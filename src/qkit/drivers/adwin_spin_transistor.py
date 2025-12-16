''' ADwin driver for the Spin-Transistor measurement. The idea is to
    view the Adwin as a highly configurable measurement device (since it
    is a programmable fpga with different hardware configurations it
    will always be specially programmed to do certain tasks efficiently)
    Here we view the Adwin as a unit together with its peripherals, like
    current sources, voltage dividers, iv_converters, filters, coils, ..
    We just want to tell it what physical quantities we want to measure 
    or apply at the sample (B-Fields, voltages, currents ...)
    Therefore the driver includes two parts:
        * AdwinIO which handles the translation between physical
          quantities and BITS.
        * The insturment driver (adwin_spin_transistor) itself only
          containes the measurement functions using bit values for the 
          DAC/ADC.
    
    So far, all measurements consist of a sweep process and a lockin
    process:
        * The lockin process can apply a sine wave at a hard coded adwin
          output and performs the measurement of the input with 500kHz
          sample_rate. It contains the lockin demodulation with low pass
          filter and can send subsampled data to the PC (depending on 
          the filter constant of the filters it does not make sense to
          use a to high data rate). The same process can also be used to
          measure the raw input of the ADC with full 500kHz or
          subsampled to a smaller sample_rate.
        * The sweep process can perform a linear sweep of the adwin
          outputs in a certain time. As soon as the sweep starts, it
          triggers the lockin process.
    
    Modes:
        * LOCKIN: After initiliazing the ADwin the lockin process has to
          be started setting the desired lockin-parameters. Then the
          lockin will continously just without sending data to the PC.
          Therfore the filter parameters are always initialized.
          As soon as the "measurment_active" flag is set to "1", the
          lockin will write the values to the FIFO. Since communication
          between PC and Adwin does affect the measurement by
          introducing jitter and maybe more, it makes sense to fetch the
          data after the measurement is done, limiting  (sample_rate *
          measurement time) by the length of the FIFOs.
        * DC: Here we just want to use the lockin prcoess for data
          aquisition, therefore just set the amplitude of the lockin to
          zero to not apply a lockin signal.

    
    ToDO:   * Sanity checky for sweep parameters e.g.
            * Maybe programm the LP filter for dc measurements as well
    '''

__all__ = ['adwin_spin_transistor']
__version__ = '0.1_20240514'
__author__ = 'Luca Kosche'

import logging as log
from pathlib import Path
from time import sleep
import ADwin as adw
import numpy as np
from qkit.core.instrument_base import Instrument
from qkit.drivers.adwinlib.io_handler import AdwinIO, AdwinModeError
from qkit.drivers.adwinlib.io_handler import AdwinLimitError
from qkit.drivers.adwinlib.io_handler import AdwinArgumentError
from qkit.drivers.adwinlib.fw_decoder import decode_adbasic_firmware
from qkit.drivers.adwinlib.nanoqt_tools import read_nanoqt_outputs

# These constants have to be synchronised with the definitions in the
# ADbasic firmware! For parameters where time is involved (frequency,
# sample_rate, sweep_duration) the exact values used by the firmware
# are sometimes not the set values due to the time quantization of the
# hardware. Therefore the real values can be read out after starting
# the process

#NANOQT SETTINGS
NANOQT_OUT_CARD = 3

# HARD CODED IN SWEEP AND LOCKIN PROCESS
PROCESS_TIME = 2e-6
LOCKIN_ACTIVE = 3      # Reports: "1" if lockin process is active
MEASURE_ACTIVE = 4     # Command: lockin process to write data to FIFOS
LOCKIN_BIAS = 38       # Command: lockin process to add bias to lockin

# HARD CODED IN LOCKIN PROCESS
VERSION_PROCESS_1 = 1  # Read: (Par)  Version of lockin process
AMPLITUDE = 5          # Set:  (Par)  Lockin amplitude (bits)
FREQUENCY = 5          # Set:  (FPar) Lockin frequency (Hz)
REPORT_FREQUENCY = 6   # Read: (FPar) Lockin frequency (Hz)
LOCKIN_PHASE = 7       # Set:  (FPar) Lockin reference phase shift (rad)
SAMPLE_RATE = 8        # Set:  (FPar) Sample rate after subsampling (Hz)
REPORT_SAMPLE_RATE = 9 # Read: (FPar) Current samplerate (Hz)
TAO_LOWPASS = 10       # Set:  (FPAR) Tc of lockin lowpass filter
MAF = 6                # Set:  (Par)  Moving average filter length in
                       # lockin periods -> F_0poles = FREQUENCY / MAF
FIFO_LEN = 1000003     # Hard coded: Length of data transmittion FIFOS
INS = { 'inph': 1,     # Data_1: (float) Inphase data FIFO
        'quad': 2,     # Data_2: (float) Quadrature data FIFO
        'raw': 3}      # Data_3: (float) Raw input signal data FIFO
LOCKIN_CARD = 3        # Hard coded: DAC card for lockin output
LOCKIN_CHANNEL = 8     # Hard coded: DAC channel for lockin output
LOCKIN_LEN = 8003      # Hard coded: Length of lockin signal arrays
MAF_ARRAY_LEN = 100100


#HARD CODED IN SWEEP PROCESS
VERSION_PROCESS_2 = 2  # Read: (Par)  Version of sweep process
SWEEP_ACTIVE = 11      # Command, Read: (Par) Start/Check Sweep (=1)
NB_OUTS = 8            # Hard coded: amount of ADwin outputs
SWEEP_DURATION = 11    # Set:  (FPar) Duration of the sweep (s)
REPORT_DURATION = 12   # Read: (FPAr) Duration of the sweep (s)
SWEEP_TARGET = 11      # Set: (Data (Long)) Target output of sweep (bit)

# RESULTING FROM ADBASIC FILES
TRIGGER_PAR = 30
OUT1_PAR= LOCKIN_CARD * 10 + 1 #The first output for card 3 is Par_31
MIN_FREQUENCY = 62.48
MAX_FREQUENCY = 40E3 # too high frequency might suffer from jitter

LOCKIN_PROCESS_NO = 1
SWEEP_PROCESS_NO = 2

class AdwinFirmwareError(Exception):
    """ Error raised, when Firmware running on Adwin is not compatible
        with python adwin driver"""

class adwin_spin_transistor(Instrument):
    ''' ADwin driver to handle kHz lockin + readout while performing
        sweeps on the output. So far the T11 processor, 16-bit output
        card and 18-bit input card are supported. '''
    def __init__(self,
        name='my_instrument',
        processor='T11',
        lockin_filter='maf_1stageLP', # maf_1stageLP or 4stageLP
        devicenumber=1,
        bootload=True,
        trigger=False,
        hard_config=None,
        soft_config=None):

        # create AdwinIO Instance
        self.aio = AdwinIO(hard_config, soft_config)

        # create ADwin instance
        self.adw = adw.ADwin(DeviceNo=devicenumber, raiseExceptions=1,
                             useNumpyArrays=True)

        # list of parameters, that needs to be set for lockin
        self._lockin_param_list = ['frequency', 'amplitude', 'tao',
                                   'phase', 'maf']

        log.info('Initializing adwin_spin_transistor instrument')
        Instrument.__init__(self, name, tags=['physical','ADwin_ProII'])

        self._state = 'init'
        self._sample_rate = None
        self._lockin_amp = None
        self._inputs = []

        # Set 'bootload' to 'False' to not reboot the Adwin.
        if bootload:
            self._bootload(processor, lockin_filter, trigger)
        else:
            firmware, version = self._read_adwin_firmware()
            if firmware != 'SPIN-TRANSISTOR':
                msg = (f'ADwin is running firmware {firmware}, version '
                     + f' {version}, which is not compatible with this '
                     + ' driver. Consider booting using bootload=True.')
                log.critical(msg)
                raise AdwinFirmwareError

        # implement general functions
        self.add_function("sweep")
        self.add_function("sweep_measure")
        self.add_function("measure")
        self.add_function("init_measurement")
        self.add_function("stop_measurement")
        self.add_function("read_outputs")
        self.add_function("stop_sweep")
        self.add_function("set_output_buffer")
        self.add_function("list_connected_outputs")

########################################################################
####################### MEASUREMENT ROUTINES ###########################
########################################################################

    def send_trigger(self):
        """ Set trigger val"""
        log.info('Adwin set trigger.')
        self.adw.Set_Par(TRIGGER_PAR, 1)

    def sweep(self, target, duration, wait=True, clearFIFO=True):
        """ Ramp the outputs of the ADwin wihtout measurement.
            If wait==True it waits for the sweep to be finished. """
        # sanity checks
        self._check_measurement_active()
        self._warn_if_fifo_to_small(duration)
        # start sweep
        self._start_sweep(target, duration)
        while wait is True and self.adw.Get_Par(SWEEP_ACTIVE) == 1:
            pass
        if clearFIFO:
            for i in INS.values():
                self.adw.Fifo_Clear(i)
        if wait is True:
            log.info('Adwin finished sweep.')
        else:
            log.info('Adwin sweeping with no idea, when it ends.')

    def sweep_measure(self, target, duration):
        ''' Start a sweep while measuring with lockin with minimal 
            communication between adwin-PC (buffering the measurement
            in fifo). The sample rate is determined by the lockin
            process which needs to be already running. '''
        # sanity checks
        self._check_measurement_active()
        self._warn_if_fifo_to_small(duration)
        # start sweep
        self._start_sweep(target, duration)
        # wait for sweep to be finished (this might not be the best
        # timing, but limits communication during measurement)
        sleep(duration)
        # check if sweep has ended
        while self.adw.Get_Par(SWEEP_ACTIVE) == 1:
            pass
        # fetch measurement data from adwin and return
        return self._fetch_data_from_fifos()

    def measure(self, duration):
        ''' Measure DC input for duration with full 500kHz sample rate
            for duration seconds. If no lockin should be applied, start
            lockin process with amplitude zero. Amount of collectable
            data is limited by fifo buffer length. '''
        # sanity checks
        self._check_measurement_active()
        self._warn_if_fifo_to_small(duration)
        log.info('Adwin starting about %.3f second measurement.', duration)
        # enable data aquisition
        self.adw.Set_Par(MEASURE_ACTIVE, 1)
        sleep(duration)
        # disable data aquisition
        self.adw.Set_Par(MEASURE_ACTIVE, 0)
        # fetch measurement data from adwin and return
        return self._fetch_data_from_fifos()

    def measure_comm_test(self, duration, comm_delay):
        ''' Start a measurement for time duration, but start
            communication to adwin after comm_delay until measurement is
            finished '''
        # sanity checks
        self._check_measurement_active()
        self._warn_if_fifo_to_small(duration)
        samples = duration * self._sample_rate
        # enable data aquisition
        self.adw.Set_Par(MEASURE_ACTIVE, 1)
        sleep(comm_delay)
        fifo_full = 0
        while fifo_full < samples:
            fifo_full = self.adw.Fifo_Full(INS['raw'])
        # disable data aquisition
        self.adw.Set_Par(MEASURE_ACTIVE, 0)
        # fetch measurement data from adwin and return
        return self._fetch_data_from_fifos()

    def _fetch_data_from_fifos(self):
        ''' Fetch all data from the fifos which has been set as inputs
            during init_measurement() and clear all other fifos '''
        res = {'inph': None, 'quad': None, 'raw': None}
        # Get same number of samples for inph and quad, needed for amp calculation
        samples = min(self.adw.Fifo_Full(INS['inph']), self.adw.Fifo_Full(INS['quad']))
        for key in res:
            if key in self._inputs:
                if key == 'raw':
                    samples = self.adw.Fifo_Full(INS[key])
                # Get input in bit values
                if samples:
                    tmp = self.adw.GetFifo_Float(INS[key], samples)
                    # Transform bit to physical quantity
                    qty = self.aio.bit2qty(tmp, name='input', absolute=False)
                    # if inph or quad component divide by amplitude to get dI/dV
                    if key in ['inph', 'quad']:
                        res[key] = np.divide(qty, self._lockin_amp)
                    else:
                        res[key] = qty
                else:
                    res[key] = np.array([])
            else:
                self.adw.Fifo_Clear(INS[key])
        return res

########################################################################
########################## PREPARE MEASUREMENT #########################
########################################################################

    def init_measurement(self, sample_rate, bias, inputs,
                         **lockin_params):
        ''' Initialize a lockin/dc measurement. For simplicity of the
            ADbasic driver, the lockin is always applied, but with
            amplitude 0 effectively there is no lockin signal. '''
        # stop old measurement process if still running
        if self._state == 'measurement_ready':
            self.adw.Stop_Process(LOCKIN_PROCESS_NO)
        # set sample rate
        self.adw.Set_FPar(SAMPLE_RATE, sample_rate)
        # set bias voltage
        bias_bits = self.aio.qty2bit(bias, card=LOCKIN_CARD,
                                     channel=LOCKIN_CHANNEL)
        lockin_par = self._get_output_par(LOCKIN_CARD, LOCKIN_CHANNEL)
        self.adw.Set_Par(lockin_par, bias_bits)
        # set inputs
        for inp in inputs:
            if inp not in INS:
                raise AdwinArgumentError
        self._inputs = inputs

        # check that all necessary lockin parameters are given
        if set(self._lockin_param_list) == set(lockin_params.keys()):
            try:
                # Set lockin frequency after checking if its valid
                freq = lockin_params['frequency']
                if not MIN_FREQUENCY <= freq <= MAX_FREQUENCY:
                    raise AdwinLimitError
                self.adw.Set_FPar(FREQUENCY, freq)
                # Set lockin amplitude after translating to bit value
                self._lockin_amp = lockin_params['amplitude']
                amp_bits = self.aio.qty2bit(self._lockin_amp,
                                            card=LOCKIN_CARD,
                                            channel=LOCKIN_CHANNEL,
                                            absolute=False)
                self.adw.Set_Par(AMPLITUDE, amp_bits)
                # Set phase shift of lockin reference
                phase = lockin_params['phase']
                self.adw.Set_FPar(LOCKIN_PHASE, phase)
                # Set filter constant tao of low pass filter
                tao = lockin_params['tao']
                if isinstance(tao, (float, int)) and tao > PROCESS_TIME:
                    self.adw.Set_FPar(TAO_LOWPASS, tao)
                else:
                    log.info('ADwin: Lockin: No lowpass applied')
                    self.adw.Set_FPar(TAO_LOWPASS, PROCESS_TIME)
                # Set length of moving average filter ( in multiples of
                # lockin period)
                maf = lockin_params['maf']
                if isinstance(maf, int):
                    maf_len = maf / (PROCESS_TIME * freq)
                    if maf_len < MAF_ARRAY_LEN:
                        self.adw.Set_Par(MAF, maf)
                    else:
                        log.error('Adwin: Lockin: maf too big!')
                        raise AdwinArgumentError
                elif maf is None:
                    log.info('ADwin: Lockin: No maf applied')
                    self.adw.Set_Par(MAF, 0)
                else:
                    log.error('Adwin: Lockin: maf val supported')
                    raise AdwinArgumentError
                # Set lockin flag
                lockin_flag = True
            except KeyError as exc:
                raise AdwinArgumentError from exc
        else:
            log.warning('Not all lockin parameters set! Falling back to'
                        +' dc measurement')
            # Set 'fake' lockin parameters which have no effect
            self.adw.Set_FPar(FREQUENCY, 125)
            self.adw.Set_Par(AMPLITUDE, 0)
            self.adw.Set_FPar(LOCKIN_PHASE, 0)
            self.adw.Set_FPar(TAO_LOWPASS, 2e-6)
            self.adw.Set_Par(MAF, 1)
            lockin_flag = False

        # start lockin process
        log.info('Adwin starting lockin!')
        self.adw.Start_Process(LOCKIN_PROCESS_NO)

        # make sure process init has run before asking for return values
        sleep(0.1)

        # get actual parameters
        sample_rate = self.adw.Get_FPar(REPORT_SAMPLE_RATE)
        self._sample_rate = sample_rate
        # set measurement ready state
        self._state = 'measurement_ready'
        # handle logging for each mode
        if lockin_flag is True:
            freq = self.adw.Get_FPar(REPORT_FREQUENCY)
            log.warning('ADwin: lock-in: frequency = %s Hz. '
                        + 'amplitdue = %s V, tao = %s s, '
                        + 'sample_rate = %s', freq, self._lockin_amp, tao,
                        sample_rate)
        else:
            log.warning('ADwin dc measurement initialized with '
                        + 'sample_rate = %s', sample_rate)
        for i in INS.values():
            self.adw.Fifo_Clear(i)

    def stop_measurement(self):
        """ Stops the lockin process. No lockin signal is applied and no
            readout is triggered by a sweep anymore. """
        self._check_measurement_active()
        log.info('Adwin stopping lockin')
        self.adw.Stop_Process(LOCKIN_PROCESS_NO)
        self._state = 'processes_loaded'

########################################################################
########################## OTHER FUNCTIONS #############################
########################################################################

    def get_lockin_frequency(self):
        ''' Return lockin frequency '''
        return self.adw.Get_FPar(REPORT_FREQUENCY)

    def get_sample_rate(self):
        ''' Return lockin frequency '''
        return self.adw.Get_FPar(REPORT_SAMPLE_RATE)

    def get_duration(self):
        ''' Return duration of the next sweep '''
        return self.adw.Get_FPar(REPORT_DURATION)

    def is_lockin_active(self) -> int:
        ''' Return 1 if lockin is active, 0 otherwise '''
        return self.adw.Get_Par(LOCKIN_ACTIVE)

    def _get_output_par(self, card, channel):
        ''' By convention the Output Par holding the current output
            value is defined like this '''
        return card * 10 + channel

    def list_connected_outputs(self):
        ''' Return copy of dictionary of all outputs '''
        return self.aio.list_connected_outputs()

    def read_outputs(self, out_format='qty', select='connected'):
        """ Read the current saved output values of the ADwin. After a 
            restart this might not be the correct values. """
        # Read all adwin parameters holding the current output values
        outs = {}
        if select == 'connected':
            outs_list = self.aio.list_connected_outputs()
        elif select == 'all':
            outs_list = self.aio.list_all_outputs()

        else:
            raise AdwinArgumentError

        for name in outs_list:
            card, channel = self.aio.get_card_channel(name)
            par_no = self._get_output_par(card, channel)
            par_val = self.adw.Get_Par(par_no)
            if out_format == 'qty':
                outs[name] = self.aio.bit2qty(par_val, card=card,
                                             channel=channel,
                                             absolute=True)
            elif out_format == 'bit':
                outs[name] = par_val
            else:
                raise AdwinArgumentError
        return outs

    def stop_sweep(self):
        """ Stopping sweep process immediately """
        log.info('Adwin stopping sweep.')
        self.adw.Stop_Process(SWEEP_PROCESS_NO)

    def set_output_buffer(self, outs:dict, val_format='qty'):
        ''' Set the buffer in which the Adwin saveds the current output
            values of the DAC's. This can be useful after a reboot of
            the adwin in which the adwin can loose this information. '''
        for name, val in outs.items():
            # If output value is given as physical quantity-> translate
            if val_format == 'qty':
                val = self.aio.qty2bit(val, name=name, absolute=True)
            # Get ADbasic Par No. of output 'key' defined by convention
            card, channel = self.aio.get_card_channel(name)
            par_no = self._get_output_par(card, channel)
            # Set ADbasic Par of for the output
            self.adw.Set_Par(par_no, int(val))

    def _start_sweep(self, target, duration, delay=0.05):
        # set sweep parameters
        self.adw.Set_FPar(SWEEP_DURATION, duration)
        # first we need all the current outputs of the adwin as list of
        # bit values sorted by card and channel (this way the adwin fw
        # gets the command for the target values of a sweep)
        current_bits = self.read_outputs(out_format='bit', select='all')
        target_bits = []
        for name in self.aio.get_sorted_channel_list():
            if name in list(target):
                target_bits.append(
                    self.aio.qty2bit(target[name], name=name))
            else:
                target_bits.append(current_bits[name])
        self.adw.SetData_Long(target_bits, SWEEP_TARGET, 1,
                              len(target_bits))
        log.info('Adwin starting %.3f second sweep.', duration)
        # initialize process
        self.adw.Start_Process(SWEEP_PROCESS_NO)
        # start process after small delay to wait for init to finish
        sleep(delay)
        self.adw.Set_Par(SWEEP_ACTIVE, 1)

    def _check_measurement_active(self):
        # just check the state of the adwin driver. It could be done by
        # reading the adwin's lockin_active par, but I want to limit
        # communication
        if self._state != 'measurement_ready':
            log.critical('ADwin: measurement not initialized. Abort! '
                         + 'Run init_measurement() first.')
            raise AdwinModeError

    def _warn_if_fifo_to_small(self, duration):
        if duration * self._sample_rate > FIFO_LEN:
            log.warning('ADwin: Fifo holds values for max %s seconds.',
            FIFO_LEN / self._sample_rate)

    def _read_adwin_firmware(self):
        try:
            fw_int32 = self.adw.Get_Par(VERSION_PROCESS_1)
            firmware, version = decode_adbasic_firmware(fw_int32)
            msg = (f'Adwin: Detected firmware {firmware}, version = '
                 + f'{version}.')
            log.warning(msg)
            return(firmware, version)
        except adw.ADwinError:
            msg = ('Adwin: Cannot detect ADwin firmware, because it is '
                 + 'not responding. Adwin turn off, just turn on, not '
                 + 'connected or overloaded.')
            log.warning(msg)
            return(None, None)

    def _bootload(self, processor, lockin_filter, trigger):
        # before boot try to read the current outputs, which can
        # fail if the adwin was power cycled and never booted since
        firmware, version = self._read_adwin_firmware()
        # Initialize output_buffer to 0V for all outputs as bits
        output_buffer = self.aio.output_zero_dict()
        # Depending on detected firmware read the current outputs
        if firmware == 'SPIN-TRANSISTOR':
            output_buffer.update(self.read_outputs(out_format='bit'))
            output_values = self.read_outputs(out_format='qty')
            msg = ('Adwin: Current firmware: Spin-Transistor: '
                 + f'{version}. Current outputs are {output_values}')
            log.warning(msg)
            log.warning(self.read_outputs(out_format='bit'))
        elif firmware == 'ELECTROMIGRATION':
            output_buffer.update(self.read_outputs(out_format='bit'))
            output_values = self.read_outputs(out_format='qty')
            msg = ('Adwin: Current firmware: Electromigration: '
                 + f'{version}. Current outputs are {output_values}')
            log.warning(msg)
            log.warning(self.read_outputs(out_format='bit'))
        elif firmware == 'NANOQT':
            output_buffer = read_nanoqt_outputs(self.adw, self.aio,
                                                output_card=NANOQT_OUT_CARD)
            msg = (f'Adwin: Current firmware: NanoQt: {version}. The '
                    + 'current outputs have been recovered to ensure a '
                    + 'nice ride with Spin-Transistor firmware.')
            log.warning(msg)
        elif firmware is None or firmware == 'unknown':
            msg = ('Adwin: Current firmware: unknown. Setting output '
                + 'buffer to zero! If outputs are not zero, recover '
                + 'them by setting the ouput buffer manually using '
                + 'set_output_buffer() BEFORE FIRST SWEEP OR '
                + 'INIT_MEASUREMENT!')
            log.critical(msg)
        else:
            log.critical('ADwin: YOU SHOULD NOT SEE THIS MEASSAGE!')

        #boot adwin
        btl_name = f"ADwin{processor.replace('T', '')}.btl"
        btl_path = Path(self.adw.ADwindir) / btl_name
        self.adw.Boot(str(btl_path))

        # Set output buffer
        self.set_output_buffer(output_buffer, val_format='bit')

        self._state = 'booted'

        # load processes
        adbasic_dir = Path(__file__).parent / 'adwinlib' / 'spin-transistor'

        if processor == 'T11':
            ext = 'TB'
        elif processor == 'T12':
            ext = 'TC'
        else:
            log.error(f'Adwin: Processor {processor} not supported.')
            raise AdwinFirmwareError

        lockin_fname = f'Pro2_T11T12_lockin_{lockin_filter}.{ext}1'
        sweep_fname = f'Pro2_T11T12_sweep.{ext}2'
        trigger_fname = f'Pro2_T11T12_trigger.{ext}3'

        lockin_process = adbasic_dir / lockin_fname
        log.info('Adwin loading: %s', lockin_process.name)
        self.adw.Load_Process(str(lockin_process))
        sweep_process = adbasic_dir / sweep_fname
        log.info('Adwin loading: %s', sweep_process.name)
        self.adw.Load_Process(str(sweep_process))

        if trigger:
            trigger_process = adbasic_dir / trigger_fname
            log.info('Adwin loading: %s', trigger_process.name)
            self.adw.Load_Process(str(trigger_process))
            self.adw.Start_Process(3)

        self._state = 'processes_loaded'

        self.adw.Set_Par(1, 0x01000000)



if __name__ == '__main__':
    pass
