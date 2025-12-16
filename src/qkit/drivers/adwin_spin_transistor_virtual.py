''' Virtual ADwin driver for the Spin-Transistor measurement.
    This driver simulates an ADwin environment for testing measurement scripts
    without the need of a physical ADwin device.
    Based on adwin_spin_transistor driver.
    Just basic functionality to test measurement scripts is implemented so far.
    '''

__all__ = ['adwin_spin_transistor_virtual']
__version__ = '0.1_20251103'
__author__ = 'Joshua Gabriel'

import logging as log
import numpy as np
from qkit.drivers.adwinlib.io_handler import AdwinIO, AdwinModeError
from qkit.core.instrument_base import Instrument


# FIFO input channels
INS = { 'inph': 1,     # Data_1: (float) Inphase data FIFO
        'quad': 2,     # Data_2: (float) Quadrature data FIFO
        'raw': 3}      # Data_3: (float) Raw input signal data FIFO


class adwin_spin_transistor_virtual(Instrument):
    ''' ADwin driver to handle kHz lockin + readout while performing
        sweeps on the output. So far the T11 processor, 16-bit output
        card and 18-bit input card are supported. '''
    def __init__(self,
        name='my_instrument',
        processor='virtual',
        hard_config=None,
        soft_config=None):

        # create AdwinIO Instance
        self.aio = AdwinIO(hard_config, soft_config)

        # list of parameters, that needs to be set for lockin
        self._lockin_param_list = ['frequency', 'amplitude', 'tao',
                                   'phase', 'maf']

        log.info('Initializing adwin_spin_transistor_virtual instrument')
        Instrument.__init__(self, name, tags=['virtual','ADwinVirtual'])

        self._state = 'init'
        self._sample_rate = None
        self._lockin_amp = None
        self._inputs = []
        self._outs = {}

        # implement general functions
        self.add_function("sweep")
        self.add_function("sweep_measure")
        self.add_function("init_measurement")
        self.add_function("stop_measurement")
        self.add_function("read_outputs")
        self.add_function("stop_sweep")
        self.add_function("set_output_buffer")
        self.add_function("list_connected_outputs")

########################################################################
####################### MEASUREMENT ROUTINES ###########################
########################################################################

    def sweep(self, target, duration, wait=False, clearFIFO=True):
        """ Ramp the outputs of the ADwin wihtout measurement.
            If wait==True it waits for the sweep to be finished. """
        self.data = {key: np.array([]) for key in INS}
        self.samples = int(duration * self._sample_rate)
        # sanity checks
        self._check_measurement_active()
        if clearFIFO:
            for i in INS:
                self.data[i] = np.array([])
        for i in INS:
            self.data[i] = np.arange(1,int(duration * self._sample_rate)+2)
        

    def sweep_measure(self, target, duration):
        ''' Start a sweep while measuring with lockin with minimal 
            communication between adwin-PC (buffering the measurement
            in fifo). The sample rate is determined by the lockin
            process which needs to be already running. '''
        # sanity checks
        self._check_measurement_active()
        self.data = {}
        for i in INS:
            self.data[i] = np.arange(1,int(duration * self._sample_rate)+2)
        # fetch measurement data from adwin and return
        return self.data

    def _fetch_data_from_fifos(self):
        ''' Fetch all data from the fifos which has been set as inputs
            during init_measurement() and clear all other fifos '''
        res = {'inph': None, 'quad': None, 'raw': None}
        # with self._lock:
        samplerate = self._sample_rate  # fetch only one second of data
        for key in res:
            if key in self._inputs:
                # Get input in bit values
                if samplerate:
                    res[key] = self.data[key][:samplerate]
                    self.data[key] = self.data[key][samplerate:]
                else:
                    res[key] = np.array([])
            else:
                self.data[key] = np.array([])
        return res

########################################################################
########################## PREPARE MEASUREMENT #########################
########################################################################

    def init_measurement(self, sample_rate, bias, inputs,
                         **lockin_params):
        ''' Initialize a lockin/dc measurement. For simplicity of the
            ADbasic driver, the lockin is always applied, but with
            amplitude 0 effectively there is no lockin signal. '''
        log.info('Adwin initializing measurement.')
        self._sample_rate = sample_rate
        self._lockin_frequency = lockin_params.get('frequency', 1000)
        for inp in inputs:
            if inp not in INS:
                raise KeyError
        self._inputs = inputs
        self._state = 'measurement_ready'

    def stop_measurement(self):
        """ Stops the lockin process. No lockin signal is applied and no
            readout is triggered by a sweep anymore. """
        self._check_measurement_active()
        self._state = 'processes_loaded'

########################################################################
########################## OTHER FUNCTIONS #############################
########################################################################


    def get_sample_rate(self):
        ''' Return sample rate '''
        return self._sample_rate
    
    def get_lockin_frequency(self):
        ''' Return lockin frequency '''
        return self._lockin_frequency

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
        for name in outs_list:
            card, channel = self.aio.get_card_channel(name)
            par_no = self._get_output_par(card, channel)
            par_val = self._outs.get(par_no, 0)
            outs[name] = par_val
        return outs

    def stop_sweep(self):
        """ Stopping sweep process immediately """
        log.info('Adwin stopping sweep.')

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
            self._outs[par_no] = val

    def _start_sweep(self, target, duration, delay=0.05):
       pass

    def _check_measurement_active(self):
        # just check the state of the adwin driver. It could be done by
        # reading the adwin's lockin_active par, but I want to limit
        # communication
        if self._state != 'measurement_ready':
            log.critical('ADwin: measurement not initialized. Abort! '
                         + 'Run init_measurement() first.')

    def _bootload(self, processor, lockin_filter):
        # before boot try to read the current outputs, which can
        # fail if the adwin was power cycled and never booted since
        self._state = 'processes_loaded'



if __name__ == '__main__':
    pass
