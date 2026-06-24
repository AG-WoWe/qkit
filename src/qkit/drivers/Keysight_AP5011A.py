# Agilent_E8257D.py class, to perform the communication between the Wrapper and the device
# Pieter de Groot <pieterdegroot@gmail.com>, 2008
# Martijn Schaafsma <qtlab@mcschaafsma.nl>, 2008
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

from qkit.core.instrument_base import Instrument
from qkit import visa

import logging
import numpy

class Keysight_AP5011A(Instrument):
    '''
    This is the driver for the Keysight AP5011A Signal Genarator

    Usage:
    Initialize with
    <name> = instruments.create('<name>', 'Keysight_AP5011A', address='<GBIP address>, reset=<bool>')
    '''

    def __init__(self, name, address, timeout=5000, reset=False):
        '''
        Initializes the Keysight_AP5011A, and communicates with the wrapper.

        Input:
          name (string)    : name of the instrument
          address (string) : GPIB address
          reset (bool)     : resets to default values, default=False
        '''
        logging.info(__name__ + ' : Initializing instrument Keysight_AP5011A')
        Instrument.__init__(self, name, tags=['physical'])

        # Add some global constants
        self._address = address
        self._visainstrument = visa.instrument(self._address)
        self._visainstrument.timeout = timeout

        self.add_parameter('power',
            flags=Instrument.FLAG_GETSET, units='dBm', minval=-30, maxval=25, type=float)
        self.add_parameter('phase',
            flags=Instrument.FLAG_GETSET, units='rad', minval=-numpy.pi, maxval=numpy.pi, type=float)
        self.add_parameter('frequency',
            flags=Instrument.FLAG_GETSET, units='Hz', minval=9e3, maxval=40e9, type=float)
        self.add_parameter('pulse_width',
            flags=Instrument.FLAG_GETSET, units='s', minval=5e-9, maxval=21, type=float)
        self.add_parameter('RF',
            flags=Instrument.FLAG_GETSET, type=bool)
        self.add_parameter('PULM',
            flags=Instrument.FLAG_GETSET, type=bool)

        self.add_function('reset')
        self.add_function('get_all')
        #self.add_function('enable_pulse_modulation')
        #self.add_function('disable_pulse_modulation')
        #self.add_function('enable_output')
        #self.add_function('disable_output')
        self.add_function('get_status')
        self.add_function('enable_external_trigger')


        if (reset):
            self.reset()
        else:
            self.get_all()
        

    def reset(self):
        '''
        Resets the instrument to default values

        Input:
            None

        Output:
            None
        '''
        logging.info(__name__ + ' : resetting instrument')
        self._visainstrument.write('*RST')
        self.get_all()

    def get_all(self):
        '''
        Reads all implemented parameters from the instrument,
        and updates the wrapper.

        Input:
            None

        Output:
            None
        '''
        logging.info(__name__ + ' : get all')
        self.get_power()
        self.get_phase()
        self.get_frequency()
        self.get_status('output')
        self.get_status('pulse_modulation')

    def do_get_power(self):
        '''
        Reads the power of the signal from the instrument

        Input:
            None

        Output:
            ampl (?) : power in ?
        '''
        logging.debug(__name__ + ' : get power')
        return float(self._visainstrument.query('POW:AMPL?'))

    def do_set_power(self, amp):
        '''
        Set the power of the signal

        Input:
            amp (float) : power in ??

        Output:
            None
        '''
        logging.debug(__name__ + ' : set power to %f' % amp)
        self._visainstrument.write('POW:AMPL %s' % amp)

    def do_get_phase(self):
        '''
        Reads the phase of the signal from the instrument

        Input:
            None

        Output:
            phase (float) : Phase in radians
        '''
        logging.debug(__name__ + ' : get phase')
        return float(self._visainstrument.query('PHASE?'))

    def do_set_phase(self, phase):
        '''
        Set the phase of the signal

        Input:
            phase (float) : Phase in radians

        Output:
            None
        '''
        logging.debug(__name__ + ' : set phase to %f' % phase)
        self._visainstrument.write('PHASE %s' % phase)

    def do_get_frequency(self):
        '''
        Reads the frequency of the signal from the instrument

        Input:
            None

        Output:
            freq (float) : Frequency in Hz
        '''
        logging.debug(__name__ + ' : get frequency')
        return float(self._visainstrument.query('FREQ:CW?'))

    def do_set_frequency(self, freq):
        '''
        Set the frequency of the instrument

        Input:
            freq (float) : Frequency in Hz

        Output:
            None
        '''
        logging.debug(__name__ + ' : set frequency to %f' % freq)
        self._visainstrument.write('FREQ:CW %s' % freq)

    def get_status(self, module):
        '''
        Reads the output status from the instrument

        Input:
            None

        Output:
            status (string) : 'On' or 'Off'
        '''
        logging.debug(__name__ + f' : get status of {module}')
        if module == 'output':
            return bool(int(self._visainstrument.query('OUTP?')))
        elif module == 'pulse_modulation':
            return bool(int(self._visainstrument.query('PULM:STAT?')))
    
    def do_set_RF(self, active:bool):
        '''
        Enable rf output
        '''
        if active:
            logging.debug(__name__ + ' : enable RF output')
            self._visainstrument.write('OUTP ON')
        else:
            logging.debug(__name__ + ' : disable RF output')
            self._visainstrument.write('OUTP OFF')
        
    # def do_disable_output(self):
    #     '''
    #     Disable pulse modulation
    #     '''
    #     logging.debug(__name__ + ' : disable RF output')
    #     self._visainstrument.write('OUTP OFF')

    def enable_external_trigger(self):
        '''
        Set the trigger to single external input on the rising edge
        '''
        logging.debug(__name__ + ' : set trigger to external')
        # Set Trigger Mode to "Single"
        self._visainstrument.write('INIT:CONT ON')
        # Set Trigger Output to "Normal"
        self._visainstrument.write('TRIG:OUTP_MODE NORM')
        # Set Trigger Edge to "Rising"
        self._visainstrument.write('TRIG:SLOP POS')
        # Set Trigger Source to "External Trigger"
        self._visainstrument.write('TRIG:SOUR EXT')

    def do_set_pulse_width(self, pulse_width):
        '''
        Set pulse modulation pulse_width

        INPUT: pulse_width in s
        '''
        self._visainstrument.write('PULM:INT:PWID %f' % pulse_width)

    def do_get_pulse_width(self):
        '''
        Get pulse modulation pulse_width
        '''
        return float(self._visainstrument.query('PULM:INT:PWID?'))

    def do_set_PULM(self, active):
        '''
        Enable pulse modulation
        '''
        if active:
            logging.debug(__name__ + ' : enable pulse modulation')
            self._visainstrument.write('PULM:STAT ON')
        else:
            logging.debug(__name__ + ' : enable pulse modulation')
            self._visainstrument.write('PULM:STAT OFF')
        
    # def do_disable_pulse_modulation(self):
    #     '''
    #     Disable pulse modulation
    #     '''
    #     logging.debug(__name__ + ' : enable pulse modulation')
    #     self._visainstrument.write('PULM:STAT OFF')


    # # shortcuts
    # def off(self):
    #     '''
    #     Set status to 'off'

    #     Input:
    #         None

    #     Output:
    #         None
    #     '''
    #     self.set_status(False)

    # def on(self):
    #     '''
    #     Set status to 'on'

    #     Input:
    #         None

    #     Output:
    #         None
    #     '''
    #     self.set_status(True)
