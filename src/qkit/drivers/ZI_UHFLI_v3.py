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

        logger.info(f"Connected to {device_id}")
        
        # Add software parameters for convenience
        # ================= PARAMETERS =================

        self._filter_settling_factors = {
            r"0.632" : 	[1.0, 2.15, 3.26, 4.35, 5.43, 6.51, 7.58, 8.64],
            r"0.9" :	[2.3, 3.89, 5.32, 6.68, 7.99, 9.27, 10.53, 11.77],
            r"0.99" : 	[4.61, 6.64, 8.41, 10.05, 11.6, 13.11, 14.57, 16],
            r"0.999":	[6.91, 9.23, 11.23, 13.06, 14.79, 16.45, 18.06, 19.62]
            }
                           
        self._bw_factors = [0.2500, 0.1250, 0.0937, 0.0781, 0.0684, 0.0615, 0.0564, 0.0524]
        # Upper limit for set_sampling_rate() (gated readout); the 100 kHz limit for continuous
        # streaming lives in ZI_UHFLI_DAQ (MAX_CONTINUOUS_RATE).
        self._max_sampling_rate = 1.758 * 1e6
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
                           minval = 2.9900000697580253e-08, maxval = 76.35,
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
        self.add_function("set_filter_settling")
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

    def calc_timeconst(self, wait_time, demod_index):
        """
        Calculate the demodulator time constant for a desired settling time.

        Uses the current filter order of the demodulator and the step recovery
        criterion (set_step_recovery: "0.632", "0.9", "0.99" or "0.999").

        Parameters
        ----------
        wait_time : float
            Time within which a step should settle to the step recovery level [s].
        demod_index : int
            Demodulator index (0...7).

        Returns
        -------
        float
            Required filter time constant tau [s].
        """
        if not 0 <= demod_index <= 7:
            raise ValueError("demodulator index must be between 0 and 7.")
        try:
            order = int(self._device.demods[demod_index].order())
            factor = self._filter_settling_factors[self._step_recovery][order-1]
        except KeyError:
            raise ValueError(
                f"Invalid settling criterion '{self._step_recovery}'. "
                f"Choose from {list(self._filter_settling_factors.keys())}."
            )

        return wait_time / factor

    def set_sampling_rate(self, demod = 0, oversampling = 10):
        """
        Set the demodulator sampling rate to a multiple of the filter bandwidth.

        demod : int
            Demodulator index.
        oversampling : float
            Sampling rate as a multiple of the bandwidth. Default is 10.
        """
        order = int(self._device.demods[demod].order())
        tc = float(self._device.demods[demod].timeconstant())
        newrate = oversampling * self._bw_factors[order - 1] / tc

        if newrate > self._max_sampling_rate:
            logger.warning(
                f"Calculated sampling rate ({newrate:.3e} Hz) exceeds the "
                f"maximum network transfer rate ({self._max_sampling_rate:.3e} Hz). "
                f"Using the maximum instead."
            )
            newrate = self._max_sampling_rate
        self._device.demods[demod].rate(newrate)
    
    def calc_settling_time(self, demod_index):
        step_recovery = self._step_recovery
        tc = float(self._device.demods[demod_index].timeconstant())
        order = int(self._device.demods[demod_index].order())
        self._settling_time = tc * self._filter_settling_factors[step_recovery][order - 1]
      
    def set_filter_settling(self, demod, settling_time, step_recovery=None, order=None):
        """
        Set the demodulator filter so that a step settles within settling_time.

        demod : int
            Demodulator index (0...7).
        settling_time : float
            Time within which a step reaches the step recovery level [s].
        step_recovery : str, optional
            "0.632", "0.9", "0.99" or "0.999". Keeps the current value if None.
        order : int, optional
            Filter order 1...8. Keeps the current order if None.

        Returns the time constant actually set by the device [s].
        """
        if step_recovery is not None:
            self._do_set_step_recovery(step_recovery)
        if order is not None:
            self._device.demods[demod].order(order)          # before calc_timeconst: it reads the order
        tc = self.calc_timeconst(settling_time, demod)
        self._device.demods[demod].timeconstant(tc)          # the device rounds to an allowed value
        self.calc_settling_time(demod)                       # from the actual time constant
        tc_set = float(self._device.demods[demod].timeconstant())
        logger.info(f"demod {demod}: tc {tc_set*1e6:.2f} us, "
                    f"settling ({self._step_recovery}) {self._settling_time*1e6:.2f} us")
        return tc_set
      
    def sample_dem(self, channel, wait_settling_time = True, output = 0):
        """
        Take one demodulator sample.

        Parameters
        ----------
        channel : int
            Demodulator index (0...7).
        wait_settling_time : bool
            Wait the filter settling time before sampling.
        output : int
            Signal output (0 or 1) whose amplitude r is normalised to. Default 0.

        Returns
        -------
        dict[str, float]
            timestamp [s], x, y [V], r (normalised to the output amplitude),
            phase [rad]: phase of the measured signal, atan2(y, x), as theta in LabOne.
        """
        if output not in (0, 1):
            raise ValueError(f"Invalid output channel {output}")
        if not bool(self._device.demods[channel].enable()):
            raise RuntimeError(f"Data transfer of demodulator {channel} is not enabled.")

        if wait_settling_time:
            time.sleep(self._settling_time)

        raw = self._device.demods[channel].sample()

        x = float(raw["x"][-1])
        y = float(raw["y"][-1])
        return {
            "timestamp": float(raw["timestamp"][-1]) * self._device.system.properties.timebase(),
            "x": x,
            "y": y,
            # raw["phase"] is the oscillator (reference) phase, not the signal phase
            "phase": float(np.arctan2(y, x)),
            "r": float(np.hypot(x, y) / self._do_get_output_amplitude(output) * np.sqrt(2)),
        }

    # ================= INPUT =================
    def _do_set_input_range(self, newrange, channel):
        logger.debug("setting input range on channel %d to %.3g V", channel, newrange)
        self._device.sigins[channel].range(newrange)

    def _do_get_input_range(self, channel):
        logger.debug("getting range on input channel %s", channel)
        return float(self._device.sigins[channel].range())
    
    def _do_set_input_scaling(self, newscale, channel):
        logger.debug("setting input scaling on channel %d to %.3g", channel, newscale)
        self._device.sigins[channel].scaling(newscale)
    
    def _do_get_input_scaling(self, channel):
        logger.debug("getting scaling on input channel %s", channel)
        return round(float(self._device.sigins[channel].scaling()), 3)
    
    def _do_set_input_50ohm(self, onoff, channel):
        mode = "50ohm" if onoff else "1Mohm"
        logger.debug("setting impedance on input channel %d to %s", channel, mode)
        self._device.sigins[channel].imp50(int(bool(onoff)))

    def _do_get_input_50ohm(self, channel):
        logger.debug("getting the impedance of input channel %s", channel)
        return bool(self._device.sigins[channel].imp50())
    
    def _do_set_input_autorange(self, onoff, channel):
        state = "ON" if onoff else "OFF"
        logger.debug("setting input autorange on channel %d to %s", channel, state)
        self._device.sigins[channel].autorange(int(bool(onoff)))

    def _do_get_input_autorange(self, channel):
        logger.debug("getting input autorange state on channel %d", channel)
        return bool(self._device.sigins[channel].autorange())

    # ================= OSC =================
    def _do_set_carrier_freq(self, newfreq, channel):
        logger.debug("setting carrier frequency on channel %s to %s Hz", channel, newfreq)
        self._device.oscs[channel].freq(newfreq)

    def _do_get_carrier_freq(self, channel):
        logger.debug("getting carrier frequency on channel %s", channel)
        return float(self._device.oscs[channel].freq())

    # ================= DEMODS =================
    def _do_set_demod_harmonic(self, newharmonic,channel):
        logger.debug("setting harmonic on demodulator %s to %s", channel, newharmonic)
        self._device.demods[channel].harmonic(newharmonic)
        
    def _do_get_demod_harmonic(self, channel):
        logger.debug("getting harmonic on demodulator %s", channel)
        return int(self._device.demods[channel].harmonic())
    
    def _do_set_filter_order(self, neworder, channel):
        logger.debug("setting filter order on demodulator %s to %s", channel, neworder)
        self._device.demods[channel].order(neworder)

    def _do_get_filter_order(self, channel):
        logger.debug("getting filter order on demodulator %s", channel)
        return int(self._device.demods[channel].order())
    
    def _do_set_filter_timeconst(self, newtc, channel):
        logger.debug("setting filter time constant on demodulator %s to %s s", channel, newtc)
        self._device.demods[channel].timeconstant(newtc)

    def _do_get_filter_timeconst(self, channel):
        logger.debug("getting filter timeconstant on demodulator %s", channel)
        return float(self._device.demods[channel].timeconstant())
    
    def _do_set_demod_enable(self, onoff, channel):
        mode = "activating" if onoff else "deactivating"
        logger.debug("%s demodulator %s", mode, channel)
        self._device.demods[channel].enable(int(bool(onoff)))

    def _do_get_demod_enable(self, channel):
        logger.debug("getting status of demodulator %s", channel)
        return bool(self._device.demods[channel].enable())

    def _do_set_sample_rate(self, newrate, channel):
        logger.debug("setting sample rate on demodulator %s to %s Hz", channel, newrate)
        self._device.demods[channel].rate(newrate)

    def _do_get_sample_rate(self, channel):
        logger.debug("getting sample rate on demodulator %s", channel)
        return float(self._device.demods[channel].rate())

    # ================= OUTPUT =================
    def _do_set_output(self, onoff, channel):
        mode = "activating" if onoff else "deactivating"
        logger.debug("%s output channel %s", mode, channel)
        self._device.sigouts[channel].on(int(bool(onoff)))

    def _do_get_output(self, channel):
        logger.debug("getting status of output channel %s", channel)
        return bool(self._device.sigouts[channel].on())

    def _do_get_output_50ohm(self, channel):
        logger.debug("getting expected load impedance of output channel %d", channel)
        return bool(self._device.sigouts[channel].imp50())

    def _do_get_output_range(self, channel):
        logger.debug("getting output range on channel %d", channel)
        return float(self._device.sigouts[channel].range())

    def _do_get_output_amplitude(self, channel):
        logger.debug("getting output amplitude on channel %d", channel)
        return float(self._device.sigouts[channel].amplitudes[3 + 4 * channel]())


    # ================= SOFTWARE =================
    def _do_set_step_recovery(self, value):
        logger.debug("setting step recovery to %s", value)
        allowed_values = ('0.632', '0.9', '0.99', '0.999')
        if str(value) not in allowed_values:
            raise ValueError(
                "Invalid step recovery value %s. Allowed values are %s"
                % (value, allowed_values)
            )
        self._step_recovery = str(value)

    def _do_get_step_recovery(self):
        logger.debug("getting step recovery value")
        return self._step_recovery
  
#=======================================================================================================
if __name__ == "__main__":
    import qkit
    qkit.start()    
    
    UHFLI_test = qkit.instruments.create("UHFLI_test", "ZI_UHFLI_v3", device_id = "dev2587")