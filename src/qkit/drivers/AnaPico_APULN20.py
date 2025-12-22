# AnaPico_APULN20.py
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
import sys
from qkit import visa

import logging
import numpy

class AnaPico_APULN20(Instrument):
    '''
    This is the driver for the Ana Pico APULN20 Signal Generator based on the driver of the AnaPico_APUASYN20.py by Nicolas Gosling <Nicolas.Gosling@partner.kit.edu> 04/21

    Usage:
    Initialize with
    <name> = instruments.create('<name>', 'AnaPico_APULN20', address='<GBIP address>, reset=<bool>')
    '''

    def __init__(self, name, address, reset=False):
        '''
        Initializes the Ana Pico APULN20, and communicates with the wrapper.

        Input:
          name (string)    : name of the instrument
          address (string) : GPIB address
          reset (bool)     : resets to default values, default=False
        '''
        logging.info(__name__ + ' : Initializing instrument Ana Pico APULN20')
        Instrument.__init__(self, name, tags=['physical'])


        
        self._address = address
        self._visainstrument = visa.instrument(self._address)

#Implement parameters


        self.add_parameter('output',
            flags=Instrument.FLAG_GETSET, type=str)
				  


        self.add_parameter('power',
            flags=Instrument.FLAG_GETSET, units='dBm', minval=-25, maxval=13, type=float) #Maximum value chosen for frequencies below GHz



        self.add_parameter('frequency',
            flags=Instrument.FLAG_GETSET, units='Hz', minval=1e5, maxval=20e9, type=float)


        self.add_parameter('FMState',
            flags=Instrument.FLAG_GETSET, type=str)


        self.add_parameter('FMSource',
            flags=Instrument.FLAG_GETSET, type=str)


        self.add_parameter('FMCoupling',
            flags=Instrument.FLAG_GETSET, type=str)


        self.add_parameter('FMSensitivity',
            flags=Instrument.FLAG_GETSET, units='Hz/V', minval=0, maxval=200e6, type=float) ##Maximum value chosen for frequencies below GHz
        
        
        self.add_parameter('FMDeviation',
            flags=Instrument.FLAG_GETSET, units='Hz', minval=0, maxval=200e6, type=float) ##Maximum value chosen for frequencies below GHz
        
        
        self.add_parameter('FMInternalfrequency',
            flags=Instrument.FLAG_GETSET, units='Hz', minval=0.1, maxval=80e3, type=float)
        
        
        self.add_parameter('FMShape',
            flags=Instrument.FLAG_GETSET, type=str)





#Define functions


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
        self.get_output()
        self.get_frequency()
        self.get_power()
        


    def do_get_output(self):
        '''
        Get the status of the RF ouput
        Input:
            None

        Output:
            Power on: ON|1
            Power off: OFF|0
        '''
        logging.debug(__name__ + ' : get output status')
        return self._visainstrument.query(':OUTPut?')

    def do_set_output(self, out):
        '''
        Turns RF output power on/off.

        Input:
            Power on: ON|1
            Power off: OFF|0

        Output:
            None
        '''
        logging.debug(__name__ + ' : set output to %s' %out)
        self._visainstrument.write(':OUTPut %s' %out)



    def do_get_frequency(self):
        '''
        Reads the frequency of the signal from the instrument

        Input:
            None

        Output:
            freq (float) : Frequency in Hz
        '''
        logging.debug(__name__ + ' : get frequency')
        return self._visainstrument.query(':FREQuency?')

    def do_set_frequency(self, freq):
        '''
        Set the frequency of the instrument

        Input:
            freq (float) : Frequency in Hz

        Output:
            None
        '''
        logging.debug(__name__ + f' : set frequency to {freq}')
        self._visainstrument.write(f':FREQuency {freq}')



    def do_get_power(self):
        '''
        Reads the power of the signal from the instrument

        Input:
            None

        Output:
            ampl (?) : power in ?
        '''
        logging.debug(__name__ + ' : get power')
        return float(self._visainstrument.query(':POWer?'))

    def do_set_power(self, amp):
        '''
        Set the power of the signal

        Input:
            amp (float) : power in ??

        Output:
            None
        '''
        logging.debug(__name__ + f' : set power to {amp}')
        self._visainstrument.write(f':POWer {amp}')



    def do_get_FMState(self):
        '''
       Get the status of the frequency modulation: ON or OFF. The reset value is OFF.

        Input:
            None

        Output:
            'ON'|1 for FM on
            'OFF'|0 for FM off
        '''
        logging.debug(__name__ + ' : get FM state')
        return self._visainstrument.query(':FM:STATe?')

    def do_set_FMState(self, FMstat):
        '''
      Set the status of the frequency modulation on ON or OFF

        Input: 
            FMstat (str) : 'ON' or 1 for ON, 'OFF' or 0 for OFF
        
        Output: 
            None
        '''
        logging.debug(__name__ + ' :set FM state to %s' %FMstat)

        self._visainstrument.write(':FM:STATe %s' %FMstat)


    
    def do_get_FMSource(self):
        '''
       Get the currently used source for frequency modulation: internal or external. The reset value is EXTernal.

        Input:
            None

        Output:
            INT
            EXT 
        '''
        logging.debug(__name__ + ' :get FM source')
        return self._visainstrument.query(':FM:SOURce?')

    def do_set_FMSource(self, FMsour):
        '''
      Set the source for frequency modulation: internal or external

        Input: 
            FMsour (str) : INT or INTernal
                           EXT or EXTernal
        
        Output: 
            None
        '''
        logging.debug(__name__ + ' :set FM source to %s' %FMsour)

        self._visainstrument.write(':FM:SOURce %s' %FMsour)



    def do_get_FMCoupling(self):
        '''
       Get the currently used signal coupling for the external FM modulation, AC or DC. The reset value is AC.

        Input:
            None

        Output:
            AC
            DC
        '''
        logging.debug(__name__ + ' :get FM coupling')
        return self._visainstrument.query(':FM:COUPling?')

    def do_set_FMCoupling(self, FMcoup):
        '''
      This command selects AC or DC signal coupling for the external FM modulation.

        Input: 
            FMcoup (str) : AC
                               DC
        
        Output: 
            None
        '''
        logging.debug(__name__ + ' :set FM coupling to %s' %FMcoup)

        self._visainstrument.write(':FM:COUPling %s' %FMcoup)



    def do_get_FMSensitivity(self):
        '''
       Get the external frequency modulation deviation per one volt peak amplitude signal input. The reset RST value is 1000 Hz/V.

        Input:
            None

        Output:
            float in Hz/V
        '''
        logging.debug(__name__ + ' :get FM sensitivity')
        return float(self._visainstrument.query(':FM:SENSitivity?'))

    def do_set_FMSensitivity(self, FMsens):
        '''
      This command sets the frequency modulation deviation per one volt peak amplitude signal input. This setting will be used if :FM:SOURce is set to EXTernal. The reset RST value is 1000 Hz/V.

        Input: 
            FMsens (float) : in Hz/V
        
        Output: 
            None
        '''
        logging.debug(__name__ + f' :set FM sensitivity to {FMsens}')

        self._visainstrument.write(f':FM:SENSitivity {FMsens}')



    def do_get_FMDeviation(self):
        '''
       Get the internal frequency modulation deviation. The reset RST value is 1000 Hz.
    
        Input:
            None
    
        Output:
            float in Hz
        '''
        logging.debug(__name__ + ' :get FM deviation')
        return float(self._visainstrument.query(':FM:DEViation?'))
    
    def do_set_FMDeviation(self, FMdev):
        '''
      This command sets the frequency modulation deviation. This setting will be used if [:SOURce<ch>]:FM:SOURce is set to INTernal. The reset RST value is 1000 Hz.
    
        Input: 
            FMdev (float) : in Hz
        
        Output: 
            None
        '''
        logging.debug(__name__ + f' :set FM deviation to {FMdev}')
    
        self._visainstrument.write(f':FM:DEViation {FMdev}')
    
    
    
    def do_get_FMInternalfrequency(self):
        '''
       Get the internal frequency modulation rate in Hz. The reset RST value is 400 Hz.
    
        Input:
            None
    
        Output:
            float in Hz
        '''
        logging.debug(__name__ + ' :get FM rate')
        return float(self._visainstrument.query(':FM:INT:FREQuency?'))
    
    def do_set_FMInternalfrequency(self, FMintfreq):
        '''
      This command sets the frequency modulation rate in Hz. This setting will be used if [:SOURce<ch>]:FM:SOURce is set to INTernal. The reset RST value is 400 Hz.
    
        Input: 
            FMintfreq (float) : in Hz
        
        Output: 
            None
        '''
        logging.debug(__name__ + f' :set FM rate to {FMintfreq}')
    
        self._visainstrument.write(f':FM:INT:FREQuency {FMintfreq}')
    
    
    
#    def do_get_FMShape(self):
#        '''
#       Get the internal frequency modulation shape as a str. The reset RST value is SINE.
#   
#        Input:
 #           None
 #   
 #       Output:
 #           str: RD Selects ramp down.
 #                RU Selects ramp up.
 #                SINE Selects sine wave.
 #                SQUare Selects square wave.
 #                TRIangle Selects triangle wave.
 #       '''
 #       logging.debug(__name__ + ' :get FM shape')
 #       return str(self._visainstrument.query(':FM:INT:SHAPe?'))
 #   
 #   def do_set_FMShape(self, FMintshape):
 #       '''
 #     This command specifies the FM modulation shape for internal modulation. The reset RST value is SINE.
 #   
 #       Input: 
 #           FMintshape (str) : RD Selects ramp down.
 #                              RU Selects ramp up.
 #                              SINE Selects sine wave.
 #                              SQUare Selects square wave.
 #                              TRIangle Selects triangle wave.
 #       
 #       Output: 
 #           None
 #       '''
 #       logging.debug(__name__ + f' :set FM shape to {FMintshape}')
 #   
#        self._visainstrument.write(f'FM:INT:SHAPe {FMintshape}')
        