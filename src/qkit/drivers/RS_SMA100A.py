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
#import types
import logging

class RS_SMA100A(Instrument):
    '''
    This is the driver for the Keysight N5173B Signal Genarator

    Usage:
    Initialize with
    <name> = instruments.create('<name>', 'Keysight_N5173B', address='<GBIP address>, reset=<bool>')
    '''

    def __init__(self, name, address, reset=False):
        '''
        Initializes the Keysight_N5173B, and communicates with the wrapper.

        Input:
          name (string)    : name of the instrument
          address (string) : GPIB address
          reset (bool)     : resets to default values, default=False
        '''
        logging.info(__name__ + ' : Initializing instrument Keysight_N5183B_WIP')
        Instrument.__init__(self, name, tags=['physical'])

        self._address = address
        self._visainstrument = visa.instrument(self._address)

        # Implement parameters
        self.add_parameter('power',
            flags=Instrument.FLAG_GETSET, units='dBm', minval=-30, maxval=30, type=float)
        #self.add_parameter('phase',
        #    flags=Instrument.FLAG_GETSET, units='rad', minval=-numpy.pi, maxval=numpy.pi, type=types.FloatType)
        self.add_parameter('frequency',
            flags=Instrument.FLAG_GETSET, units='Hz', minval=9e3, maxval=20e9, type=float)
        self.add_parameter('status',
            flags=Instrument.FLAG_GETSET, type=bool)
        self.add_parameter('PULSEsource',
            flags=Instrument.FLAG_GETSET, type=str)
        self.add_parameter('PULSEmodulation',
            flags=Instrument.FLAG_GETSET, type=str)
        self.add_parameter('FM',
            flags=Instrument.FLAG_GETSET,type=bool)
        self.add_parameter('FM_FreqDev',
            flags=Instrument.FLAG_GETSET, units='Hz', minval=5e-1 , maxval=1e6, type=float)
        self.add_parameter('FM_ModulationFreq',
            flags=Instrument.FLAG_GETSET, units='Hz', minval= 1e-1, maxval=625e4, type=float)
        self.add_parameter('FM_source',
            flags=Instrument.FLAG_GETSET, type=bool)

        self.add_function('reset')
        self.add_function ('get_all')


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
        #self.get_phase()
        self.get_frequency()
        self.get_status()

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

    #def do_get_phase(self):
    #    '''
    #    Reads the phase of the signal from the instrument
    #
    #    Input:
    #        None
    #
    #    Output:
    #        phase (float) : Phase in radians
    #    '''
    #    logging.debug(__name__ + ' : get phase')
    #    return float(self._visainstrument.query('PHASE?'))

    #def do_set_phase(self, phase):
    #    '''
    #    Set the phase of the signal
    #
    #    Input:
    #        phase (float) : Phase in radians
    #
    #    Output:
    #        None
    #    '''
    #    logging.debug(__name__ + ' : set phase to %f' % phase)
    #    self._visainstrument.write('PHASE %s' % phase)

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

    def do_get_status(self):
        '''
        Reads the output status from the instrument

        Input:
            None

        Output:
            status (string) : 'On' or 'Off'
        '''
        logging.debug(__name__ + ' : get status')
        return bool(int(self._visainstrument.query('OUTP?')))


    def do_set_status(self, status):
        '''
        Set the output status of the instrument

        Input:
            status (string) : 'On' or 'Off'

        Output:
            None
        '''
        logging.debug(__name__ + ' : set status to %s' % status)
        
        if status == True:
            self._visainstrument.write('OUTP ON')
        elif status == False:
            self._visainstrument.write('OUTP OFF')
        else:
            raise ValueError('set_status(): can only set True or False')
            
    def do_set_PULSEsource(self, PULSEsource):
        '''
        Defining the source of the pulse modulation on PULSE port
        
        Input:
            source (string) : 
            EXTernal        or 
            INTernal SQUare|FRUN|TRIGgered|ADOublet|DOUBlet|GATEd|PTRain
        
        Output: 
            None
        '''
        logging.debug(__name__ + ' : set pulse source to %s' % PULSEsource)
        self._visainstrument.write('PULM:SOURce %s' %PULSEsource)     #not working because reasons
        #if PULSEsource=="EXTernal" or PULSEsource=="EXT" or PULSEsource=="EXTERNAL":
        #    self._visainstrument.write('PULM:SOURce EXT')
        #elif PULSEsource=="INTernal" or PULSEsource=="INT" or PULSEsource=="INTERNAL":
         #   self._visainstrument.write('PULM:SOURce INT')
        #else:
        #   return(0)

    def do_get_PULSEsource(self):
        '''
        Reads the PULSE source
        Input:
            None
        Output:
            pulse source(string): EXTernal or specified INTernal
        '''
        #a="EXT"
        logging.debug(__name__ + ' : get PM source')
        #if (self._visainstrument.query('PULM:SOURce?'))==a:
            #return (self._visainstrument.query('PULM:SOURce?'))
        #else:
            #return (self._visainstrument.query('PULM:SOURce?'),self._visainstrument.query('PULM:SOURce:INTernal?'))   
        return str(self._visainstrument.query(':PULM:SOURce?'))
            
            
    def do_set_PULSEmodulation(self, PULSEmodulation):
        '''
        Starting/stopping pulse modulation using PULSE port
        
        Input:
            ON|OFF|1|0 
        Output:
            None
        '''
        
        logging.debug(__name__ + ' : set pulse modulation to %s' % PULSEmodulation)
        self._visainstrument.write('PULM:STATe %s' % PULSEmodulation)
        
    def do_get_PULSEmodulation(self):
        '''
        Reads the pulsemodulation status from the instrument
        
        Input:
            None
            
        Output:
            pulsemodulation (bool) : 'On' (1) or 'Off' (0)
        '''
        logging.debug(__name__ + ' : get PM status')
        return bool(self._visainstrument.query('PULM:STATe?'))

    # shortcuts
    def off(self):
        '''
        Set status to 'off'

        Input:
            None

        Output:
            None
        '''
        self.set_status(False)

    def on(self):
        '''
        Set status to 'on'

        Input:
            None

        Output:
            None
        '''
        self.set_status(True)

    def do_set_FM(self, FM):
        '''
        Set the status of the frequency modulation (UNT option)
        
        Input: 
            FM (Bool) : 1 for 'ON', 0 for 'OFF'
        
        Output: 
            None
        '''
        logging.debug(__name__ + ' : set FM to %s' % FM)
        
        if FM == True:
            self._visainstrument.write(':FM:STAT ON')
        elif FM==False:
            self._visainstrument.write('FM:STAT OFF')
        else:
            raise ValueError('set_FM(): can only set True or False')
    
    
    def do_get_FM(self):
        '''
        Get the status of the frequency modulation (UNT option)
        
        Input:
            None
        
        Output:
            status (Bool) of the FM
        '''
        logging.debug(__name__ + ' : get FM status')
        #return bool(int(self._visainstrument.query(':FM:STAT?')))
        
    def do_set_FM_FreqDev(self,FreqDev):
        '''
        ----Valid only for Low frequency output----
        Sets the Frequency deviation for the frequency modulation
        i.e. by how much the frequency is modulated
        
        Input:
            FreqDev (INT): 
            
        Output:
            None
        '''
        
        logging.debug(__name__ + ' : set FM Frequency Deviation to %s' % FreqDev)
        self._visainstrument.write(' FM:DEViation %s ' % FreqDev)
    
    def do_get_FM_FreqDev(self):
        '''
        Get the currently set FM Frequency Deviation
        
        Input:
            None
        
        Output:
            FreqDev(INT)
        '''
        
        logging.debug(__name__ + ' : get FM Frequency Deviation')
        #return(self._visainstrument.query('FM:DEViation?'))
    """  
    def do_set_FM_ModulationFreq(self,ModFreq):
        '''
        ---- Valid only for Low Frequency Output ----
        Sets the modulation frequency for the frequency modulation
        i.e. how often the frequency range is covered
        
        Input:
            ModFreq(INT)
        
        Output:
            None
        '''
        
        logging.debug(__name__ + ' : set FM Modulation Frequency to %s' % ModFreq)
        self._visainstrument.write('FM1:INTernal:FUNCtion1:FREQuency %s' % ModFreq)
     
    def do_get_FM_ModulationFreq(self):
        '''
        Get the currently set FM Modulation frequency
        
        Input:
            None
        
        Output:
            ModFreq(INT)
        ''' 
        
        logging.debug(__name__ + ' : get FM Modulation frequency')
        return(self._visainstrument.query('FM1:INTernal:FUNCtion1:FREQuency?'))
        
    def do_set_FM_source(self,FM_source):
        '''
        Sets the source that creates the analogue frequency modulation
        
        Input:
            FM_source (string)
            
        Output:
            None
        '''
        available_modes=("FUNC[1]", "FUNC[2]", "SWE", "DUAL", "NOIS[1]", "NOIS[2]", "EXT[1]", "EXT[2]")
        logging.debug(__name__ + ' : set FM source to %s' % FM_source)
        if FM_source in available_modes:
            self._visainstrument.write('FM[1]:SOURce %s' % FM_source)
        else:
            raise ValueError('set_FM_source(): can only set FUNC[1], FUNC[2], SWE, DUAL, NOIS[1], NOIS[2], EXT[1] and EXT[2]')

    def do_get_FM_source(self):
        '''
        Get the currently used source for frequency modulation
        
        Input:
            None
        
        Output:
            FM_source (string)
        '''
        
        logging.debug(__name__ + ':get FM_source')
        return(self._visainstrument.query( 'FM1:SOURce?'))
	"""

    def activate_PC_Mode(self,State=False):
        '''
        (de)activates the phase-continuous mode
        
        Input:
            State   :   bool
        
        Output:
            None
        '''
        
        logging.debug(__name__ + f' : activating phase continuous mode {State}')
        return(self._visainstrument.write(f'FREQ:PHAS:CONT:STAT {State}'))

    def set_PC_Mode(self,mode):
        '''
        setting the type of the phase-continuous mode
        
        Input:
            mode   :   string
        
        Output:
            None
        '''
        
        logging.debug(__name__ + f' : setting phase continuous mode {mode}')
        if mode=="narrow":
            return(self._visainstrument.write(f'FREQ:PHAS:CONT:MODE NARR'), "setting mode to narrow")
        else:
            return(self._visainstrument.write(f'FREQ:PHAS:CONT:MODE WIDE'), "setting mode to default(wide)")
