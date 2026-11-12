# ZI_HDAWG4 driver
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
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

import json
import logging
import os
import shutil
import time
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import qkit
from qkit.core.instrument_base import Instrument
import zhinst
import zhinst.utils
from zhinst.toolkit import Session, Waveforms


class ZI_HDAWG4_v2(Instrument):

    #input to initialize instrument: name(string) - name of the instrument, device_id - serial numer of instrument
    def __init__(self, name, device_id, disable_everything = False, **kwargs):
        """
        DOCUMENTATION

        __init__: ZI_HDAWG4 (parent class: Instrument)

            initialization parameters:

            name (STRING):
                name of the device
            device_id (string):
                number of the device

            work parameters (see methods descriptions for further information):

            marker_output (INT)
            output_range (FLOAT)
            voltage_offset (FLOAT)
            sampling_clock (FLOAT)
            sampling_prescaler (INT)
            sampling_rate (FLOAT)
            channel_grouping (INT)
            user_regs (INT)
            direct (INT)
            delay (FLOAT)
            channel_output (INT)
            amplitude (FLOAT)
            modulation_mode (INT)
            voltage_limit (FLOAT)
            console_output (BOOL)
            auto_range (BOOL)
            max_samples (INT)

        The channel numbering (1-4) of amplitude and modulation_mode assumes the
        2x2 channel grouping (two cores with two outputs each).
        """
        logging.info(__name__ + ' : Initializing instrument')
        Instrument.__init__(self, name, tags = ['physical','ZI_HDAWG4'])

        self._device_id = device_id

        #auxiliary variables
        #array to translate channel number into (core, output on that core)
        self._binary = np.array([[0,0],[0,1],[1,0],[1,1]])
        #maximum length of waveform (in samples, in order to set trigger)
        self._waveform_max_length = 0

        #arrays containing information about which channel of the device are switched on
        #and which marker outputs are used
        #all of them are off per default
        self._marker_outputs = np.array([0,0,0,0])
        self._channel_outputs = np.array([0,0,0,0])

        #Sample clock prescaler values:
        self._prescaler = np.array([2**i for i in range(14)])

        #Possible voltage ranges for outputs
        self._Vrange_array = np.array([0.2, 0.4, 0.6, 0.8, 1., 2., 3., 4., 5.])

        #Limiter for output range
        self._max_Vrange = 5 # in V

        #Turn text output of waveform upload on and off
        self._console_output = True

        #True: sequencer waits for digital trigger 1 before each playback; False: free-running loop
        self._use_trigger = True

        #Marker arrays count as HIGH above this value (they arrive as sampled floats 0 / 1)
        self._marker_threshold = 0.5

        #True: upload_waveform chooses the output range; False: the range set by the user is kept
        self._auto_range = True

        #largest waveform (samples per channel) that upload_waveform accepts, protects the RAM of the PC
        self._max_samples = 128_000_000

        #warn if the mean of a wave exceeds this fraction of its peak (DC load on the bias tee); None = off
        self._dc_warning = 0.01

        #sequencer program of the old csv upload path
        self.awg_program = ""

        #set apilevel to highest supported by device to unlock most of the functionalities
        #create apisession to communicate with device (ziDataServer needed)
        self._apilevel = 6
        self._bad_device_message = "No ZI_HDAWG4 device found."
        (self.daq, self.device, _) = zhinst.utils.create_api_session(self._device_id, self._apilevel)
        zhinst.utils.api_server_version_check(self.daq)

        ### connect to data server
        session = Session('localhost')
        ### connect to device
        self.device_new = session.connect_device(self._device_id)

        #create instance of awgModule
        self.awgModule = self.daq.awgModule()
        self.awgModule.set("device", self.device)
        self.awgModule.execute()

        #path of the module folder
        self.data_dir = self.awgModule.getString("directory")
        logging.info(__name__+'Module folder set: '+self.data_dir)

        #path of the folder in which waveforms are saved (only this specific folder is possible)
        self.wave_dir = str(os.path.join(self.data_dir, "awg", "waves"))+'/'
        logging.info(__name__+'Waveform folder set: '+self.wave_dir)

        # disable all outputs etc.
        if disable_everything:
            self.disable_everything()

        #implement functions
        self.add_function("start_playback")
        self.add_function("stop_playback")
        self.add_function('refresh_folder')
        self.add_function('write')
        self.add_function('set_program_string')
        self.add_function('upload_to_device')
        self.add_function('upload_waveform')
        self.add_function('load_config_file')
        self.add_function('disable_everything')
        self.add_function('set_trigger')

        #/TRIGGERS/OUT/n/SOURCE
        self.add_parameter('marker_output', type = int,
            flags = Instrument.FLAG_GETSET,
            channels = (1,4), channel_prefix = "ch%d_",
            minval = 0, maxval = 2,
            tags = ['sweep'])

        #/SIGOUTS/n/RANGE
        self.add_parameter('output_range', type = float,
            flags = Instrument.FLAG_GETSET,
            channels = (1,4), channel_prefix = "ch%d_",
            minval = 0.2, maxval = 5,
            units = 'V', tags = ['fixed values'])

        #/SIGOUTS/n/OFFSET (amplified mode, into 50 Ohm: -1.25 V to +1.25 V)
        self.add_parameter('voltage_offset', type = float,
            flags = Instrument.FLAG_GETSET,
            channels = (1,4), channel_prefix = "ch%d_",
            minval = -1.25, maxval = 1.25,
            units = 'V', tags = ['sweep'])

        #/SYSTEM/CLOCKS/SAMPLECLOCK/FREQ
        self.add_parameter('sampling_clock', type = float,
            flags = Instrument.FLAG_GETSET,
            minval = 100e6, maxval = 2.4e9,
            tags = ['sweep'])

        #/AWGS/n/TIME
        self.add_parameter('sampling_prescaler', type = int,
            flags = Instrument.FLAG_GETSET,
            minval = 1, maxval = 8192,
            tags = ['sweep'])

        #Actual sampling rate
        self.add_parameter('sampling_rate', type = float,
            flags = Instrument.FLAG_GET)

        #/SYSTEM/AWG/CHANNELGROUPING
        self.add_parameter('channel_grouping', type = int,
            flags = Instrument.FLAG_GETSET,
            minval = 0, maxval = 1,
            tags = ['sweep'])

        #/AWGS/n/USERREGS/n
        # there are 32 user registers that the sequencer has access to
        # usage: communicate information to API program
        self.add_parameter('user_regs', type = int,
            flags = Instrument.FLAG_GETSET,
            channels = (1,32), channel_prefix = 'reg%d_',
            tags = ['sweep'])

        #/SIGOUTS/0/DIRECT
        self.add_parameter('direct', type = int,
            flags = Instrument.FLAG_GETSET,
            channels = (1,4), channel_prefix = 'ch%d_',
            minval = 0, maxval = 1,
            tags = ['sweep'])

        #/SIGOUTS/0/DELAY
        self.add_parameter('delay', type = float,
            flags = Instrument.FLAG_GETSET,
            channels = (1,4), channel_prefix = 'ch%d_',
            minval = 0,maxval = 25.83e-9,
            units = 's', tags = ['sweep'])

        #/SIGOUTS/n/ON
        self.add_parameter('channel_output', type = int,
            flags = Instrument.FLAG_GETSET,
            channels = (1,4), channel_prefix = "ch%d_",
            minval = 0, maxval = 1,
            tags = ['sweep'])

        #/AWGS/n/OUTPUTS/n/AMPLITUDE
        self.add_parameter('amplitude', type = float,
            flags = Instrument.FLAG_GETSET,
            channels = (1,4), channel_prefix = "ch%d_",
            tags = ['sweep'])

        #/AWGS/n/OUTPUTS/n/MODULATION/MODE
        self.add_parameter('modulation_mode', type = int,
            flags = Instrument.FLAG_GETSET,
            channels = (1,4), channel_prefix = 'ch%d_',
            minval = 0, maxval = 5,
            tags = ['sweep'])

        #Actual voltage limit
        self.add_parameter('voltage_limit', type = float,
            flags = Instrument.FLAG_GETSET,
            minval = 0, maxval = 5,
            tags = ['sweep'])

        # Add console_output
        self.add_parameter('console_output', type = bool,
            flags = Instrument.FLAG_GETSET,
            minval = 0, maxval = 1,
            tags = ['sweep'])

        # automatic output range in upload_waveform
        self.add_parameter('auto_range', type = bool,
            flags = Instrument.FLAG_GETSET)

        # largest waveform that upload_waveform accepts (samples per channel)
        self.add_parameter('max_samples', type = int,
            flags = Instrument.FLAG_GETSET,
            minval = 32, maxval = 500_000_000)


    def _do_set_modulation_mode(self,new,channel):
        modes = {0: 'off', 1: 'sine 11 / 33', 2: 'sine 22 / 44', 3: 'sine 12 / 34', 4: 'sine 21 / 43', 5: 'advanced'}
        logging.info(__name__+ ': Switching channel %d modulation to %s.'% (channel, modes.get(new, str(new))))

        self.daq.setInt('/%s/AWGS/%d/OUTPUTS/%d/MODULATION/MODE'% (self.device, self._binary[channel-1][0], self._binary[channel-1][1]), new)
        self.daq.sync()

    def _do_get_modulation_mode(self, channel):
        output = self.daq.getInt('/%s/AWGS/%d/OUTPUTS/%d/MODULATION/MODE'% (self.device, self._binary[channel-1][0], self._binary[channel-1][1]))

        modes = {0: 'off', 1: 'sine 11 / 33', 2: 'sine 22 / 44', 3: 'sine 12 / 34', 4: 'sine 21 / 43', 5: 'advanced'}
        logging.info(__name__+ ': Channel %d modulation: %s.'% (channel, modes.get(output, str(output))))

        return output

    #Amplitude (units of full scale) AWG Output (has to be <= 1 !!)
    def _do_set_amplitude(self, new, channel):

        logging.info(__name__ + ': Setting amplitude channel %d to %s (units of full scale)'% (channel, str(new)))

        self.daq.setDouble('/%s/awgs/%d/outputs/%d/amplitude'% (self.device, self._binary[channel-1][0], self._binary[channel-1][1]), new)
        self.daq.sync()

    def _do_get_amplitude(self, channel):

        output = self.daq.getDouble('/%s/awgs/%d/outputs/%d/amplitude'% (self.device, self._binary[channel-1][0], self._binary[channel-1][1]))

        logging.info(__name__ + ': Reading amplitude channel %d: %s (units of full scale)'% (channel, str(output)))
        return output

    def _do_set_channel_output(self, new, channel):

        #set channel on device
        self.daq.setInt('/%s/sigouts/%d/on'% (self.device, channel-1), new)
        self.daq.sync()

        #logging information
        if new == 1:
            logging.info(__name__ + ': Switching channel %d output on'% channel)
        else:
            logging.info(__name__ + ': Switching channel %d output off'% channel)

        #save channel output information for further processing
        self._channel_outputs[channel-1] = new

    def _do_get_channel_output(self, channel):

        #readout
        output = self.daq.getInt('/%s/sigouts/%d/on'% (self._device_id, channel-1))

        #logging information
        if output == 1:
            logging.info(__name__ + ': Channel %d output is on'% channel)
        else:
            logging.info(__name__ + ': Channel %d output is off'% channel)

        return output

    def _do_set_marker_output(self, new, channel):
        """
        DOCUMENTATION

        set_chX_marker_output(new):

             Select what the marker output 'X' on the front panel plays.

             parameters:

             new (INT): 0 (no waveform marker: the output follows sequencer trigger 1, which is
                           low unless the sequencer program sets it),
                        1 (marker 1 of the wave on this output),
                        2 (marker 2 of the wave on this output)
             channel (INT): channel index 'X'

             Note: for new = 1 or 2 the analog output of the same channel is switched on as well
             (historic behaviour, the setups rely on it).
        """
        if new not in (0, 1, 2):
            raise ValueError("marker_output must be 0, 1 or 2")

        #switch on channel if output is used as marker
        #use set_channel_output to switch channel off, new = 0 will only switch off marker
        if new == 1 or new == 2:
            getattr(self, 'set_ch%d_channel_output' % channel)(1)

        #set marker on device
        settings_array = np.array([[0,4,5],[0,6,7]])
        self.daq.setInt('/%s/triggers/out/%d/source'% (self.device, channel-1), int(settings_array[(channel-1)%2][new]))
        self.daq.sync()

        #logging information
        if new != 0:
            logging.info(__name__ + ': Marker %d set to channel %d'% (new, channel))
        else:
            logging.info(__name__ + ': Switching marker channel %d off'% (channel))

        #save marker information for further processing
        self._marker_outputs[channel-1] = new

    #read out marker setting on awg, return number of marker
    def _do_get_marker_output(self, channel):
        """
        DOCUMENTATION

        get_chX_marker_output():

             Get marker output of channel 'X'

             parameters:

             channel (INT): channel index 'X'

             return value (INT): 0 (no waveform marker), 1 (marker 1 on), 2 (marker 2 on)

        """
        #readout
        output = self.daq.getInt('/%s/triggers/out/%d/source'% (self._device_id, channel-1))

        #convert read out setting to number of array (read out for triggers will be ignored)
        settings_array = np.array([[0,4,5],[0,6,7]])
        hits = np.where(settings_array[(channel-1)%2] == output)[0]
        result = int(hits[0]) if len(hits) else 0

        logging.info(__name__+ ': Reading marker %d on channel %d.'% (result, channel))
        return result

    def _do_set_delay(self,new,channel):
        """
        DOCUMENTATION

        set_chX_delay(new):

             Set delay of wave output channel 'X'

             parameters:

             new (FLOAT): 0 to 25.83e-9 s
             channel (INT): channel index 'X'

        """
        logging.info(__name__+': setting delay to %s ' %new +'s.')
        self.daq.setDouble('/%s/SIGOUTS/%d/DELAY'%(self._device_id,channel-1), new)
        self.daq.sync()
        print('Delay set to '+str(self.daq.getDouble('/%s/SIGOUTS/%d/DELAY'%(self._device_id,channel-1)))+'s.')

    def _do_get_delay(self, channel):
        """
        DOCUMENTATION

        get_chX_delay():

             Get delay of wave output channel 'X'

             parameters:

             channel (INT): channel index 'X'

             return value (FLOAT): 0 to 25.83e-9 s

        """
        logging.info(__name__+': getting delay.')
        return self.daq.getDouble('/%s/SIGOUTS/%d/DELAY'%(self._device_id,channel-1))

    def _do_set_direct(self,new,channel):
        """
        DOCUMENTATION

        set_chX_direct(new):

             Enable or disable direct mode of channel 'X'

             parameters:

             new (INT): 0 (disable), 1 (enable)
             channel (INT): channel index 'X'

        """
        if new == 0:
            logging.info(__name__+ ': Switching channel %d direct mode off.'% channel)
        if new == 1:
            logging.info(__name__+ ': Switching channel %d direct mode on.'% channel)

        self.daq.setInt('/%s/SIGOUTS/%d/DIRECT'%(self._device_id,channel-1), new)
        self.daq.sync()

    def _do_get_direct(self, channel):
        """
        DOCUMENTATION

        get_chX_direct():

             Check if direct mode of channel 'X' is enabled

             parameters:

             channel (INT): channel index 'X'

             return value (INT): 0 (disable), 1 (enable)

        """
        output=self.daq.getInt('/%s/SIGOUTS/%d/DIRECT'%(self._device_id,channel-1))
        if output == 0:
            logging.info(__name__+ ': Channel %d direct mode: off.'% channel)
        if output == 1:
            logging.info(__name__+ ': Channel %d direct mode: on.'% channel)

        return output

    def _do_set_user_regs(self,new, channel):
        """
        DOCUMENTATION

        self.set_regX_user_regs(new)

             Set value of register 'X'

             parameters:

             new (INT): arbitrary integer value
             channel (INT): register index 'X' (1-16: core 0, 17-32: core 1)

        """
        #translate register number to nodes values
        _first_node_value = (channel-1) // 16
        _second_node_value = (channel-1) % 16

        self.daq.setInt('/%s/AWGS/%d/USERREGS/%d'% (self.device, _first_node_value, _second_node_value), new)
        self.daq.sync()
        logging.info(__name__ + ': User register %d value set to %d'% (channel, new))

    def _do_get_user_regs(self, channel):
        """
        DOCUMENTATION

        self.get_regX_user_regs()

             Get value of register 'X'

             parameters:

             channel (INT): register index 'X' (1-16: core 0, 17-32: core 1)

             return value (INT): register value

        """
        #translate register number to nodes values
        _first_node_value = (channel-1) // 16
        _second_node_value = (channel-1) % 16

        output = self.daq.getInt('/%s/AWGS/%d/USERREGS/%d'% (self.device, _first_node_value, _second_node_value))
        logging.info(__name__ + ': User register %d value is %d'% (channel, output))
        return output

    #set channel grouping, possible integer values for HDAWG4 are 0 (groups of 2) or 1 (groups of 4)
    def _do_set_channel_grouping(self,new):
        """
        DOCUMENTATION

        self.set_channel_grouping(new)

             Set the channel grouping of the device

             parameters:

             new (INT): 0 (2x2: two cores with two outputs each), 1 (1x4: one core with four outputs)

             The rest of this driver (upload_waveform, amplitude, modulation_mode) assumes 2x2.

        """
        if new == 0:
            logging.info(__name__+ ': Setting channel grouping to groups of 2.')
        if new == 1:
            logging.info(__name__+ ': Setting channel grouping to groups of 4.')
        self.daq.setInt('/%s/SYSTEM/AWG/CHANNELGROUPING' % self._device_id, new)
        self.daq.sync()

    def _do_get_channel_grouping(self):
        logging.info(__name__+': getting channel_grouping.')
        output = self.daq.getInt('/%s/SYSTEM/AWG/CHANNELGROUPING' % self._device_id)
        if output == 0:
            logging.info(__name__+ ': Channel grouping set to groups of 2.')
        if output == 1:
            logging.info(__name__+ ': Channel grouping set to groups of 4.')
        return output

    def _do_set_sampling_clock(self, newclock):
        logging.info(__name__+ ': Setting sample clock to %f.' % newclock)
        self.daq.setDouble('/%s/system/clocks/sampleclock/freq' % self._device_id, newclock)
        self.daq.sync()

    def _do_get_sampling_clock(self):
        logging.info(__name__+ ': Getting sample clock.')
        return self.daq.getDouble('/%s/system/clocks/sampleclock/freq' % self._device_id)

    def _do_set_sampling_prescaler(self, newdiv, core=None):
        """
        Set the sampling rate divider 2^n (n = 0...13) of an AWG core.
        core: 0 or 1 for a single core; None (default) sets both cores to the same value.
        """
        if newdiv not in self._prescaler:
            raise ValueError(__name__ + " Could not set sampling prescaler, must be 2^n, with n between 0 and 13")
        if core is None:
            cores = (0, 1)
        elif core in (0, 1):
            cores = (core,)
        else:
            raise ValueError("The core must be 0, 1 or None (both). Value out of range.")

        exponent = int(np.log2(newdiv))
        for c in cores:
            logging.info(__name__ + ': Setting sampling prescaler of core %d to %d' % (c, newdiv))
            self.daq.setInt('/%s/AWGS/%d/TIME' % (self._device_id, c), exponent)
        self.daq.sync()     # make sure the new rate is applied before anything reads it back

    def _do_get_sampling_prescaler(self, core = 0):
        """
        Get the sampling rate divider of an AWG core.
        core: 0 (default) or 1
        """
        if core not in (0, 1):
            raise ValueError("The core must be 0 or 1. Value out of range.")
        logging.info(__name__ +': getting sampling_prescaler of core %d' % core)
        exponent = self.daq.getInt('/%s/AWGS/%d/TIME' % (self._device_id, core))
        return 2**exponent

    def _do_get_sampling_rate(self, core = 0):
        """
        Get the actual sampling rate (sample clock / prescaler) of an AWG core in Sa/s.
        core: 0 (default) or 1
        """
        if core not in (0, 1):
            raise ValueError("The core must be 0 or 1. Value out of range.")
        logging.info(__name__ +': getting sampling_rate of core %d' % core)
        clock = self.daq.getDouble('/%s/system/clocks/sampleclock/freq' % self._device_id)
        prescaler = 2**self.daq.getInt('/%s/AWGS/%d/TIME' % (self._device_id, core))
        return clock/prescaler

    def _do_set_output_range(self,new,channel):
        """
        Set the output range of channel 'X'. Allowed values (V): 0.2 / 0.4 / 0.6 / 0.8 / 1 / 2 / 3 / 4 / 5.
        Other values are rounded down to the next allowed one (values below 0.2 V give 0.2 V).
        """
        if not np.any(np.isclose(self._Vrange_array, new)):
            idx = max(int(np.searchsorted(self._Vrange_array, new, side = 'right')) - 1, 0)
            new = self._Vrange_array[idx]
            logging.warning('Output range must be equal to one of the following values (in V): '
                            '0.2 / 0.4 / 0.6 / 0.8 / 1 / 2 / 3 / 4 / 5. Setting output range to ' + str(new) + ' V')
        logging.info(__name__+': setting output range of channel %d to %s V.' % (channel, str(new)))
        self.daq.setDouble('/%s/SIGOUTS/%d/RANGE' % (self._device_id, channel-1), float(new))
        self.daq.sync()

    def _do_get_output_range(self,channel):

        output = self.daq.getDouble('/%s/SIGOUTS/%d/RANGE' % (self._device_id, channel-1))
        logging.info(__name__+': output range of channel %d : %s V.' % (channel, str(output)))

        return output

    def _do_set_voltage_offset(self, new, channel, speed = 0.2, voltage_step = 1e-3):
        """
        Ramp the offset of output 'X' to a new value.

        new (FLOAT): target offset in V
        speed (FLOAT): ramp speed in V/s
        voltage_step (FLOAT): step size of the ramp in V
        """
        if speed <= 0 or voltage_step <= 0:
            raise ValueError("speed and voltage_step must be larger than 0")

        node = '/%s/sigouts/%d/offset'% (self.device, channel-1)
        init_voltage = self.daq.getDouble(node)
        n_steps = int(np.ceil(abs(new - init_voltage) / voltage_step - 1e-9))

        #works in both directions and ends exactly at the target
        for volt in np.linspace(init_voltage, new, n_steps + 1)[1:]:
            self.daq.setDouble(node, float(volt))
            time.sleep(voltage_step / speed)
        self.daq.sync()

        logging.info(__name__ + ': Channel %d offset set to %s V'% (channel, str(new)))

    def _do_get_voltage_offset(self, channel):
        #readout channel offset
        output = self.daq.getDouble('/%s/sigouts/%d/offset'% (self._device_id, channel-1))

        logging.info(__name__ + ': Channel %d offset is %s V'% (channel, str(output)))
        return output

    def _do_set_voltage_limit(self, maxV):
        """
        Limit the output range that upload_waveform is allowed to select (in V, 0.2 to 5).
        """
        if not (self._Vrange_array[0] <= maxV <= self._Vrange_array[-1]):
            raise ValueError("voltage_limit must be between %s and %s V" % (self._Vrange_array[0], self._Vrange_array[-1]))
        self._max_Vrange = maxV
        logging.info(__name__+': output range is limited to %s V' % str(maxV))

    def _do_get_voltage_limit(self):
        return self._max_Vrange

    def _do_set_console_output(self, output_bool):
        self._console_output = bool(output_bool)
        logging.info(__name__+': console output is set to %s' % str(self._console_output))

    def _do_get_console_output(self):
        return self._console_output

    def _do_set_auto_range(self, state):
        '''
        True (default): upload_waveform sets the smallest output range that fits the waveform.
        False: the output range set with set_chX_output_range is kept; a waveform that does not
               fit raises an error. Use this to avoid range switching within a sweep.
        '''
        self._auto_range = bool(state)
        logging.info(__name__ + ': automatic output range %s' % ('on' if self._auto_range else 'off'))

    def _do_get_auto_range(self):
        return self._auto_range

    def _do_set_max_samples(self, n):
        '''
        Largest waveform (samples per channel) that upload_waveform accepts.
        Large waveforms need several GB of RAM on the measurement PC.
        '''
        self._max_samples = int(n)
        logging.info(__name__ + ': maximum waveform length set to %d samples' % self._max_samples)

    def _do_get_max_samples(self):
        return self._max_samples

    #start awg sequencer
    def start_playback(self, cores = (0, 1)):
        """
        Enable the sequencer of the given cores (default: both).
        """
        for core in cores:
            self.daq.setInt(f"/{self.device}/awgs/{core}/enable", 1)

    #stop awg sequencer
    def stop_playback(self, cores = (0, 1)):
        """
        Disable the sequencer of the given cores (default: both).
        """
        for core in cores:
            self.daq.setInt(f"/{self.device}/awgs/{core}/enable", 0)

    #disable everything
    def disable_everything(self):
        zhinst.utils.disable_everything(self.daq, self.device)
        logging.info(__name__+': all outputs etc. disabled')

    def set_trigger(self, enabled=True):
        """
        Switch the digital trigger wait in the sequencer program on or off.
        Takes effect the next time upload_waveform() is called.

        enabled (BOOL): True  -> waitDigTrigger(1) before each playWave (default)
                        False -> free-running loop without trigger
        """
        self._use_trigger = bool(enabled)
        logging.info(__name__ + ': trigger %s' % ('enabled' if self._use_trigger else 'disabled'))

    # ------------------------------------------------------------------------------------------
    # old upload path (csv files + own sequencer program)
    # ------------------------------------------------------------------------------------------

    #create backup of folder "waves/" and empty it
    def refresh_folder(self):

        #if folder "waves/" already exists, create new folder and backup existing one
        if os.path.exists(self.wave_dir):
            #create backup folder name (folder in "awg/") using timestamp
            ts = int(time.time())
            folder = self.wave_dir.replace("waves/","")
            foldername = folder+'old_waves_backup_'+str(ts)

            #rename current waveform folder to backup folder
            shutil.move(self.wave_dir,foldername)
            logging.info(__name__+'Backup wavefolder created:'+str(foldername)+'.')

        #create new waveform folder
        os.mkdir(self.wave_dir)
        logging.info(__name__+'Wavefolder emptied.')

    #write sequence array to csv file and display preview
    #when used in a loop, stamp has to be equal to the iteration index
    #the input array for multiple channels must have the form (['channel1','channel2',...])
    #select preview plot by setting preview = 'yes' (default: 'no')
    def write(self,array,stamp = 1,preview = 'no'):

        #csv files are saved for the outputs that are switched on, using A,B,C or D for channels 1 to 4
        channeldefinitions = [letter for letter, on in zip(['A','B','C','D'], self._channel_outputs) if on != 0]
        if len(array) > len(channeldefinitions):
            raise ValueError("%d waveforms given, but only %d channel outputs are switched on"
                             % (len(array), len(channeldefinitions)))

        #create new csv file
        for u in range(0,len(array)):

            #check if waveform length is aligned to 16 (see AWG granularity in user manual)
            if len(array[u])%16!=0:
                logging.warning(__name__+' Waveform number ' +str(u)+': length has to be a multiple of 16, '
                                'the AWG will modify the waveform.')

            filename = str(self.wave_dir)+"custom"+str(stamp)+channeldefinitions[u]+".csv"
            Path(filename).touch()

            #write array to csv file
            with open(filename,'w') as file:
                for v in range(0,len(array[u])):
                    file.write(str(array[u][v])+'\n')

            logging.info(__name__+'Waveform written to: '+str(filename))

            #preview
            if preview == 'yes':
                #preview with matplotlib and terminal output
                logging.info(__name__+'\nPartial sequence generated - array length (samples):'+str(len(array[u]))+'\n')

                x = range(0,len(array[u]))
                y = array[u]
                plt.plot(x,y)
                plt.title("sequence preview")
                plt.show()

            #give array length to self._waveform_max_length to set trigger in zcreate_sequence_program
            if (len(array[u])>self._waveform_max_length):
                self._waveform_max_length = len(array[u])

    #load own sequential C program (input as string)
    def set_program_string(self, program):
        if type(program) != str:
            raise TypeError(__name__ + ": Assigned value must be a string")
        self.awg_program = program
        logging.info(__name__+' : sequence program :\n\n'+self.awg_program+'\n\n')

    #compile and upload sequence to device
    def upload_to_device(self, core = 0):
        """
        Compile the program given with set_program_string() and upload it to an AWG core.
        core: 0 (default) or 1
        """
        if core not in (0, 1):
            raise ValueError("The core must be 0 or 1. Value out of range.")
        if not self.awg_program:
            raise Exception("No sequencer program set, use set_program_string() first.")

        #check if folder containing wave files exists
        if not os.path.isdir(self.wave_dir):
            raise Exception(f"Wave folder {self.wave_dir} does not exist or is not a directory.")

        #transfer and compile sequence program
        self.awgModule.set("index", core)
        self.awgModule.set("compiler/sourcestring", self.awg_program)
        while self.awgModule.getInt("compiler/status") == -1:
            time.sleep(0.1)

        #raise exception if compilation has failed
        if self.awgModule.getInt("compiler/status") == 1:
            raise Exception(self.awgModule.getString("compiler/statusstring"))

        #upload messages
        if self.awgModule.getInt("compiler/status") == 0:
            print("Compilation successful (no warnings), uploading.")
        if self.awgModule.getInt("compiler/status") == 2:
            print("Compilation successful (with warnings), uploading.")
            print("Compiler warning: ", self.awgModule.getString("compiler/statusstring"))

        #wait until uploaded
        time.sleep(0.2)
        i = 0
        while (self.awgModule.getDouble("progress") < 1.0) and (self.awgModule.getInt("elf/status") != 1):
            print(f"{i} progress: {self.awgModule.getDouble('progress'):.2f}")
            time.sleep(0.2)
            i += 1
        print(f"{i} progress: {self.awgModule.getDouble('progress'):.2f}")
        if self.awgModule.getInt("elf/status") == 0:
            print("Upload successful.")
        if self.awgModule.getInt("elf/status") == 1:
            raise Exception("Upload failed.")

        #set single mode
        #According to Zurich Instruments:
        # "This is the preferred method of using the AWG: Run in single mode continuous waveform playback is best achieved by
        # using an infinite loop (e.g., while (true)) in the sequencer program."
        self.daq.setInt(f"/{self.device}/awgs/{core}/single", 1)

    # ------------------------------------------------------------------------------------------
    # new upload path (direct upload from python)
    # ------------------------------------------------------------------------------------------

    # upload waveform from array
    def upload_waveform(self, awg_core, wave_dict):
        """
        Upload waves and markers to one AWG core and load the matching sequencer program.

        awg_core (INT): 0 (outputs 1/2) or 1 (outputs 3/4)
        wave_dict (DICT): any of "Ch1", "Ch2" (waves in V) and "Trig1", "Trig2" (markers, 0 / 1),
                          all with the same length. Keys are relative to the core
                          (on core 1: Ch1 -> output 3, Trig2 -> marker 4).

        Marker word: bit 0 = marker 1 of wave 1 (Trig1), bit 2 = marker 1 of wave 2 (Trig2).
        The marker output is HIGH where the Trig array is above self._marker_threshold (0.5).
        A marker without a wave on the same output is played on a zero wave.
        The dictionary and arrays of the caller are not modified.

        The core is stopped before the upload and stays stopped; start it with start_playback().
        """
        if awg_core not in (0, 1):
            raise ValueError("awg_core must be 0 or 1")
        allowed = ("Ch1", "Ch2", "Trig1", "Trig2")
        unknown = [k for k in wave_dict if k not in allowed]
        if unknown:
            raise ValueError(f"Unknown channel(s) {unknown}, allowed: {allowed}")
        if not wave_dict:
            raise Exception("No waveform provided")

        # no copies here: every step below creates new arrays, the caller's data stay untouched
        data = {k: np.asarray(v, dtype=float) for k, v in wave_dict.items()}

        lengths = {k: len(v) for k, v in data.items()}
        if len(set(lengths.values())) != 1:
            raise ValueError(f"All waves and markers of one core need the same length, got {lengths}")
        n_raw = next(iter(lengths.values()))
        if n_raw == 0:
            raise ValueError("Empty waveform")
        if n_raw > self._max_samples:
            raise ValueError(f"Waveform of core {awg_core} has {n_raw:,} samples, more than max_samples = "
                             f"{self._max_samples:,}. Use a larger sampling prescaler or a shorter pulse, "
                             f"or raise the limit with set_max_samples().")

        has_marker = {k: f"Trig{k}" in data for k in ("1", "2")}
        user_wave  = {k: f"Ch{k}" in data for k in ("1", "2")}

        # stop the core before its program and memory are replaced
        self.daq.setInt(f"/{self.device}/awgs/{awg_core}/enable", 0)
        self.daq.sync()

        # --- output range and normalisation (only for waves given by the caller) ---
        for k in ("1", "2"):
            if not user_wave[k]:
                continue
            wave = data[f"Ch{k}"]
            output = int(k) + 2 * awg_core                      # physical output 1..4
            maxV = float(np.max(np.abs(wave)))
            if maxV > self._max_Vrange:
                raise Exception(f"Output {output}: waveform peak {maxV:.4g} V exceeds the voltage limit "
                                f"of {self._max_Vrange} V")

            # DC content charges the bias tee
            if self._dc_warning is not None and maxV > 0:
                mean = float(np.mean(wave))
                if abs(mean) > self._dc_warning * maxV:
                    message = (f"Output {output}: the wave has a mean of {mean*1e3:.3g} mV over the cycle "
                               f"({abs(mean)/maxV*100:.1f} % of its peak). This DC part charges the bias tee.")
                    logging.warning(__name__ + ': ' + message)
                    if self._console_output:
                        print("WARNING " + message)

            node = '/%s/SIGOUTS/%d/RANGE' % (self._device_id, output - 1)
            current = self.daq.getDouble(node)
            direct = self.daq.getInt('/%s/SIGOUTS/%d/DIRECT' % (self._device_id, output - 1))
            if self._auto_range and not direct:
                idx = min(int(np.searchsorted(self._Vrange_array, maxV, side='left')), len(self._Vrange_array) - 1)
                new = float(self._Vrange_array[idx])
                if not np.isclose(new, current):                  # only switch the range when it changes
                    if self._console_output:
                        print(f"Setting ch{output} output range to {new} V to match waveform data.")
                    self.set(f'ch{output}_output_range', new)
                    current = self.daq.getDouble(node)
            # scale with the range the instrument really uses
            if current <= 0:
                raise Exception(f"Output {output}: could not read a valid output range ({current})")
            if maxV > current * (1 + 1e-9):
                raise Exception(f"Output {output}: waveform peak {maxV:.4g} V does not fit into the output range "
                                f"of {current} V" + (" (direct mode)" if direct else
                                                     " (automatic range is off)" if not self._auto_range else ""))
            data[f"Ch{k}"] = wave / current

        # --- length: multiple of 16 samples, at least 32 ---
        n = max(32, int(np.ceil(n_raw / 16)) * 16)
        if n != n_raw:
            if self._console_output:
                print(f"Waveform of core {awg_core} has {n_raw} samples and is zero-extended to {n}.")
            for key in data:
                data[key] = np.append(data[key], np.zeros(n - n_raw))

        # --- marker word ---
        any_marker = has_marker["1"] or has_marker["2"]
        marker = np.zeros(n, dtype=np.uint16)
        if has_marker["1"]:
            marker[data["Trig1"] > self._marker_threshold] |= 0b0001      # wave 1, marker 1
        if has_marker["2"]:
            marker[data["Trig2"] > self._marker_threshold] |= 0b0100      # wave 2, marker 1

        def tf(flag):
            return "true" if flag else "false"

        # --- sequencer program and waveform slot ---
        waveforms = Waveforms()
        if any_marker or (user_wave["1"] and user_wave["2"]):
            # two-wave form; a missing wave is replaced by zeros so that its marker can be played
            w1 = data["Ch1"] if user_wave["1"] else np.zeros(n)
            w2 = data["Ch2"] if user_wave["2"] else np.zeros(n)
            sequencer  = f"wave w1 = placeholder({n}, {tf(has_marker['1'])}, false);\n"
            sequencer += f"wave w2 = placeholder({n}, {tf(has_marker['2'])}, false);\n"
            play_args = "1, w1, 2, w2"
            waveforms[0] = (w1, w2, marker) if any_marker else (w1, w2)
        elif user_wave["1"]:
            sequencer = f"wave w1 = placeholder({n}, false, false);\n"
            play_args = "1, w1"
            waveforms[0] = (data["Ch1"],)
        elif user_wave["2"]:
            sequencer = f"wave w2 = placeholder({n}, false, false);\n"
            play_args = "2, w2"
            waveforms[0] = (data["Ch2"],)
        else:
            raise Exception("No waveform provided")

        sequencer += f"assignWaveIndex({play_args}, 0);\n"
        if self._use_trigger:
            sequencer += "while(true){\nwaitDigTrigger(1);\nplayWave(" + play_args + ");\nwaitWave();\n}"
        else:
            sequencer += "while(true){\nplayWave(" + play_args + ");\n}"

        if self._console_output:
            print("")
            print(sequencer, "\n")

        # --- write sequencer code and upload the waveform to the AWG ---
        awg_node = self.device_new.awgs[awg_core]
        awg_node.load_sequencer_program(sequencer)   # compiles and uploads, blocks until done
        awg_node.write_to_waveform_memory(waveforms)
        self.daq.sync()                              # make sure everything has arrived before a start

    #load config file from path
    def load_config_file(self, path):
        logging.info(__name__+': loading config file %s '% path)
        with open(path, 'r') as f:
            config_data = json.load(f)
        settings = config_data['device_settings'][0]

        #set sampling rate
        self.set_sampling_clock(settings['sampling_clock'])
        #set user registers
        for i in range(1,33):
            getattr(self, 'set_reg%d_user_regs' % i)(int(settings['user_reg%d' % i]))
        #set channel grouping
        self.set_channel_grouping(settings['channel_grouping'])
        for ch in range(1,5):
            #set channel outputs on or off
            getattr(self, 'set_ch%d_channel_output' % ch)(settings['channel_output_channel%d' % ch])
        for ch in range(1,5):
            #set marker outputs (1 or 2) on or off
            getattr(self, 'set_ch%d_marker_output' % ch)(settings['marker_output_channel%d' % ch])
        for ch in range(1,5):
            #set channel output range
            getattr(self, 'set_ch%d_output_range' % ch)(settings['output_range_channel%d' % ch])
        for ch in range(1,5):
            #set channel amplitudes
            getattr(self, 'set_ch%d_amplitude' % ch)(settings['amplitude_channel%d' % ch])
        for ch in range(1,5):
            #set modulation mode
            getattr(self, 'set_ch%d_modulation_mode' % ch)(settings['modulation_mode_channel%d' % ch])
        for ch in range(1,5):
            #set direct mode
            getattr(self, 'set_ch%d_direct' % ch)(settings['direct_channel%d' % ch])


if __name__ == "__main__":
    qkit.start()

    #example: create a ZI_HDAWG4 instance and upload a pulse with a marker to core 0
    device_identification = 'dev8980'
    hartwig = qkit.instruments.create('hartwig','ZI_HDAWG4',device_id = device_identification)

    #hartwig.set_trigger(False)                 # free-running loop
    #hartwig.set_sampling_prescaler(2**5)       # both cores
    #wave   = np.concatenate([np.zeros(160), 0.1*np.ones(160), np.zeros(160)])   # V
    #marker = np.concatenate([np.zeros(160), np.ones(160), np.zeros(160)])
    #hartwig.set_ch2_marker_output(1)
    #hartwig.set_auto_range(True)               # choose the output range automatically
    #hartwig.upload_waveform(0, {"Ch1": wave, "Trig2": marker})
    #hartwig.start_playback(cores=(0,))

    #disable everything
    #hartwig.disable_everything()