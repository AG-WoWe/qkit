''' ADwin driver for the Electromigration process. The idea is to
    view the Adwin as a highly configurable measurement device (since it
    is a programmable fpga with different hardware configurations it
    will always be specially programmed to do certain tasks efficiently)
    Here we view the Adwin as a unit together with its peripherals, like
    current sources, voltage dividers, iv_converters, ..
    We just want to tell it a voltage sweep_rate for the electromigration process
    and a sample_rate for the data readout with PC. Optional parameter are:
        * report_voltage: voltage to start saving data for PC readout
        * max_voltage: maximal voltage to stop sweep, default -> 10V
        * r_limit: limit for resistance, to automatically stop voltage sweep
        * gate_sweep: additional gate sweep with half rate of source-drain

    Therefore the driver includes two parts:
        * AdwinIO which handles the translation between physical
          quantities and BITS.
        * The insturment driver (adwin_electromigration) itself only
          containes the measurement functions using bit values for the 
          DAC/ADC.
    
    So far, the electromigration consist of a sweep process and a readout
    process:
        * The readout process is to measure the raw input and calculate
          the resistance value using raw input and applied voltage
          as fast as possible. This is to immediately set the output
          voltage to zero if a resistance threshhold is reached, to
          prevent damaging the chip. The raw input is measured with
          500kHz sample_rate and can send subsampled data to the PC.
        * The sweep process can perform a linear sweep of the adwin
          outputs (source-drain/gate voltage) with a given sweep rate.
          The sweep rate for the gate voltage depends on the sweep rate
          of the source-drain voltage. As soon as the sweep starts, it
          triggers the readout process.

    
    ToDO:   * Sanity checky for sweep rate e.g.
    '''

__all__ = ['adwin_electromigration']
__version__ = '0.1_20250401'
__author__ = 'Joshua Gabriel'

import logging as log
from pathlib import Path
from time import sleep
import ADwin as adw
from qkit.core.instrument_base import Instrument
from qkit.drivers.adwinlib.io_handler import AdwinIO, AdwinModeError
from qkit.drivers.adwinlib.io_handler import AdwinArgumentError
from qkit.drivers.adwinlib.fw_decoder import decode_adbasic_firmware
from qkit.drivers.adwinlib.nanoqt_tools import read_nanoqt_outputs

# These constants have to be synchronised with the definitions in the
# ADbasic firmware! For parameters where time is involved (sample_rate,
# sweep_rate) the exact values used by the firmware are sometimes not
# the set values due to the time quantization of the hardware.
# Therefore the real values can be read out after starting the process.

# HARD CODED IN SWEEP AND READOUT PROCESS
OUTPUT_CARD = 3        # Hard coded: DAC card for electromigration output
OUTPUT_CHANNEL = 8     # Hard coded: DAC channel for source-drain voltage sweep output
GATE_CHANNEL = 7       # Hard coded: DAC channel for gate voltage sweep output

# HARD CODED IN READOUT PROCESS
VERSION_PROCESS_1 = 1  # Read: (Par)  Version of electromigration process
READOUT_ACTIVE = 3     # Reports: "1" if readout process is active
VOLTAGE = 38           # Read: (Par) Last applied voltage
REPORT_VOLTAGE = 8     # Read: (Par) Voltage to start sending data to PC
R_LIMIT = 9            # Set: (Par) Resistance limit to stop sweep ("0" is no limit)
SAMPLE_RATE = 8        # Set:  (FPar) Sample rate after subsampling (Hz)
REPORT_SAMPLE_RATE = 9 # Read: (FPar) Current samplerate (Hz)
FIFO_LEN = 1000003     # Hard coded: Length of data transmittion FIFOS
INS = {'raw': 1}       # Data_3: (float) Raw input signal data FIFO
INPUT_CARD = 2
INPUT_CHANNEL = 8
EMERGENCY_STOP = 12    # Command: (Par) Stop electromigration immediately (=1)

#HARD CODED IN SWEEP PROCESS
VERSION_PROCESS_2 = 2  # Read: (Par)  Version of sweep process
GATE_DURATION = 11     # Set: (Par) Duration for gate to sweep to zero
SWEEP_ACTIVE = 11      # Command, Read: (Par) Start/Check Sweep (=1)
MAX_VOLTAGE = 18       # Maximal voltage for sweep
GATE_SCALE = 20        # Scale for gate voltage (FPar)
SWEEP_RATE = 21        # Sweep rate of source-drain voltage (FPar)

# RESULTING FROM ADBASIC FILES
OUT1_PAR= OUTPUT_CARD * 10 + 1 #The first output for card 3 is Par_31

READOUT_PROCESS_NO = 1
SWEEP_PROCESS_NO = 2

class AdwinFirmwareError(Exception):
    """ Error raised, when Firmware running on Adwin is not compatible
        with python adwin driver"""

class adwin_electromigration(Instrument):
    ''' ADwin driver to handle electromigration process + readout while performing
        sweeps on the output. So far the T11 processor, 16-bit output
        card and 18-bit input card are supported. '''
    def __init__(self,
        name='my_instrument',
        processor='T11',
        devicenumber=1,
        bootload=True,
        hard_config=None,
        soft_config=None):

        # create AdwinIO Instance
        self.aio = AdwinIO(hard_config, soft_config)

        # create ADwin instance
        self.adw = adw.ADwin(DeviceNo=devicenumber, raiseExceptions=1,
                             useNumpyArrays=True)

        log.info('Initializing adwin_electromigration instrument')
        Instrument.__init__(self, name, tags=['physical','ADwin_ProII'])

        self._state = 'init'
        self._sample_rate = None
        self._inputs = []

        # Set 'bootload' to 'False' to not reboot the Adwin.
        if bootload:
            self._bootload(processor)
        else:
            firmware, version = self._read_adwin_firmware()
            if firmware != 'ELECTROMIGRATION':
                msg = (f'ADwin is running firmware {firmware}, version '
                     + f' {version}, which is not compatible with this '
                     + ' driver. Consider booting using bootload=True.')
                log.critical(msg)
                raise AdwinFirmwareError

        # implement general functions
        self.add_function("init_electromigration")
        self.add_function("stop_electromigration")
        self.add_function("read_outputs")
        self.add_function("stop_sweep")
        self.add_function("list_connected_outputs")

########################################################################
########################### READOUT ROUTINES ###########################
########################################################################

    def _fetch_data_from_fifos(self):
        ''' Fetch all data from the fifos which has been set as inputs
            during init_electromigration() and clear all other fifos '''
        res = {'raw': None}
        for key in res:
            if key in self._inputs:
                samples = self.adw.Fifo_Full(INS[key])
                tmp = self.adw.GetFifo_Float(INS[key], samples)
                res[key] = self.aio.bit2qty(tmp, name='input',
                                            absolute=False)
            else:
                self.adw.Fifo_Clear(INS[key])
        return res

########################################################################
########################## PREPARE ELECTROMIGRATION ####################
########################################################################

    def init_electromigration(self, sample_rate, sweep_rate, report_voltage=0,
                              max_voltage=10, r_limit=0, gatesweep=False, duration=10):
        ''' Initialize a electromigration process. '''
        # stop old electromigration process if still running
        if self._state == 'electromigration_ready':
            self.adw.Stop_Process(READOUT_PROCESS_NO)
        # set sample rate
        self.adw.Set_FPar(SAMPLE_RATE, sample_rate)
        sweep_rate = self.aio.qty2bit(sweep_rate, card=OUTPUT_CARD,
                                      channel=OUTPUT_CHANNEL, absolute=False)
        report_voltage = self.aio.qty2bit(report_voltage, card=OUTPUT_CARD,
                                      channel=OUTPUT_CHANNEL)
        max_voltage = self.aio.qty2bit(max_voltage, card=OUTPUT_CARD,
                                      channel=OUTPUT_CHANNEL)
        self.adw.Set_FPar(SWEEP_RATE, sweep_rate)
        self.adw.Set_Par(REPORT_VOLTAGE, report_voltage)
        self.adw.Set_Par(MAX_VOLTAGE, max_voltage)
        if gatesweep:
            gate_scale = 0.5 * self.aio.get_scale(name="vd") / self.aio.get_scale(name="vg")
            self.adw.Set_FPar(GATE_SCALE, gate_scale)
            self.adw.Set_Par(GATE_DURATION, duration)
        else:
            self.adw.Set_FPar(GATE_SCALE, 0)
        self.set_r_limit(r_limit)

        # set input
        self._inputs = ["raw"]

        # get actual parameters
        sample_rate = self.adw.Get_FPar(REPORT_SAMPLE_RATE)
        self._sample_rate = sample_rate
        # set electromigration ready state
        self._state = 'electromigration_ready'
        # handle logging for each mode
        log.info('ADwin electromigration initialized with '
                        + 'sample_rate = %s', sample_rate)

    def stop_electromigration(self):
        """ Stops the electromigration process. No signal is applied and no
            readout is triggered by a sweep anymore. """
        log.info('Adwin stopping electromigration')
        self.adw.Set_Par(EMERGENCY_STOP, 1)
        self.adw.Stop_Process(SWEEP_PROCESS_NO)
        self.adw.Stop_Process(READOUT_PROCESS_NO)
        self._state = 'processes_loaded'

########################################################################
########################## OTHER FUNCTIONS #############################
########################################################################

    def set_r_limit(self, r_limit):
        ''' calculate and set bit value for resistance limit '''
        # calculate r scaling factors
        r_scale = (self.aio.get_scale(card=OUTPUT_CARD, channel=OUTPUT_CHANNEL)
                   /self.aio.get_scale(card=INPUT_CARD, channel=INPUT_CHANNEL))
        r_bitscale = 2**(self.aio.get_bits(card=OUTPUT_CARD, channel=OUTPUT_CHANNEL)
                         -self.aio.get_bits(card=INPUT_CARD, channel=INPUT_CHANNEL))
        # calculate r bit value
        r_limit *= r_scale/r_bitscale
        # set r_limit
        self.adw.Set_Par(R_LIMIT, r_limit)

    def get_sample_rate(self):
        ''' Return sample rate '''
        return self.adw.Get_FPar(REPORT_SAMPLE_RATE)

    def is_readout_active(self) -> int:
        ''' Return 1 if readout is active, 0 otherwise '''
        return self.adw.Get_Par(READOUT_ACTIVE)

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


    def _start_electromigration(self, delay=0.05):
        # start electromigration process
        log.info('Adwin starting electromigration.')
        # initialize process
        self.adw.Start_Process(SWEEP_PROCESS_NO)
        # start process after small delay to wait for init to finish
        sleep(delay)
        self.adw.Start_Process(READOUT_PROCESS_NO)
        self.adw.Set_Par(SWEEP_ACTIVE, 1)

    def _check_measurement_active(self):
        # just check the state of the adwin driver.
        if self.adw.Get_Par(SWEEP_ACTIVE) not in [0,1]:
            log.critical('ADwin: electromigration not initialized. Abort! '
                         + 'Run init_electromigration() first.')
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

    def _bootload(self, processor):
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
            output_buffer = read_nanoqt_outputs(self.adw)
            msg = (f'Adwin: Current firmware: NanoQt: {version}. The '
                    + 'current outputs have been recovered to ensure a '
                    + 'nice ride with Electromigration firmware.')
            log.warning(msg)
        elif firmware is None or firmware == 'unknown':
            msg = ('Adwin: Current firmware: unknown. Setting output '
                + 'buffer to zero! If outputs are not zero, you should '
                + 'not boot initialize this driver. It is not able to '
                + 'sweep outputs secure to zero! ')
            log.critical(msg)
        else:
            log.critical('ADwin: YOU SHOULD NOT SEE THIS MEASSAGE!')

        if any(val != 0 for val in output_values.values()):
            msg = ('Adwin: Not all outputs are zero. Outputs need to be '
                    + 'zero, because this driver is not able to sweep '
                    + 'all outputs. Aborted initializing Electromigration! ')
            log.critical(msg)
        else:
            #boot adwin
            btl_name = f"ADwin{processor.replace('T', '')}.btl"
            btl_path = Path(self.adw.ADwindir) / btl_name
            self.adw.Boot(str(btl_path))

            self._state = 'booted'

            # load processes
            adbasic_dir = Path(__file__).parent / 'adwinlib' / 'electromigration'
            em_readout_fname = f'Pro2_{processor}_em_readout.TB1'

        ##############################################################################
            # DEBUG OVERWRITE
            em_readout_fname = 'Pro2_T11T12_em_readout.TB1'
            em_sweep_fname = 'Pro2_T11T12_em_sweep.TB2'

            em_readout_process = adbasic_dir / em_readout_fname
            log.info('Adwin loading: %s', em_readout_process.name)
            self.adw.Load_Process(str(em_readout_process))
            em_sweep_process = adbasic_dir / em_sweep_fname
            log.info('Adwin loading: %s', em_sweep_process.name)
            self.adw.Load_Process(str(em_sweep_process))

            self._state = 'processes_loaded'

            self.adw.Set_Par(1, 0x01000000)



if __name__ == '__main__':
    pass
