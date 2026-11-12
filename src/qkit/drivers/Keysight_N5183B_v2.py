# Keysight_N5183B.py class, to perform the communication between the Wrapper and the device
# based on Agilent_E8257D.py
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

import logging

import pyvisa  # use pyvisa for initialization

import qkit
from qkit.core.instrument_base import Instrument


class Keysight_N5183B_v2(Instrument):
    '''
    This is the driver for the Keysight N5183B MXG microwave analog signal generator.

    Usage:
    Initialize with
    <name> = qkit.instruments.create('<name>', 'Keysight_N5183B', address='<IP address>', reset=<bool>)

    Pulse modulation (needs option UNW / UNU, option 320 for 'pulse_train'):

        mode             what the RF output does
        ---------------  ----------------------------------------------------------------------
        'continuous'     pulse modulation off, the RF is on all the time (CW)
        'gated'          external: the RF follows the signal at the PULSE input
                         (RF on while the input is high for pulse_polarity 'normal')
        'square'         internal square wave, 50 % duty cycle, rate = pulse_frequency
        'free_run'       internal pulse train with pulse_period, pulse_width, pulse_delay
        'triggered'      one pulse (pulse_width, pulse_delay) per trigger at the PULSE input
        'doublet'        two pulses per trigger: the first follows the trigger input,
                         the second has pulse_width / pulse_delay
        'adjustable_doublet'  two pulses per trigger: pulse_width / pulse_delay and
                         pulse_width2 / pulse_delay2 (second one timed from the first)
        'gated_train'    internal pulse train (pulse_period, pulse_width) while a gate is
                         applied to the PULSE input
        'pulse_train'    programmed pulse train per trigger (option 320)

    pulse_polarity only acts on the external PULSE input:
        'normal'    the generator responds to a TTL high level
        'inverted'  the generator responds to a TTL low level

    Safety:
        * set_power() refuses powers above max_power (default +10 dBm, set_max_power() to change).
        * set_mode() and set_pulse_polarity() read the setting back and check the error queue;
          a setting the instrument did not take raises an error.
        * on() prints mode and polarity and refuses to switch on in 'continuous' (CW on the sample)
          unless allow_cw is set (set_allow_cw(True)) or on(force=True) is used.
        * Pulses shorter than 1 us need the ALC off: prepare_short_pulses(True).
    '''

    # mode name -> SCPI value of :PULM:SOURce:INTernal
    _INTERNAL_MODES = {
        'square':             'SQUare',
        'free_run':           'FRUN',
        'triggered':          'TRIGgered',
        'adjustable_doublet': 'ADOublet',
        'doublet':            'DOUBlet',
        'gated_train':        'GATEd',
        'pulse_train':        'PTRain',
    }
    _POLARITIES = {'normal': 'NORMal', 'inverted': 'INVerted'}

    def __init__(self, name, address, reset=False):
        '''
        Initializes the Keysight_N5183B, and communicates with the wrapper.

        Input:
            name (string)    : name of the instrument
            address (string) : IP address
            reset (bool)     : resets to default values, default=False
        '''
        logging.info(__name__ + ' : Initializing instrument Keysight_N5183B')
        Instrument.__init__(self, name, tags=['physical'])

        self._address = 'TCPIP0::' + address + '::hislip0::INSTR'
        self._rm = pyvisa.ResourceManager()
        self._instrument = self._rm.open_resource(self._address)
        self._instrument.timeout = 10000            # ms; *RST and mode changes can take a few seconds

        # safety settings
        self._max_power = 10.0                      # dBm, set_power() refuses anything above
        self._allow_cw = False                      # on() refuses 'continuous' unless this is True
        self._check_errors = True                   # raise if the instrument reports an error after a setting

        # Implement parameters
        self.add_parameter('power',
            flags=Instrument.FLAG_GETSET, units='dBm', minval=-135, maxval=30, offset=True, type=float)
        self.add_parameter('frequency',
            flags=Instrument.FLAG_GETSET, units='Hz', minval=9e3, maxval=20e9, type=float)
        self.add_parameter('status',
            flags=Instrument.FLAG_GETSET, type=bool)
        self.add_parameter('mode',
            flags=Instrument.FLAG_GETSET, type=str)

        # pulse modulation
        self.add_parameter('pulse_polarity',
            flags=Instrument.FLAG_GETSET, type=str)
        self.add_parameter('video_polarity',
            flags=Instrument.FLAG_GETSET, type=str)
        self.add_parameter('pulse_width',
            flags=Instrument.FLAG_GETSET, units='s', minval=20e-9, maxval=42, type=float)
        self.add_parameter('pulse_delay',
            flags=Instrument.FLAG_GETSET, units='s', minval=0, maxval=42, type=float)
        self.add_parameter('pulse_width2',
            flags=Instrument.FLAG_GETSET, units='s', minval=20e-9, maxval=42, type=float)
        self.add_parameter('pulse_delay2',
            flags=Instrument.FLAG_GETSET, units='s', minval=0, maxval=42, type=float)
        self.add_parameter('pulse_period',
            flags=Instrument.FLAG_GETSET, units='s', minval=30e-9, maxval=42, type=float)
        self.add_parameter('pulse_frequency',
            flags=Instrument.FLAG_GETSET, units='Hz', minval=0.1, maxval=10e6, type=float)

        # general modulation switch ("Mod On/Off" key) and automatic level control
        self.add_parameter('modulation',
            flags=Instrument.FLAG_GETSET, type=bool)
        self.add_parameter('alc',
            flags=Instrument.FLAG_GETSET, type=bool)

        # safety
        self.add_parameter('max_power',
            flags=Instrument.FLAG_GETSET, units='dBm', minval=-135, maxval=30, type=float)
        self.add_parameter('allow_cw',
            flags=Instrument.FLAG_GETSET, type=bool)

        self.add_function('reset')
        self.add_function('get_all')
        self.add_function('get_pulse_settings')
        self.add_function('get_error')
        self.add_function('write')
        self.add_function('query')
        self.add_function('ask')
        self.add_function('on')
        self.add_function('off')
        self.add_function('close')
        self.add_function('prepare_short_pulses')

        if (reset):
            self.reset()
        else:
            self.get_all()

    # ------------------------------------------------------------------------------------------
    # raw communication
    # ------------------------------------------------------------------------------------------
    def write(self, command):
        '''
        Send a raw SCPI command to the instrument.
        '''
        self._instrument.write(command)

    def query(self, command):
        '''
        Send a raw SCPI query and return the answer as a string.
        '''
        return self._instrument.query(command).strip()

    def ask(self, command):
        '''
        Same as query().
        '''
        return self.query(command)

    def get_error(self):
        '''
        Read all entries of the error queue of the instrument.

        Output:
            errors (list of strings) : empty list if there is no error
        '''
        errors = []
        for _ in range(50):
            answer = self.query(":SYST:ERR?")
            if answer.startswith("+0") or answer.startswith("0"):
                break
            errors.append(answer)
        return errors

    def _raise_on_error(self, action):
        '''
        Read the error queue after a setting and raise if the instrument reports an error.
        '''
        if not self._check_errors:
            return
        errors = self.get_error()
        if errors:
            raise RuntimeError(f"{action}: the instrument reported {errors}")

    def close(self):
        '''
        Close the connection to the instrument.
        '''
        try:
            self._instrument.close()
        finally:
            self._rm.close()

    @staticmethod
    def _to_bool(answer):
        return answer.strip().upper() in ("1", "+1", "ON")

    def reset(self):
        '''
        Resets the instrument to default values

        Input:
            None

        Output:
            None
        '''
        logging.info(__name__ + ' : resetting instrument')
        self._instrument.write("*RST")
        self._instrument.query("*OPC?")
        self._instrument.write("*CLS")              # clear the error queue
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
        self.get_frequency()
        self.get_status()
        # the pulse parameters need the pulse option; do not fail on instruments without it
        for name in ('mode', 'pulse_polarity', 'modulation'):
            try:
                getattr(self, 'get_' + name)()
            except Exception as e:
                logging.warning(__name__ + ' : could not read %s (%s)' % (name, e))

    def get_pulse_settings(self, show=True):
        '''
        Read all pulse modulation settings.

        Input:
            show (bool) : print the settings, default=True

        Output:
            settings (dict)
        '''
        settings = {}
        for name in ('status', 'power', 'frequency', 'max_power', 'allow_cw',
                     'mode', 'pulse_polarity', 'modulation', 'alc', 'video_polarity',
                     'pulse_width', 'pulse_delay', 'pulse_width2', 'pulse_delay2',
                     'pulse_period', 'pulse_frequency'):
            try:
                settings[name] = getattr(self, 'do_get_' + name)()
            except Exception as e:
                settings[name] = 'not available (%s)' % e
        if show:
            for key, value in settings.items():
                print(f"{key:16s}: {value}")
        return settings

    # ------------------------------------------------------------------------------------------
    # power, frequency, output
    # ------------------------------------------------------------------------------------------
    def do_get_power(self):
        '''
        Reads the power of the signal from the instrument

        Output:
            ampl (float) : power in dBm
        '''
        logging.debug(__name__ + ' : get power')
        return float(self._instrument.query("POW?"))

    def do_set_power(self, amp):
        '''
        Set the power of the signal

        Input:
            amp (float) : power in dBm
        '''
        logging.debug(__name__ + ' : set power to %f' % amp)
        if amp > self._max_power:
            raise ValueError(f"set_power(): {amp} dBm is above max_power = {self._max_power} dBm. "
                             f"Raise the limit with set_max_power() if this is intended.")
        self._instrument.write(f"POW {float(amp)} DBM")

    def do_get_frequency(self):
        '''
        Reads the frequency of the signal from the instrument

        Output:
            freq (float) : Frequency in Hz
        '''
        logging.debug(__name__ + ' : get frequency')
        return float(self._instrument.query("FREQ?"))

    def do_set_frequency(self, freq):
        '''
        Set the frequency of the instrument

        Input:
            freq (float) : Frequency in Hz
        '''
        logging.debug(__name__ + ' : set frequency to %f' % freq)
        self._instrument.write(f"FREQ {float(freq)!r} HZ")

    def do_get_status(self):
        '''
        Reads the output status from the instrument

        Output:
            status (bool) : True (RF on) or False (RF off)
        '''
        logging.debug(__name__ + ' : get status')
        return self._to_bool(self._instrument.query("OUTP?"))

    def do_set_status(self, status):
        '''
        Set the output status of the instrument

        Input:
            status (bool) : True (RF on) or False (RF off)
        '''
        logging.debug(__name__ + ' : set status to %s' % status)

        if status is True or status == 1:
            self._instrument.write("OUTP ON")
        elif status is False or status == 0:
            self._instrument.write("OUTP OFF")
        else:
            raise ValueError('set_status(): can only set True or False')

    def do_get_max_power(self):
        '''
        Reads the largest power that set_power() accepts (dBm).
        '''
        return self._max_power

    def do_set_max_power(self, limit):
        '''
        Set the largest power that set_power() accepts.
        Lowering it below the current power switches nothing, but the next set_power() is checked.

        Input:
            limit (float) : dBm
        '''
        self._max_power = float(limit)
        logging.info(__name__ + ' : max power set to %s dBm' % limit)
        try:
            current = self.do_get_power()
            if current > self._max_power:
                print(f"WARNING: the current power ({current} dBm) is above the new limit ({self._max_power} dBm).")
        except Exception:
            pass

    def do_get_allow_cw(self):
        '''
        Reads whether on() may switch the RF on in 'continuous' mode.
        '''
        return self._allow_cw

    def do_set_allow_cw(self, state):
        '''
        Allow on() to switch the RF on while pulse modulation is off (CW on the sample).

        Input:
            state (bool)
        '''
        self._allow_cw = bool(state)

    def do_get_modulation(self):
        '''
        Reads the general modulation switch ("Mod On/Off" key).
        Pulse modulation only acts on the RF output while this is on.

        Output:
            modulation (bool)
        '''
        logging.debug(__name__ + ' : get modulation')
        return self._to_bool(self._instrument.query(":OUTP:MOD?"))

    def do_set_modulation(self, state):
        '''
        Set the general modulation switch ("Mod On/Off" key).

        Input:
            state (bool)
        '''
        logging.debug(__name__ + ' : set modulation to %s' % state)
        self._instrument.write(":OUTP:MOD " + ("ON" if state else "OFF"))

    def do_get_alc(self):
        '''
        Reads the state of the automatic level control (ALC).

        Output:
            alc (bool)
        '''
        logging.debug(__name__ + ' : get alc')
        return self._to_bool(self._instrument.query(":POW:ALC?"))

    def do_set_alc(self, state):
        '''
        Switch the automatic level control (ALC) on or off.
        Pulses shorter than 1 us need ALC off.

        Input:
            state (bool)
        '''
        logging.debug(__name__ + ' : set alc to %s' % state)
        self._instrument.write(":POW:ALC " + ("ON" if state else "OFF"))
        self._raise_on_error(f"set_alc({state})")

    def prepare_short_pulses(self, enable=True):
        '''
        Pulses shorter than 1 us need the ALC off (data sheet: >= 1 us with ALC on, >= 20 ns with ALC off).
        With the ALC off the output level is less accurate; re-check the Rabi frequency after switching.

        Input:
            enable (bool) : True switches the ALC off, False switches it back on
        '''
        self.set_alc(not enable)
        print(f"ALC {'off: pulses down to 20 ns' if enable else 'on: pulses >= 1 us'}")

    # ------------------------------------------------------------------------------------------
    # pulse modulation
    # ------------------------------------------------------------------------------------------
    def do_get_mode(self):
        '''
        Reads the mode of the pulse modulation (see class documentation).

        Output:
            mode (string) : 'continuous', 'gated', 'square', 'free_run', 'triggered',
                            'doublet', 'adjustable_doublet', 'gated_train' or 'pulse_train'
        '''
        logging.debug(__name__ + ' : get mode')

        if not self._to_bool(self._instrument.query(":PULM:STAT?")):
            return 'continuous'

        source = self._instrument.query(":PULM:SOUR?").strip().upper()
        if source.startswith('EXT'):
            return 'gated'

        internal = self._instrument.query(":PULM:SOUR:INT?").strip().upper()
        for mode, scpi in self._INTERNAL_MODES.items():
            short = ''.join(c for c in scpi if c.isupper())          # e.g. 'ADOublet' -> 'ADO'
            if internal.startswith(short):
                return mode
        raise RuntimeError(f"get_mode(): Unexpected internal pulse source '{internal}'")

    def do_set_mode(self, mode):
        '''
        Mode for pulse modulation (see class documentation).

        'continuous' switches the pulse modulation off: the RF is on all the time.
        All other modes switch the pulse modulation and the general modulation switch on.
        The polarity of the PULSE input is not changed, set it with set_pulse_polarity().

        Input:
            mode (string) : 'continuous', 'gated', 'square', 'free_run', 'triggered',
                            'doublet', 'adjustable_doublet', 'gated_train' or 'pulse_train'
        '''
        logging.debug(__name__ + ' : set mode to %s' % mode)

        if mode == 'continuous':
            self._instrument.write(":PULM:STAT OFF")   # Disable pulse modulation
        elif mode == 'gated':
            self._instrument.write(":PULM:SOUR EXT")   # RF follows the PULSE input
            self._instrument.write(":OUTP:MOD ON")
            self._instrument.write(":PULM:STAT ON")
        elif mode in self._INTERNAL_MODES:
            self._instrument.write(":PULM:SOUR INT")
            self._instrument.write(":PULM:SOUR:INT " + self._INTERNAL_MODES[mode])
            self._instrument.write(":OUTP:MOD ON")
            self._instrument.write(":PULM:STAT ON")
        else:
            raise ValueError("set_mode(): mode must be 'continuous', 'gated' or one of "
                             + str(list(self._INTERNAL_MODES)))
        self._instrument.query("*OPC?")                # wait until the instrument has settled
        self._raise_on_error(f"set_mode('{mode}')")

        # read back
        actual = self.do_get_mode()
        if actual != mode:
            raise RuntimeError(f"set_mode('{mode}'): the instrument reports mode '{actual}'")
        if mode != 'continuous' and not self.do_get_modulation():
            raise RuntimeError(f"set_mode('{mode}'): the general modulation switch is still off")

    def _get_polarity(self, command):
        answer = self._instrument.query(command).strip().upper()
        return 'inverted' if answer.startswith('INV') else 'normal'

    def _set_polarity(self, command, polarity, name):
        if polarity not in self._POLARITIES:
            raise ValueError(f"{name}(): polarity must be 'normal' or 'inverted'")
        self._instrument.write(command + " " + self._POLARITIES[polarity])

    def do_get_pulse_polarity(self):
        '''
        Reads the polarity of the external PULSE input.

        Output:
            polarity (string) : 'normal' (responds to TTL high) or 'inverted' (responds to TTL low)
        '''
        logging.debug(__name__ + ' : get pulse polarity')
        return self._get_polarity(":PULM:EXT:POL?")

    def do_set_pulse_polarity(self, polarity):
        '''
        Set the polarity of the external PULSE input.

        Input:
            polarity (string) : 'normal' (responds to TTL high) or 'inverted' (responds to TTL low)
        '''
        logging.debug(__name__ + ' : set pulse polarity to %s' % polarity)
        self._set_polarity(":PULM:EXT:POL", polarity, 'set_pulse_polarity')
        self._raise_on_error(f"set_pulse_polarity('{polarity}')")
        actual = self.do_get_pulse_polarity()
        if actual != polarity:
            raise RuntimeError(f"set_pulse_polarity('{polarity}'): the instrument reports '{actual}'")

    def do_get_video_polarity(self):
        '''
        Reads the polarity of the pulse video signal at the trigger output.

        Output:
            polarity (string) : 'normal' or 'inverted'
        '''
        logging.debug(__name__ + ' : get video polarity')
        return self._get_polarity(":PULM:INT:VID:POL?")

    def do_set_video_polarity(self, polarity):
        '''
        Set the polarity of the pulse video signal at the trigger output.

        Input:
            polarity (string) : 'normal' or 'inverted'
        '''
        logging.debug(__name__ + ' : set video polarity to %s' % polarity)
        self._set_polarity(":PULM:INT:VID:POL", polarity, 'set_video_polarity')

    def do_get_pulse_width(self):
        '''
        Reads the width of the internal pulse (first pulse of the doublets) in s.
        '''
        return float(self._instrument.query(":PULM:INT:PWID1?"))

    def do_set_pulse_width(self, width):
        '''
        Set the width of the internal pulse (first pulse of the doublets).
        Has to be shorter than the pulse period.

        Input:
            width (float) : width in s (20 ns to pulse period - 10 ns)
        '''
        self._instrument.write(f":PULM:INT:PWID1 {float(width)!r} S")
        self._raise_on_error("set_pulse_width()")

    def do_get_pulse_delay(self):
        '''
        Reads the delay of the internal pulse (first pulse of the doublets) in s.
        '''
        return float(self._instrument.query(":PULM:INT:DEL1?"))

    def do_set_pulse_delay(self, delay):
        '''
        Set the delay of the internal pulse (first pulse of the doublets).

        Input:
            delay (float) : delay in s
        '''
        self._instrument.write(f":PULM:INT:DEL1 {float(delay)!r} S")
        self._raise_on_error("set_pulse_delay()")

    def do_get_pulse_width2(self):
        '''
        Reads the width of the second pulse of 'adjustable_doublet' in s.
        '''
        return float(self._instrument.query(":PULM:INT:PWID2?"))

    def do_set_pulse_width2(self, width):
        '''
        Set the width of the second pulse of 'adjustable_doublet'.

        Input:
            width (float) : width in s
        '''
        self._instrument.write(f":PULM:INT:PWID2 {float(width)!r} S")
        self._raise_on_error("set_pulse_width2()")

    def do_get_pulse_delay2(self):
        '''
        Reads the delay of the second pulse of 'adjustable_doublet' in s.
        '''
        return float(self._instrument.query(":PULM:INT:DEL2?"))

    def do_set_pulse_delay2(self, delay):
        '''
        Set the delay of the second pulse of 'adjustable_doublet' (timed from the first pulse).

        Input:
            delay (float) : delay in s
        '''
        self._instrument.write(f":PULM:INT:DEL2 {float(delay)!r} S")
        self._raise_on_error("set_pulse_delay2()")

    def do_get_pulse_period(self):
        '''
        Reads the period of the internal pulse train in s.
        '''
        return float(self._instrument.query(":PULM:INT:PER?"))

    def do_set_pulse_period(self, period):
        '''
        Set the period of the internal pulse train ('free_run', 'gated_train').

        Input:
            period (float) : period in s (30 ns to 42 s)
        '''
        self._instrument.write(f":PULM:INT:PER {float(period)!r} S")
        self._raise_on_error("set_pulse_period()")

    def do_get_pulse_frequency(self):
        '''
        Reads the rate of the internal square wave in Hz.
        '''
        return float(self._instrument.query(":PULM:INT:FREQ?"))

    def do_set_pulse_frequency(self, frequency):
        '''
        Set the rate of the internal square wave ('square').

        Input:
            frequency (float) : rate in Hz (0.1 Hz to 10 MHz)
        '''
        self._instrument.write(f":PULM:INT:FREQ {float(frequency)!r} HZ")
        self._raise_on_error("set_pulse_frequency()")

    ## shortcuts
    def off(self):
        '''
        Set status to 'off'
        '''
        self.set_status(False)

    def on(self, force=False):
        '''
        Set status to 'on'.
        Prints mode and polarity. Refuses to switch on in 'continuous' mode (RF on all the time)
        unless allow_cw is set or force=True.

        Input:
            force (bool) : switch on in 'continuous' mode anyway, default=False
        '''
        mode = self.do_get_mode()
        if mode == 'continuous' and not (self._allow_cw or force):
            raise RuntimeError("on(): pulse modulation is off, the RF would be on all the time (CW). "
                               "Use set_mode('gated'), or on(force=True) / set_allow_cw(True) if CW is intended.")
        if mode == 'gated':
            print(f"RF on: gated, polarity {self.do_get_pulse_polarity()}, {self.do_get_power()} dBm, "
                  f"{self.do_get_frequency()/1e9:.9f} GHz")
        else:
            print(f"RF on: mode {mode}, {self.do_get_power()} dBm, {self.do_get_frequency()/1e9:.9f} GHz")
        self.set_status(True)


if __name__ == "__main__":
    # Example for a sequence
    qkit.start()

    # Initialize the instrument
    kira = qkit.instruments.create('kira', 'Keysight_N5183B', address='192.168.0.42')

    # Set frequency and power of the RF Generator
    kira.set_frequency(10e6)
    kira.set_power(0)

    # Get frequency and power of the RF Generator
    kira.get_power()
    kira.get_frequency()

    # Gated by an external signal at the PULSE input (on the back of the device):
    # the RF is on while the input is high. The delay from the input to the RF is around 100 ns.
    kira.set_pulse_polarity('normal')
    kira.set_mode('gated')

    # Internal pulse generator: one 10 us pulse, 1 us after every trigger at the PULSE input
    #kira.set_pulse_width(10e-6)
    #kira.set_pulse_delay(1e-6)
    #kira.set_mode('triggered')

    # Show all pulse settings and the error queue
    kira.get_pulse_settings()
    print(kira.get_error())

    # Safety: largest allowed power
    kira.set_max_power(0)

    # Turn the RF Generator on and off
    kira.on()
    kira.off()

    # Close the connection
    #kira.close()

    # Back to a continuous signal
    #kira.set_mode('continuous')