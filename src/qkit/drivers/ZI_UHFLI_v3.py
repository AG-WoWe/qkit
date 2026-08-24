# -*- coding: utf-8 -*-
"""
Created on Fri Juli 2026

@author: nanospin
"""

# ZI_UHFLI_v3.py

# import zhinst.toolkit
import time
from qkit.core.instrument_base import Instrument
from zhinst.toolkit import Session
import logging
import numpy as np

logger = logging.getLogger(__name__)

class ZI_UHFLI_v3(Instrument):
    #     name (string)    : name of the instrument   ("UHFLI")
    #     device_id : serial number of the instrument ("dev2587")
    def __init__(self, name, device_id, host="localhost", step_recovery = "0.9", settling_time = 0.0):
        super().__init__(name, tags=["physical", "Lock-in Amplifier"])

        self._device_id = device_id
        
        #Create an apisession, to be able to control the device from python.
        # -------- zhinst-toolkit ----------
        self._session = Session(host)
        self._device = self._session.connect_device(device_id)

        #logging.info(f"{__name__}: Connected to {device_id}")
        logger.info(f"{__name__}: Connected to {device_id}")
        
        # Add software parameters for convenience
        # ================= PARAMETERS =================

        self._filter_settling_factors = {
            r"0.632" : 	[1.0, 2.15, 3.26, 4.35, 5.43, 6.51, 7.58, 8.64],
            r"0.9" :	[2.3, 3.89, 5.32, 6.68, 7.99, 9.27, 10.53, 11.77],
            r"0.99" : 	[4.61, 6.64, 8.41, 10.05, 11.6, 13.11, 14.57, 16],
            r"0.999":	[6,91, 9.23, 11.23, 13.06, 14.79, 16.45, 18.06, 19.62]
            }

        self._bw_factors = [0.2500, 0.1250, 0.0937, 0.0781, 0.0684, 0.0615, 0.0615, 0.0564, 0.0524]
        self._max_sampling_rate = 1.758 * 1e6 # This is not a device but network limit. Check if data is lost when using higher transfer rates.
        self._step_recovery = step_recovery
        self._settling_time = settling_time

        # Add Instrument parameters for qkit compatibility
        # ================= PARAMETERS =================

        # INPUTS
        self.add_parameter("input_range", type=float,
                           flags=self.FLAG_GETSET,
                           channels=(0, 1), channel_prefix="ch%d_",
                           minval = 10e-3, maxval = 1.5,
                           units="V")
        
        self.add_parameter("input_scaling", type = float,
                           flags = self.FLAG_GETSET,
                           channels = (0, 1), channel_prefix = "ch%d_",
                           minval = 1e-12, maxval = 1e12)


        self.add_parameter("input_50ohm", type=bool,
                           flags=self.FLAG_GETSET,
                           channels=(0, 1), channel_prefix="ch%d_")

        # OSCILLATORS
        self.add_parameter("carrier_freq", type=float,
                           flags = self.FLAG_GETSET,
                           channels = (0, 1), channel_prefix="ch%d_",
                           minval = 0, maxval = 600e6,
                           units="Hz",  tags = ["sweep"])

        # DEMODS
        self.add_parameter("demod_harmonic", type = int,
                           flags = self.FLAG_GETSET,
                           channels = (0, 7), channel_prefix = "dem%d_",
                           minval = 1, maxval = 1023)
        
        self.add_parameter("filter_order", type=int,
                           flags = self.FLAG_GETSET,
                           channels = (0, 7), channel_prefix="dem%d_",
                           minval = 1, maxval = 8)
        
        self.add_parameter("filter_timeconst", type=float,
                           flags = self.FLAG_GETSET,
                           channels = (0, 7), channel_prefix="dem%d_",
                           minval = 102.6e-9, maxval = 76.35,
                           units = "s", tags = ["sweep"])

        self.add_parameter("demod_enable", type=bool,
                           flags=self.FLAG_GETSET,
                           channels=(0, 7), channel_prefix="dem%d_")

        self.add_parameter("sample_rate", type=float,
                           flags=self.FLAG_GETSET,
                           channels=(0, 7), channel_prefix="dem%d_",
                           minval = 1.676, maxval = 14.06e6, 
                           units = "Hz", tags = ["sweep"])

        # OUTPUTS
        self.add_parameter("output", type=bool,
                           flags=self.FLAG_GETSET,
                           channels=(0, 1), channel_prefix="ch%d_")
        
        self.add_parameter("output_50ohm", type = bool,
                           flags = self.FLAG_GET,
                           channels = (0, 1), channel_prefix = "ch%d_")
        
        self.add_parameter("output_range", type = float,
                           flags = self.FLAG_GET,
                           channels = (0, 1), channel_prefix = "ch%d_",
                           minval = 75e-3, maxval = 1.5,
                           units = "V")
        
        self.add_parameter("output_amplitude", type = float,
                           flags = self.FLAG_GET,
                           channels = (0, 1), channel_prefix = "ch%d_",
                           minval = -1.5, maxval = 1.5,
                           units = "V")

        # SOFTWARE
        self.add_parameter("step_recovery",  type=str,
                            flags=self.FLAG_GETSET,
                            options=("0.632", "0.9", "0.99", "0.999"))


        # ================= PUBLIC FUNCTIONS =================
        self.add_function("disable_everything")
        self.add_function("set_output_amplitude")
        self.add_function("calc_timeconst")
        self.add_function("calc_settling_time")
        self.add_function("set_sampling_rate")
        self.add_function("sample_dem")

    def disable_everything(self):
        # Disable all demodulators
        for d in range(8):
            self._device.demods[d].enable(0)

        # Disable all signal outputs
        self._device.sigouts[0].on(0)
        self._device.sigouts[1].on(0)

        # Remove all subscriptions
        self._session.unsubscribe()

    def set_output_amplitude(self, channel, amplitude, matched=True):
        if channel not in (0, 1):
            raise ValueError(f"Invalid output channel {channel}")

        if amplitude <= 0:
            raise ValueError(f"Amplitude must be positive, got {amplitude} V")

        # Configure output impedance and allowed range
        if matched:
            self._device.sigouts[channel].imp50(True)
            max_amp = 750e-3
            ranges = [75e-3, 750e-3]
        else:
            self._device.sigouts[channel].imp50(False)
            max_amp = 1.5
            ranges = [150e-3, 1.5]

        if amplitude > max_amp:
            raise ValueError(
                f"Amplitude {amplitude} V exceeds maximum {max_amp} V"
            )

        # Select the smallest suitable output range
        for r in ranges:
            if amplitude <= r:
                self._device.sigouts[channel].range(r)
                break

        # Enable variable output and set amplitude
        self._device.sigouts[channel].enables[3 + 4*channel](True)
        self._device.sigouts[channel].amplitudes[3 + 4*channel](amplitude)

    def calc_timeconst(self, wait_time, filter_order = 1):
        """
        Calculate the demodulator time constant for a desired record time.

        Parameters
        ----------
        wait_time : float
            Time available befor one measurement point [s].

        filter_order : int
            Demodulator filter order (1...8).

        settling : str
            Settling criterion: "0.632", "0.9", "0.99", or "0.999".

        Returns
        -------
        float
            Required filter time constant tau [s].
        """
        if not 1 <= filter_order <= 8:
            raise ValueError("filter_order must be between 1 and 8.")
        try:
            factor = self._filter_settling_factors[self._step_recovery][filter_order - 1]
        except KeyError:
            raise ValueError(
                f"Invalid settling criterion '{settling}'. "
                f"Choose from {list(self._filter_settling_factors.keys())}."
            )

        return wait_time / factor

    def set_sampling_rate(self, demod = 0, oversampling = 10):
        """
        Set the demodulator sampling rate to a multiple of the bandwidth.

        Parameters
        ----------
        demod : int
            Demodulator index.

        oversampling : float
            Sampling rate as a multiple of the bandwidth.
            Default is 10.
        """
        newrate = oversampling * self._bw_factors[demod] / self._device.demods[demod].timeconstant()

        if newrate > self._max_sampling_rate:
            raise ValueError(
                f"Calculated sampling rate ({newrate:.3e} Hz) exceeds the "
                f"maximum network transfer rate ({self._max_sampling_rate:.3e} Hz). "
            )
        self._device.demods[demod].rate(newrate)
    
    def calc_settling_time(self, demod_index):
        step_recovery = self._step_recovery
        tc = float(self._device.demods[demod_index].timeconstant())
        order = int(self._device.demods[demod_index].order())
        self._settling_time = tc * self._filter_settling_factors[step_recovery][order - 1]
        
    def sample_dem(self, channel, wait_settling_time = True):
        """
        Take one demodulator sample.

        Returns
        -------
        dict[str, float]
            Dictionary containing demod data with timestamp converted to seconds.
        """
        if not bool(self._device.demods[channel].enable()):
            raise RuntimeError(f"Data transfer of demodulator {channel} is not enabled.")

        if wait_settling_time:
            time.sleep(self._settling_time)
        raw = self._device.demods[channel].sample()
        out = {}

        for key, value in raw.items():
            # Convert numpy arrays to single values
            if hasattr(value, "__len__"):
                value = value[-1]

            # Convert timestamp from ticks to seconds
            if key == "timestamp":
                value = float(value) * self._device.system.properties.timebase()
                key = "time"
                
            out[key] = float(value)

        # Add magnitude r from x and y
        if "x" in out and "y" in out:
            out["r"] = float(np.hypot(out["x"], out["y"]))

        return out

    # ================= INPUT =================
    def _do_set_input_range(self, newrange, channel):
        logging.debug("%s: setting input range on channel %d to %.3g V",__name__, channel, newrange)
        self._device.sigins[channel].range(newrange)

    def _do_get_input_range(self, channel):
        logging.debug(__name__ + ' : getting range on input channel %s' % channel)
        return float(self._device.sigins[channel].range())
    
    def _do_set_input_scaling(self, newscale, channel):
        logging.debug(__name__ + ' : setting input scaling on channel %d to %.3g"', channel, newscale)
        self._device.sigins[channel].scaling(newscale)
    
    def _do_get_input_scaling(self, channel):
        logging.debug(__name__ + ' : getting scaling on input channel %s' % channel)
        return round(float(self._device.sigins[channel].scaling()), 3)
    
    def _do_set_input_50ohm(self, onoff, channel):
        mode = "50ohm" if onoff else "1Mohm"
        logging.debug(__name__ + ' : setting impedance on input channel %d to %s', channel, mode)
        self._device.sigins[channel].imp50(int(bool(onoff)))

    def _do_get_input_50ohm(self, channel):
        logging.debug(__name__ + ' : getting the impedance of input channel %s' % channel)
        return bool(self._device.sigins[channel].imp50())
    
    def _do_set_input_autorange(self, onoff, channel):
        state = "ON" if onoff else "OFF"
        logging.debug(__name__ + " : setting input autorange on channel %d to %s", channel, state)
        self._device.sigins[channel].autorange(int(bool(onoff)))

    def _do_get_input_autorange(self, channel):
        logging.debug("%s: getting input autorange state on channel %d",__name__, channel)
        return bool(self._device.sigins[channel].autorange())

    # ================= OSC =================
    def _do_set_carrier_freq(self, newfreq, channel):
        logging.debug(__name__ + ' : setting carrier frequency on channel %s to %s Hz',  channel, newfreq)
        self._device.oscs[channel].freq(newfreq)

    def _do_get_carrier_freq(self, channel):
        logging.debug(__name__ + ' : getting carrier frequency on channel %s' % channel)
        return float(self._device.oscs[channel].freq())

    # ================= DEMODS =================
    def _do_set_demod_harmonic(self, newharmonic,channel):
        logging.debug(__name__ + " : setting harmonic on demodulator %s to %s" ,channel, newharmonic)
        self._device.demods[channel].harmonic(newharmonic)
        
    def _do_get_demod_harmonic(self, channel):
        logging.debug(__name__ + ' : getting harmonic on demodulator %s' % channel)
        return int(self._device.demods[channel].harmonic())
    
    def _do_set_filter_order(self, neworder, channel):
        logging.debug(__name__ + " : setting filter order on demodulator %s to %s" ,channel, neworder)
        self._device.demods[channel].order(neworder)

    def _do_get_filter_order(self, channel):
        logging.debug(__name__ + ' : getting filter order on demodulator %s' % channel)
        return int(self._device.demods[channel].order())
    
    def _do_set_filter_timeconst(self, newtc, channel):
        logging.debug(__name__ + " : setting filter time constant on demodulator %s to %s s" ,channel, newtc)
        self._device.demods[channel].timeconstant(newtc)

    def _do_get_filter_timeconst(self, channel):
        logging.debug(__name__ + ' : getting filter timeconstant on demodulator %s' % channel)
        return float(self._device.demods[channel].timeconstant())
    
    def _do_set_demod_enable(self, onoff, channel):
        mode = "activating" if onoff else "deactivating"
        logging.debug(__name__ + ' : %s demodulator %s' ,mode, channel)
        self._device.demods[channel].enable(int(bool(onoff)))

    def _do_get_demod_enable(self, channel):
        logging.debug(__name__ + ' : getting status of demodulator %s' % channel)
        return bool(self._device.demods[channel].enable())

    def _do_set_sample_rate(self, newrate, channel):
        logging.debug(__name__ + " : setting sample rate on demodulator %s to %s s" ,channel, newrate)
        self._device.demods[channel].rate(newrate)

    def _do_get_sample_rate(self, channel):
        logging.debug(__name__ + ' : getting sample rate on demodulator %s' % channel)
        return float(self._device.demods[channel].rate())

    # ================= OUTPUT =================
    def _do_set_output(self, onoff, channel):
        mode = "activating" if onoff else "deaktivating"
        logging.debug(__name__ + ' : %s output channel %s', mode, channel)
        self._device.sigouts[channel].on(int(bool(onoff)))

    def _do_get_output(self, channel):
        logging.debug(__name__ + ' : getting status of output channel %s' % channel)
        return bool(self._device.sigouts[channel].on())

    def _do_get_output_50ohm(self, channel):
        logging.debug("%s: getting expected load impedance of output channel %d",__name__, channel)
        return bool(self._device.sigouts[channel].imp50())

    def _do_get_output_range(self, channel):
        logging.debug("%s: getting output range on channel %d",__name__, channel)
        return float(self._device.sigouts[channel].range())

    def _do_get_output_amplitude(self, channel):
        logging.debug("%s: getting output amplitude on channel %d",__name__, channel)
        return float(self._device.sigouts[channel].amplitudes[3 + 4 * channel]())
    
    def _do_set_output_amp_enable(self, onoff, channel):
        mode = "activating" if onoff else "deactivating"
        logging.debug(__name__ + ' : %s amplitude on output channel %s' ,mode, channel)
        self._device.sigouts[channel].on(int(bool(onoff)))
        #self._device.sigouts[channel].on[3 +4 * channel](int(bool(onoff)))
        
    def _do_get_output_amp_enable(self, channel):
        logging.debug(__name__ + ' : getting amplitude status on output channel %s' % channel)
        #return bool(self._device.sigouts[channel].on[3 + 4 * channel]())
        return bool(self._device.sigouts[channel].on())

    # ================= SOFTWARE =================
    def _do_set_step_recovery(self, value):
        logging.debug(__name__ + ' : setting step recovery to %s' % value)
        allowed_values = ('0.632', '0.9', '0.99', '0.999')
        if str(value) not in allowed_values:
            raise ValueError(
                "Invalid step recovery value %s. Allowed values are %s"
                % (value, allowed_values)
            )
        self._step_recovery = str(value)

    def _do_get_step_recovery(self):
        logging.debug(__name__ + ' : getting step recovery value')
        return self._step_recovery
  
#=======================================================================================================
if __name__ == "__main__":
    import qkit
    qkit.start()    
    
    UHFLI_test = qkit.instruments.create("UHFLI_test", "ZI_UHFLI_v2", device_id = "dev2587")
    
