# -*- coding: utf-8 -*-
"""
Created on Fri Jan  9 10:53:26 2026

@author: nanospin
"""

# ZI_UHFLI_v2.py
from qkit.core.instrument_base import Instrument
import zhinst.toolkit
from zhinst.toolkit import Session
import numpy as np
import time
import logging

logger = logging.getLogger(__name__)

class ZI_UHFLI_v2(Instrument):
    
    #     name (string)    : name of the instrument   ("UHFLI")
    #     device_id : serial number of the instrument ("dev2587")
    def __init__(self, name, device_id, host="localhost"):
        super().__init__(name, tags=["physical", "lock-in amplifier"])
        self._device_id = device_id
        
        # trigger mode in numers
        self._trigger_mode_dict = {"continuous" : 0,
                                   "in3_rising" : 1,
                                   "in3_falling" : 2,
                                   "in3_both" : 3,
                                   "in3_hi" : 32,
                                   "in3_lo" : 16,
                                   "in4_rising" : 4,
                                   "in4_falling" : 8,
                                   "in4_both" : 12,
                                   "in4_hi" : 128,
                                   "in4_lo" : 64,
                                   "in3|4_rising" : 5,
                                   "in3|4_falling" : 10,
                                   "in3|4_both" : 15,
                                   "in3|4_hi" : 160,
                                   "in3|4_lo" : 80}
        self._inv_trigger_mode_dict = {v: k for k, v in self._trigger_mode_dict.items()}
        self._difference_mode_dict = {"off" : 0,
                                      "inverted" : 1,
                                      "in1-in2" : 2,
                                      "in2-in1" : 3}
                                      
        # setteling times in units of time constant from selected Filter
        self._filter_settling_factors = {r"63.2%" : [1.0, 2.15, 3.26, 4.35, 
                                                   5.43, 6.51, 7.58, 8.64],
                                         r"90%" : [2.3, 3.89, 5.32, 6.68, 
                                                   7.99, 9.27, 10.53, 11.77],
                                         r"99%" : [4.61, 6.64, 8.41, 10.05, 
                                                   11.6, 13.11, 14.57, 16]}
        self._inv_difference_mode_dict = {v: k for k, v in self._difference_mode_dict.items()}
                
        #Set the apilevel to the highest supported by your device, to unlock most of the functionalities.     
        self._apilevel = 6
        self._bad_device_message = "No UHFLI device found."
        
        #Create an apisession, to be able to control the device from python.
        # -------- zhinst-toolkit ----------
        self._session = Session(host)
        self._device = self._session.connect_device(device_id)

        #logging.info(f"{__name__}: Connected to {device_id}")
        logger.info(f"{__name__}: Connected to {device_id}")

        # -------- DAQ ----------
        #self._subscribed_demods = []
        #self.integration_time = 0.05
        #self.timeout = 0.1
        
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

        self.add_parameter("input_ac_coupling", type=bool,
                           flags=self.FLAG_GETSET,
                           channels=(0, 1), channel_prefix="ch%d_")

        self.add_parameter("input_50ohm", type=bool,
                           flags=self.FLAG_GETSET,
                           channels=(0, 1), channel_prefix="ch%d_")
        
        self.add_parameter("input_autorange", type = bool,
                           flags = self.FLAG_GETSET,
                           channels = (0, 1), channel_prefix = "ch%d_")
        
        self.add_parameter("input_difference", type = str,
                           flags = self.FLAG_GETSET,
                           channels = (0, 1), channel_prefix = "ch%d_")

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
        
        self.add_parameter("phase_offs", type = float,
                           flags = self.FLAG_GETSET,
                           channels = (0, 7), channel_prefix = "dem%d_",
                           minval = 0, maxval = 360,
                           units = "deg", tags = ["sweep"])
        
        self.add_parameter("autophase", type = bool,
                           flags = self.FLAG_GETSET,
                           channels = (0, 7), channel_prefix = "dem%d_")
        
        self.add_parameter("filter_order", type=int,
                           flags = self.FLAG_GETSET,
                           channels = (0, 7), channel_prefix="dem%d_",
                           minval = 1, maxval = 8)
        
        self.add_parameter("filter_timeconst", type=float,
                           flags = self.FLAG_GETSET,
                           channels = (0, 7), channel_prefix="dem%d_",
                           minval = 102.6e-9, maxval = 76.35,
                           units = "s", tags = ["sweep"])
        
        self.add_parameter("filter_sinc", type = bool,
                           flags = self.FLAG_GETSET,
                           channels = (0, 7), channel_prefix = "dem%d_")

        self.add_parameter("demod_enable", type=bool,
                           flags=self.FLAG_GETSET,
                           channels=(0, 7), channel_prefix="dem%d_")

        self.add_parameter("sample_rate", type=float,
                           flags=self.FLAG_GETSET,
                           channels=(0, 7), channel_prefix="dem%d_",
                           minval = 1.676, maxval = 14.06e6, 
                           units = "Hz", tags = ["sweep"])
        
        self.add_parameter("trigger_mode", type = str,
                           flags = self.FLAG_GETSET,
                           channels = (0, 7), channel_prefix = "dem%d_")

        
       

        # OUTPUTS
        self.add_parameter("output", type=bool,
                           flags=self.FLAG_GETSET,
                           channels=(0, 1), channel_prefix="ch%d_")
        
        self.add_parameter("output_50ohm", type = bool,
                           flags = self.FLAG_GETSET,
                           channels = (0, 1), channel_prefix = "ch%d_")
        
        self.add_parameter("output_range", type = float,
                           flags = self.FLAG_GETSET,
                           channels = (0, 1), channel_prefix = "ch%d_",
                           minval = 75e-3, maxval = 1.5,
                           units = "V")
        
        self.add_parameter("output_offset", type = float,
                           flags = self.FLAG_GETSET,
                           channels = (0, 1), channel_prefix = "ch%d_",
                           minval = -1.5, maxval = 1.5,
                           units = "V")
        
        self.add_parameter("output_amplitude", type = float,
                           flags = self.FLAG_GETSET,
                           channels = (0, 1), channel_prefix = "ch%d_",
                           minval = -1.5, maxval = 1.5,
                           units = "V")
        
        self.add_parameter("output_autorange", type = bool,
                           flags = self.FLAG_GETSET,
                           channels = (0, 1), channel_prefix = "ch%d_")
                
        self.add_parameter("output_amp_enable", type = bool,
                           flags = self.FLAG_GETSET,
                           channels = (0, 1), channel_prefix = "ch%d_")
        
        #SOFTWARE PARAMETERS
        self.add_parameter("step_recovery", type = str,
                          flags = self.FLAG_SET | self.FLAG_SOFTGET,
                          channels = (0, 7), channel_prefix = "dem%d_")
        
        for demod_index in range(8):
            self.set(f"dem{demod_index}_step_recovery", r"99%")
        self.settling_times = [0] * 8
        self.calc_all_settling_times()


        # ================= PUBLIC FUNCTIONS =================
        self.add_function("disable_everything")
        self.add_function("calc_settling_time")
        self.add_function("wait_settle_time")
        self.add_function("wait_longest_settle_time")
        self.add_function("calc_all_settling_times")
        

    def disable_everything(self):
        # Disable all demodulators
        for d in range(8):
            self._device.demods[d].enable(0)

        # Disable all signal outputs
        for ch in range(2):
            self._device.sigouts[ch].on(0)
            self._device.sigouts

        # Remove all subscriptions
        self._session.unsubscribe("*")
        
    def calc_settling_time(self, demod_index):
        step_recovery = self.get(f"dem{demod_index}_step_recovery")
        tc = float(self._device.demods[demod_index].timeconstant())
        order = int(self._device.demods[demod_index].order())
        value = tc * self._filter_settling_factors[step_recovery][order - 1]
        #print(value)
        return value
        #print(tc * self._filter_settling_factors[step_recovery][order - 1])
        #return tc * self._filter_settling_factors[step_recovery][order - 1]

        
    def wait_settle_time(self, demod_index):
        time.sleep(self.settling_times[demod_index])
        
    def wait_longest_settle_time(self):
        time.sleep(self.longest_settling_time)
        
    def calc_all_settling_times(self):
        for demod_index in range(8):
            self.settling_times[demod_index] = self.calc_settling_time(demod_index)
        self.longest_settling_time = max(self.settling_times)
        
    
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

    def _do_set_input_ac_coupling(self, onoff, channel):
        mode = "AC" if onoff else "DC"
        logging.debug(__name__ + " : setting input coupling on channel %d to %s", channel, mode)
        self._device.sigins[channel].ac(int(bool(onoff)))

    def _do_get_input_ac_coupling(self, channel):
        logging.debug(__name__ + " : getting input coupling on channel %d" % channel)
        return bool(self._device.sigins[channel].ac())
    
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
    
    def _do_set_input_difference(self, newmode, channel):
        logging.debug("%s: setting difference mode on input channel %d to %s",__name__, channel, newmode)
        try:
            self._device.sigins[channel].diff(self._difference_mode_dict[newmode])
        except KeyError:
            logging.warning("Invalid difference mode: %s", newmode)

    def _do_get_input_difference(self, channel):
        logging.debug("%s: getting difference mode on input channel %d",__name__, channel)
        return self._inv_difference_mode_dict[self._device.sigins[channel].diff()]

    
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
    
    def _do_set_phase_offs(self, newoffs, channel):
        logging.debug(__name__ + " : setting phase offset on demodulator %s to %s deg" ,channel, newoffs)
        self._device.demods[channel].phaseshift(newoffs)
    
    def _do_get_phase_offs(self, channel):
        logging.debug(__name__ + ' : getting phase offset on demodulator %s' % channel)
        return round(float(self._device.demods[channel].phaseshift()), 3)    
        
    def _do_set_autophase(self, onoff, channel):
        mode = "activating" if onoff else "deactivating"
        logging.debug(__name__ + ' : %s autophase on input channel %d' ,mode, channel)
        self._device.demods[channel].phaseadjust(int(bool(onoff)))
        
    def _do_get_autophase(self, channel):
        logging.debug(__name__ + ' : getting the autorange status of input channel %s' % channel)
        return bool(self._device.demods[channel].phaseadjust())
    
    def _do_set_filter_order(self, neworder, channel):
        logging.debug(__name__ + " : setting filter order on demodulator %s to %s" ,channel, neworder)
        self._device.demods[channel].order(neworder)
        self.settling_times[channel] = self.calc_settling_time(channel)
        self.longest_settling_time = max(self.settling_times)
        self.wait_settle_time(channel)

    def _do_get_filter_order(self, channel):
        logging.debug(__name__ + ' : getting filter order on demodulator %s' % channel)
        return int(self._device.demods[channel].order())
    
    def _do_set_filter_timeconst(self, newtc, channel):
        logging.debug(__name__ + " : setting filter time constant on demodulator %s to %s s" ,channel, newtc)
        self._device.demods[channel].timeconstant(newtc)
        self.settling_times[channel] = self.calc_settling_time(channel)
        self.longest_settling_time = max(self.settling_times)
        self.wait_settle_time(channel)

    def _do_get_filter_timeconst(self, channel):
        logging.debug(__name__ + ' : getting filter timeconstant on demodulator %s' % channel)
        return float(self._device.demods[channel].timeconstant())
    
    def _do_set_filter_sinc(self, onoff, channel):
        mode = "activating" if onoff else "deactivating"
        logging.debug(__name__ + ' : %s sinc filter on demodulator %s' ,mode,channel)
        self._device.demods[channel].sinc(int(bool(onoff)))
    
    def _do_get_filter_sinc(self, channel):
        logging.debug(__name__ + ' : getting sinc filter status on demodulator %s' % channel)
        return bool(self._device.demods[channel].sinc())
    
    def _do_set_demod_enable(self, onoff, channel):
        mode = "acticating" if onoff else "deactivating"
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
    
    def _do_set_trigger_mode(self, newmode, channel):
        logging.debug(__name__ + " : setting trigger mode on demodulator %s to %s" ,channel, newmode)
        try:
            self._device.demods[channel].trigger(self._trigger_mode_dict[newmode])
        except:
            logging.warning("You entered an invalid trigger mode, puny human.")
    
    def _do_get_trigger_mode(self, channel):
        logging.debug(__name__ + ' : getting trigger mode on demodulator %s' % channel)
        return self._device.demods[channel].trigger()
    
   

    

    # ================= OUTPUT =================
    
    def _do_set_output(self, onoff, channel):
        mode = "activating" if onoff else "deaktivating"
        logging.debug(__name__ + ' : %s output channel %s', mode, channel)
        self._device.sigouts[channel].on(int(bool(onoff)))

    def _do_get_output(self, channel):
        logging.debug(__name__ + ' : getting status of output channel %s' % channel)
        return bool(self._device.sigouts[channel].on())
    
    def _do_set_output_50ohm(self, onoff, channel):
        state = "50ohm" if onoff else "HiZ"
        logging.info("%s : setting expected load on output channel %d to %s", __name__, channel, state)
        logger.info("%s : setting expected load on output channel %d to %s", __name__, channel, state)
        if onoff:
            self.set_parameter_bounds(f"ch{channel}_output_range", 75e-3, 750e-3)
        else:
            self.set_parameter_bounds(f"ch{channel}_output_range", 150e-3, 1.5)
        self._device.sigouts[channel].imp50(int(bool(onoff)))


    def _do_get_output_50ohm(self, channel):
        logging.debug("%s: getting expected load impedance of output channel %d",__name__, channel)
        return bool(self._device.sigouts[channel].imp50())
    
    def _do_set_output_range(self, newrange, channel, matching_50ohm = False):
        valuesarray = np.array([75e-3, 750e-3])
        if matching_50ohm:
            self._device.sigouts[channel].imp50(True)
        else: 
            self._device.sigouts[channel].imp50(False)
            
            
        if not bool(self._device.sigouts[channel].imp50()):                     # no 50Ohm matching
            valuesarray = 2 * valuesarray                                       # 150mV to 1.5V range
        if newrange not in valuesarray:                                         # 50Ohm matching
            index = np.searchsorted(valuesarray, newrange, side="right") - 1
            newrange = valuesarray[index if index >= 0 else 0]
            logging.warning("%s: invalid output range value, setting to next lower value: %.3g",__name__, newrange)

        logging.debug("%s: setting output range on channel %d to %.3g V",__name__, channel, newrange)
        self.set_parameter_bounds(f"ch{channel}_output_offset", -newrange, newrange)
        self.set_parameter_bounds(f"ch{channel}_output_amplitude", -newrange, newrange)
        self._device.sigouts[channel].range(newrange)


    def _do_get_output_range(self, channel):
        logging.debug("%s: getting output range on channel %d",__name__, channel)
        return float(self._device.sigouts[channel].range())
    
    def _do_set_output_offset(self, newoffs, channel):
        logging.debug(__name__ + " : setting offset on output channel %s to %s s" ,channel, newoffs)
        self._device.sigouts[channel].offset(newoffs) 
        
    def _do_get_output_offset(self, channel):
        logging.debug(__name__ + " : getting offset on output channel %s" % channel)
        return float(self._device.sigouts[channel].offset())
    
    def _do_set_output_amplitude(self, newampl, channel):
        logging.debug("%s: setting output amplitude on channel %d to %.3g V",__name__, channel, newampl)
        self._device.sigouts[channel].amplitudes[3 + 4 * channel](newampl)

    def _do_get_output_amplitude(self, channel):
        logging.debug("%s: getting output amplitude on channel %d",__name__, channel)
        return float(self._device.sigouts[channel].amplitudes[3 + 4 * channel]())
    
    def _do_set_output_autorange(self, onoff, channel):
        mode = "activating" if onoff else "deactivating"
        logging.debug(__name__ + ' : %s autorange on output channel %s' ,mode, channel)
        self._device.sigouts[channel].autorange(int(bool(onoff)))
    
    def _do_get_output_autorange(self, channel):
        logging.debug(__name__ + ' : getting the autorange status of output channel %s' % channel)
        return bool(self._device.sigouts[channel].autorange())
    
    def _do_set_output_amp_enable(self, onoff, channel):
        mode = "activating" if onoff else "deactivating"
        logging.debug(__name__ + ' : %s amplitude on output channel %s' ,mode, channel)
        self._device.sigouts[channel].on(int(bool(onoff)))
        #self._device.sigouts[channel].on[3 +4 * channel](int(bool(onoff)))
        
    def _do_get_output_amp_enable(self, channel):
        logging.debug(__name__ + ' : getting amplitude status on output channel %s' % channel)
        #return bool(self._device.sigouts[channel].on[3 + 4 * channel]())
        return bool(self._device.sigouts[channel].on())
    
    
    #SOFTWARE PARAMETERS
    def _do_set_step_recovery(self, new_rec, channel):
        allowed_recs = self._filter_settling_factors.keys()
        if new_rec not in allowed_recs:
            raise ValueError(f"{__name__}: {new_rec} is not a defined step recovery percentile. The allowed percentiles are {allowed_recs}.")
        logging.debug(__name__ + ' : setting step_recovery to %s' ,new_rec)



   
#=======================================================================================================
if __name__ == "__main__":
    import qkit
    qkit.start()    
    
    UHFLI_test = qkit.instruments.create("UHFLI_test", "ZI_UHFLI_v2", device_id = "dev2587")
    
    UHFLI_test.set_dem1_filter_timeconst(1e-3)
    UHFLI_test.set_ch0_output_50ohm(True)
    UHFLI_test.set_ch0_output_amplitude(300e-3)
    UHFLI_test.set_ch0_output_amp_enable(True)
    UHFLI_test.set_ch0_output(True)
    UHFLI_test.set_ch1_input_range(0.7)
    UHFLI_test.set_ch1_input_autorange
    UHFLI_test.set_ch1_input_scaling(32)
    UHFLI_test.set_ch1_input_ac_coupling(True)
    UHFLI_test.set_ch1_input_50ohm(True)
    #UHFLI_test.set_ch1_input_autorange(True)
    UHFLI_test.set_ch1_input_difference("in2-in1")
  
    print(UHFLI_test.get_ch1_input_range())
    print(UHFLI_test.get_ch1_input_scaling())
    print(UHFLI_test.get_ch1_input_ac_coupling())
    print(UHFLI_test.get_ch1_input_50ohm())
    print(UHFLI_test.get_ch1_input_autorange())
    print(UHFLI_test.get_ch1_input_difference())
    print("Done!")
    #UHFLI_test.disable_everything()
