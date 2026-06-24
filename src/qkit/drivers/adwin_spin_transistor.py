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
__version__ = '0.1_20260521'
__author__ = 'Luca Kosche, Joshua Gabriel'

import logging as log
from pathlib import Path
from time import sleep
import ADwin as adw
import numpy as np
from qkit.core.instrument_base import Instrument
from qkit.drivers.adwinlib.io_handler import AdwinIO, AdwinModeError
from qkit.drivers.adwinlib.io_handler import AdwinLimitError
from qkit.drivers.adwinlib.io_handler import AdwinArgumentError
from qkit.drivers.adwinlib.fw_decoder import decode_adbasic_firmware, AdwinFirmwareError
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

class adwin_spin_transistor(Instrument):
    ''' ADwin driver to handle kHz lockin + readout while performing
        sweeps on the output. So far the T11 & T12 processor, 16-bit output
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

        # Initialize ADwin instrument
        log.info('Initializing adwin_spin_transistor instrument')
        Instrument.__init__(self, name, tags=['physical','ADwin_ProII'])

        # create AdwinIO Instance
        self.aio = AdwinIO(hard_config, soft_config)

        # create ADwin Instance
        self.adw = adw.ADwin(DeviceNo=devicenumber, raiseExceptions=1,
                             useNumpyArrays=True)

        # Add driver parameters
        self.add_parameter('driver_state', type=str, flags=Instrument.FLAG_GET,
                           tags=['driver'])

        # Add adwin parameters
        self.add_parameter('adwin_outputs', type=dict, flags=Instrument.FLAG_GET,
                           tags=['adwin'])
        self.add_parameter('adwin_inputs', type=dict, flags=Instrument.FLAG_GET,
                           tags=['adwin'])
        self.add_parameter('output_buffer', type=dict, flags=Instrument.FLAG_GETSET,
                           tags=['adwin'])

        # Add lockin parameters
        self.add_parameter('lockin_frequency', type=float, flags=Instrument.FLAG_GETSET,
                           tags=['lockin'])
        self.add_parameter('lockin_amplitude', type=float, flags=Instrument.FLAG_GETSET,
                           tags=['lockin'])
        self.add_parameter('lockin_tao', type=float, flags=Instrument.FLAG_GETSET,
                           tags=['lockin'])
        self.add_parameter('lockin_phase', type=float, flags=Instrument.FLAG_GETSET,
                           tags=['lockin'])
        self.add_parameter('lockin_maf', type=int, flags=Instrument.FLAG_GETSET,
                           tags=['lockin'])
        self.add_parameter('lockin_params', type=dict, flags=Instrument.FLAG_GET,
                           tags=['lockin'])
        self.add_parameter('lockin_active', type=int, flags=Instrument.FLAG_GET,
                           tags=['lockin','adwin'])
        self.add_parameter('lockin_bias', type=float, flags=Instrument.FLAG_GETSET,
                           tags=['lockin'])

        # Add sweep parameters
        self.add_parameter('sweep_duration', type=float, flags=Instrument.FLAG_GETSET,
                           tags=['sweep'])
        self.add_parameter('sweep_target', type=dict, flags=Instrument.FLAG_GETSET,
                           tags=['sweep'])
        self.add_parameter('sweep_active', type=int, flags=Instrument.FLAG_GET,
                           tags=['sweep','adwin'])

        # Add measurement parameters
        self.add_parameter('sample_rate', type=float, flags=Instrument.FLAG_GETSET,
                           tags=['readout'])
        self.add_parameter('readout_inputs', type=list, flags=Instrument.FLAG_GETSET,
                           tags=['readout'])


        # Add functions
        self.add_function('init_measurement')
        self.add_function('stop_measurement')
        self.add_function('send_trigger')
        self.add_function('start_sweep')
        self.add_function('stop_sweep')
        self.add_function('measure_sweep')
        self.add_function('measure_static')
        self.add_function('measure_comm_test')
        self.add_function('do_get_fifo_data')

        # list of parameters, that needs to be set for lockin
        self._lockin_param_list = ['frequency', 'amplitude', 'tao',
                                   'phase', 'maf']

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

########################################################################
##################### GETTER AND SETTER FUNCTIONS ######################
########################################################################

    def do_set_lockin_frequency(self, val):
        ''' Set lockin frequency at adwin.'''
        if not MIN_FREQUENCY <= val <= MAX_FREQUENCY:
            raise AdwinLimitError
        self.adw.Set_FPar(FREQUENCY, val)

    def do_get_lockin_frequency(self):
        ''' Get real lockin frequency from adwin.'''
        return self.adw.Get_FPar(REPORT_FREQUENCY)

    def do_set_lockin_amplitude(self, val, val_format='qty'):
        ''' Set lockin amplitude at adwin.'''
        if val_format == 'qty':
            self._lockin_amp = val
            amp_bits = self.aio.qty2bit(self._lockin_amp, card=LOCKIN_CARD,
                                        channel=LOCKIN_CHANNEL, absolute=False)
            self.adw.Set_Par(AMPLITUDE, amp_bits)
        else:
            self._lockin_amp = self.aio.bit2qty(val, card=LOCKIN_CARD,
                                    channel=LOCKIN_CHANNEL, absolute=False)
            self.adw.Set_Par(AMPLITUDE, val)

    def do_get_lockin_amplitude(self, output_format='qty'):
        ''' Get lockin amplitude from adwin.'''
        if output_format == 'qty':
            return self.aio.bit2qty(self.adw.Get_Par(AMPLITUDE), card=LOCKIN_CARD,
                                    channel=LOCKIN_CHANNEL, absolute=False)
        elif output_format == 'bit':
            return self.adw.Get_Par(AMPLITUDE)
        else:
            raise AdwinArgumentError(f'Output format {output_format} not supported.')

    def do_set_lockin_tao(self, val):
        ''' Set lockin low pass filter constant at adwin.'''
        if isinstance(val, (float, int)) and val > PROCESS_TIME:
            self.adw.Set_FPar(TAO_LOWPASS, val)
        else:
            log.info('ADwin: Lockin: No lowpass applied')
            self.adw.Set_FPar(TAO_LOWPASS, PROCESS_TIME)

    def do_get_lockin_tao(self):
        ''' Get lockin low pass filter constant from adwin.'''
        return self.adw.Get_FPar(TAO_LOWPASS)

    def do_set_lockin_phase(self, val):
        ''' Set lockin reference phase shift at adwin.'''
        self.adw.Set_FPar(LOCKIN_PHASE, val)

    def do_get_lockin_phase(self):
        ''' Get lockin reference phase shift from adwin.'''
        return self.adw.Get_FPar(LOCKIN_PHASE)

    def do_set_lockin_maf(self, val):
        ''' Set lockin moving average filter length at adwin.'''
        if val is None:
            log.info('ADwin: Lockin: No maf applied')
            self.adw.Set_Par(MAF, 0)
        elif not isinstance(val, int):
            log.error('Adwin: Lockin: maf value has to be integer or None!')
            raise AdwinArgumentError
        else:
            maf_len = val / (PROCESS_TIME * self.adw.Get_FPar(FREQUENCY))
            if maf_len < MAF_ARRAY_LEN:
                self.adw.Set_Par(MAF, val)
            else:
                log.error('Adwin: Lockin: maf value too high! Max maf is %s s '
                          + 'which corresponds to maf_len of %s, but got maf_len'
                          + 'of %s. Consider increasing MAF_ARRAY_LEN in the '
                          + 'firmware and this driver if you want to use higher maf values.',
                          MAF_ARRAY_LEN * PROCESS_TIME, MAF_ARRAY_LEN, maf_len)
                raise AdwinLimitError

    def do_get_lockin_maf(self):
        ''' Get lockin moving average filter length from adwin.'''
        return self.adw.Get_Par(MAF)

    def do_get_lockin_params(self, output_format='qty'):
        ''' Get all lockin parameters from adwin and return as dict.'''
        params = {}
        params['frequency'] = self.adw.Get_FPar(REPORT_FREQUENCY)
        if output_format == 'qty':
            params['amplitude'] = self.aio.bit2qty(self.adw.Get_Par(AMPLITUDE),
                                                 card=LOCKIN_CARD,
                                                 channel=LOCKIN_CHANNEL,
                                                 absolute=False)
        elif output_format == 'bit':
            params['amplitude'] = self.adw.Get_Par(AMPLITUDE)
        else:
            raise AdwinArgumentError(f'Output format {output_format} not supported.')
        params['tao'] = self.adw.Get_FPar(TAO_LOWPASS)
        params['phase'] = self.adw.Get_FPar(LOCKIN_PHASE)
        params['maf'] = self.adw.Get_Par(MAF)
        params['active'] = bool(self.adw.Get_Par(LOCKIN_ACTIVE))
        return params

    def do_set_lockin_bias(self, val):
        ''' Set lockin bias voltage at adwin.'''
        bias_bits = self.aio.qty2bit(val, card=LOCKIN_CARD,
                                     channel=LOCKIN_CHANNEL)
        lockin_par = self._get_output_par(LOCKIN_CARD, LOCKIN_CHANNEL)
        self.adw.Set_Par(lockin_par, bias_bits)

    def do_get_lockin_bias(self, output_format='qty'):
        ''' Get lockin bias voltage from adwin.'''
        lockin_par = self._get_output_par(LOCKIN_CARD, LOCKIN_CHANNEL)
        bias_bits = self.adw.Get_Par(lockin_par)
        if output_format == 'qty':
            return self.aio.bit2qty(bias_bits, card=LOCKIN_CARD,
                                    channel=LOCKIN_CHANNEL, absolute=True)
        elif output_format == 'bit':
            return bias_bits
        else:
            raise AdwinArgumentError(f'Output format {output_format} not supported.')

    def do_set_sweep_duration(self, val):
        ''' Set sweep duration at adwin.'''
        self.adw.Set_FPar(SWEEP_DURATION, val)

    def do_get_sweep_duration(self):
        ''' Get sweep duration from adwin.'''
        return self.adw.Get_FPar(REPORT_DURATION)

    def do_set_sweep_target(self, target):
        ''' Set sweep target at adwin.'''
        # first we need all the current outputs of the adwin as list of
        # bit values sorted by card and channel (this way the adwin fw
        # gets the command for the target values of a sweep)
        current_bits = self.do_get_output_buffer(out_format='bit', select='all')
        target_bits = []
        for name in self.aio.get_sorted_channel_list():
            if name in list(target):
                target_bits.append(self.aio.qty2bit(target[name], name=name))
            else:
                target_bits.append(current_bits[name])
        self.adw.SetData_Long(target_bits, SWEEP_TARGET, 1,
                              len(target_bits))

    def do_get_sweep_target(self, output_format='qty'):
        ''' Get sweep target from adwin.'''
        target_bits = self.adw.GetData_Long(SWEEP_TARGET, 1, NB_OUTS)
        target = {}
        for i, name in enumerate(self.aio.get_sorted_channel_list()):
            if output_format == 'qty':
                target[name] = self.aio.bit2qty(target_bits[i], name=name,
                                                absolute=True)
            elif output_format == 'bit':
                target[name] = target_bits[i]
            else:
                raise AdwinArgumentError(f'Output format {output_format} not supported.')
        return target

    def do_get_sweep_active(self):
        ''' Get sweep active flag from adwin.'''
        return self.adw.Get_Par(SWEEP_ACTIVE)

    def do_set_sample_rate(self, val):
        ''' Set sample rate at adwin.'''
        self.adw.Set_FPar(SAMPLE_RATE, val)

    def do_get_sample_rate(self):
        ''' Get real sample rate from adwin.'''
        return self.adw.Get_FPar(REPORT_SAMPLE_RATE)

    def do_set_readout_inputs(self, inputs):
        ''' Set list of inputs for readout of measurement.'''
        for inp in inputs:
            if inp not in INS:
                raise AdwinArgumentError
        self._inputs = inputs

    def do_get_readout_inputs(self):
        ''' Get list of inputs set for readout of measurement.'''
        return self._inputs

    def do_get_adwin_outputs(self, connected=False):
        ''' Get output channels of adwin as dict.'''
        if connected:
            return self.aio.list_connected_outputs()
        return self.aio.list_all_outputs()

    def do_get_adwin_inputs(self):
        ''' Get input channels of adwin as dict.'''
        return self.aio.list_connected_inputs()
    
    def do_get_output_buffer(self, out_format='qty', select='connected'):
        ''' Get the buffer in which the Adwin saveds the current output
            values of the DAC's. This can be useful after a reboot of
            the adwin in which the adwin can loose this information. '''
        if select == 'connected':
            outs_list = self.aio.list_connected_outputs()
        elif select == 'all':
            outs_list = self.aio.list_all_outputs()
        else:
            raise AdwinArgumentError(f'Select {select} not supported.')
        outs = {}
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
                raise AdwinArgumentError(f'Output format {out_format} not supported.')
        return outs

    def do_set_output_buffer(self, outs:dict, val_format='qty'):
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


########################################################################
####################### MEASUREMENT ROUTINES ###########################
########################################################################

    def send_trigger(self):
        """ Set trigger val"""
        log.info('Adwin set trigger.')
        self.adw.Set_Par(TRIGGER_PAR, 1)

    def start_sweep(self, target, duration, wait=True, clearFIFO=True):
        """ Ramp the outputs of the ADwin wihtout measurement.
            If wait==True it waits for the sweep to be finished. """
        # sanity checks
        self._check_measurement_active()
        self._warn_if_fifo_to_small(duration)
        # start sweep
        self._start_sweep(target, duration)
        if wait:
            sleep(duration)
            while self.adw.Get_Par(SWEEP_ACTIVE) == 1:
                sleep(0.01)
        if clearFIFO:
            for i in INS.values():
                self.adw.Fifo_Clear(i)
        if wait is True:
            log.info('Adwin finished sweep.')
        else:
            log.info('Adwin sweeping with no idea, when it ends.')

    def measure_sweep(self, target, duration):
        ''' Start a sweep while measuring with lockin with minimal 
            communication between adwin-PC (buffering the measurement
            in fifo). The sample rate is determined by the lockin
            process which needs to be already running. '''
        # start sweep without clearing the fifos, since we want to fetch the data after its finished
        self.start_sweep(target, duration, wait=True, clearFIFO=False)
        # fetch measurement data from adwin and return
        return self._fetch_data_from_fifos()

    def measure_static(self, duration):
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

    def do_get_fifo_data(self):
        ''' Get the data currently in the fifos without stopping the
            measurement process. This can be used for a rough live view of
            the measurement, but since communication with the adwin can
            cause jitter, it is not recommended to use this function during
            a critical measurement. '''
        self._check_measurement_active()
        return self._fetch_data_from_fifos()


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
        # set sample rate, lockin bias voltage and readout inputs
        self.do_set_sample_rate(sample_rate)
        self.do_set_lockin_bias(bias)
        self.do_set_readout_inputs(inputs)

        # check that all necessary lockin parameters are given
        if set(self._lockin_param_list) == set(lockin_params.keys()):
            try:
                self.do_set_lockin_frequency(lockin_params['frequency'])
                self.do_set_lockin_amplitude(lockin_params['amplitude'])
                self.do_set_lockin_phase(lockin_params['phase'])
                self.do_set_lockin_tao(lockin_params['tao'])
                self.do_set_lockin_maf(lockin_params['maf'])
                lockin_flag = True
            except KeyError as exc:
                raise AdwinArgumentError from exc
        else:
            log.warning('Not all lockin parameters set! Falling back to'
                        +' dc measurement')
            # Set 'fake' lockin parameters which have no effect
            self.do_set_lockin_frequency(125)
            self.do_set_lockin_amplitude(0)
            self.do_set_lockin_phase(0)
            self.do_set_lockin_tao(2e-6)
            self.do_set_lockin_maf(1)
            lockin_flag = False

        # start lockin process
        log.info('Adwin starting lockin!')
        self.adw.Start_Process(LOCKIN_PROCESS_NO)
        sleep(0.1)      # delay for init, so the real parameters are calculated at the adwin

        self._sample_rate = self.do_get_sample_rate()       # get real sample rate
        if lockin_flag:
            log.warning('ADwin: lock-in: frequency = %s Hz. '
                        + 'amplitdue = %s V, tao = %s s, '
                        + 'sample_rate = %s', self.do_get_lockin_frequency(),
                        self._lockin_amp, self.do_get_lockin_tao(), self._sample_rate)
        else:
            log.warning('ADwin dc measurement initialized with '
                        + 'sample_rate = %s', self._sample_rate)

        self._state = 'measurement_ready'       # set state of driver to measurement ready
        for i in INS.values():
            self.adw.Fifo_Clear(i)

########################################################################
########################## OTHER FUNCTIONS #############################
########################################################################

    def stop_measurement(self):
        """ Stops the lockin process. No lockin signal is applied and no
            readout is triggered by a sweep anymore. """
        self._check_measurement_active()
        log.info('Adwin stopping lockin')
        self.adw.Stop_Process(LOCKIN_PROCESS_NO)
        self._state = 'processes_loaded'

    def stop_sweep(self):
        """ Stopping sweep process immediately """
        log.info('Adwin stopping sweep.')
        self.adw.Stop_Process(SWEEP_PROCESS_NO)

    def _start_sweep(self, target, duration):
        # set sweep parameters at adwin
        self.do_set_sweep_duration(duration)
        self.do_set_sweep_target(target)
        log.info('Adwin starting %.3f second sweep.', duration)
        # start sweep process
        self.adw.Start_Process(SWEEP_PROCESS_NO)
        self.adw.Set_Par(SWEEP_ACTIVE, 1)

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

    def _get_output_par(self, card, channel):
        ''' By convention the Output Par holding the current output
            value is defined like this '''
        return card * 10 + channel

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
            output_buffer.update(self.do_get_output_buffer(out_format='bit'))
            output_values = self.do_get_output_buffer(out_format='qty')
            msg = ('Adwin: Current firmware: Spin-Transistor: '
                 + f'{version}. Current outputs are {output_values}')
            log.warning(msg)
            log.warning(self.do_get_output_buffer(out_format='bit'))
        elif firmware == 'ELECTROMIGRATION':
            output_buffer.update(self.do_get_output_buffer(out_format='bit'))
            output_values = self.do_get_output_buffer(out_format='qty')
            msg = ('Adwin: Current firmware: Electromigration: '
                 + f'{version}. Current outputs are {output_values}')
            log.warning(msg)
            log.warning(self.do_get_output_buffer(out_format='bit'))
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
        self.do_set_output_buffer(output_buffer, val_format='bit')

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
