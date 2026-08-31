#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Jan 8 2025

@author: Katja
"""
import qkit
import qkit.drivers.ZI_UHFLI_v2 as lolvl

from warnings import warn
from typing import Dict, Iterable, List, Optional
import numpy as np
import logging


try:
    # zhinst-toolkit (recommended high-level API)
    from zhinst.toolkit import Session
    from zhinst.toolkit.session import PollFlags
except Exception as exc:  # pragma: no cover
    Session = None  # type: ignore[assignment]
    PollFlags = None  # type: ignore[assignment]
    _TOOLKIT_IMPORT_ERROR = exc
else:
    _TOOLKIT_IMPORT_ERROR = None


log = logging.getLogger(__name__)

class ZI_UHFLI_SemiCon_v2(lolvl.ZI_UHFLI_v2):
    
    def __init__(self, name, device_id):
        
        self._device_id = device_id
        super().__init__(name, self._device_id)
        
        daq1 = self._session.modules.create_daq_module().raw_module
        daq2 = self._session.modules.create_daq_module().raw_module

        self.daqM1 = qkit.instruments.create("UHFLI_daqM1", "ZI_DAQ_module", unmanaged_daq_module=daq1, device_id=self._device_id)
        self.daqM2 = qkit.instruments.create("UHFLI_daqM2", "ZI_DAQ_module", unmanaged_daq_module=daq2, device_id=self._device_id)
        
        self._FLAG_THROW = 0x0004
        self._FLAG_DETECT = 0x0008
        self.integration_time = 0.05 #in s
        self.timeout = 0.1 #in s // timeout > integration_time
        
        self.add_parameter("data_nodes", type = list,
                          flags = self.FLAG_SET | self.FLAG_SOFTGET)
        self.set_data_nodes([])
        
        self.add_parameter("subscribed_demods", type=list,
                           flags=self.FLAG_SET | self.FLAG_SOFTGET)
        self.set_subscribed_demods([])
    
        
        #qkit functions
        self.add_function("create_daq_module")
        self.add_function("activate_ch0")
        self.add_function("activate_ch1")
        self.add_function("deactivate_ch0")
        self.add_function("deactivate_ch1")
        self.add_function("easy_sub")
        self.add_function("sample_dem")
        self.add_function("get_sample")
        self.add_function("continuous_acquisition")
        self.add_function("sample_averaged")
        self.add_function("convert_reader")
        
        
    def create_daq_module(self):
        """Create a *new* LabOne Data Acquisition Module instance (unmanaged)."""
        # Toolkit provides a factory for DAQ modules.
        return self.session.create_daq_module()
     
    
    # ================= CONVENIENCE =================
    def activate_ch0(self):
        """Enable demod0, acticate ch0 output, subscribe to demod (easy_sub(dem[chanenl])) and set data nodes 'x', 'y', 'timestamp' """
        self.set_dem0_demod_enable(True)
        self.set_ch0_output(True)
        demods = list(self.get_subscribed_demods())  
        if 0 not in demods:
            demods.append(0)
        self.easy_sub(demods)
        self.set_data_nodes(["x", "y", "timestamp"])

    def activate_ch1(self):
        """Enable demod1, activate ch1 output, subscribe to demod (easy_sub([channel]) ans set data nodes 'x', 'y', 'timestamp'"""
        self.set_dem4_demod_enable(True)
        self.set_ch1_output(True)
        demods = list(self.get_subscribed_demods())  
        if 4 not in demods:
            demods.append(4)
        self.easy_sub(demods)
        self.set_data_nodes(["x", "y", "timestamp"])
    
    def deactivate_ch0(self):
        """Disable demod0, deactivate ch0 output"""
        self.set_dem0_demod_enable(False)
        self.set_ch0_output(False)

        demods = [d for d in self.get_subscribed_demods() if d != 0]
        self.easy_sub(demods)

    def deactivate_ch1(self):
        """Disable demod1, deactivate ch2 output"""
        self.set_dem4_demod_enable(False)
        self.set_ch1_output(False)

        demods = [d for d in self.get_subscribed_demods() if d != 4]
        self.easy_sub(demods)
        
   
    def sample_dem(self, channel: int, wait_settle_time: bool = True, attenuation = 15) -> Dict[str, float]:
        """
        One datapoint of 'x', 'y', 'r', 'timestamp'
        Intendet to be used in a loop which calls the function repeatedly.
        
        Parameters
        ----------
        channel: int 
        wait_settle_time: bool (decide it you want to wait each point the calculated setteling_time from 'ZI_UHFLI_v2')
        
        Returns
        -------
        result: dict[str, float]
        """
        assert self.get(f"dem{channel}_demod_enable"), f"{__name__}: Demod {channel} is not enabled."
        
        #wait filter setteling time
        if wait_settle_time:
            self.wait_settle_time(channel)
        
        #get data
        raw = self._device.demods[channel].sample()   
        nodes = self.get_data_nodes()
        

        out: Dict[str, float] = {}
        for node in nodes:
            v = raw[node]
            # wenn v ein Array/Listen ist: letzten Wert nehmen
            if hasattr(v, "__len__") and not np.isscalar(v):
                v = v[-1]
            out[f"{node}{channel}"] = float(v)
            #print(float(raw[node]))
            #out[f"{node}{channel}"] = float(raw[node])
        if channel < 4:
            outamp0 = self.get_ch0_output_amplitude()     
        else: 
            outamp1 = self.get_ch1_output_amplitude()

        if "x" in nodes and "y" in nodes:
            #r0[f"r{channel}"] = float(np.hypot(out[f"x{channel}"], out[f"y{channel}"]))
            out[f"r{channel}"] = float(np.hypot(out[f"x{channel}"], out[f"y{channel}"]))
            
            #out[f"theta{channel}"] = np.arctan2(out[f"y{channel}"], out[f"x{channel}"])
        return out

   
    
    def easy_sub(self, demod_indices):
        """
        Set a subscribtion for demod_indices
        
        Parameters
        ----------
        demod_indices: int (from 0 to 7)
        """
        demod_indices = list(demod_indices)
        for d in demod_indices:
            if not isinstance(d, int):
                raise TypeError(f"{__name__}: {demod_indices} must be iterable of int")
            if d not in range(8):
                raise ValueError(f"{__name__}: Invalid demodulator number {d}")
    # remove old subscriptions
        for d in self.get_subscribed_demods():
            try:
                self._device.demods[d].sample.unsubscribe()
            except Exception:
                pass
    # set new subscriptions 
        for d in demod_indices:
            self._device.demods[d].sample.subscribe()

        self.set_subscribed_demods(demod_indices)
   

    def get_sample(self):
        demods = self.get_subscribed_demods()
        nodes = self.get_data_nodes()
        if not demods:
            raise AssertionError(f"{__name__}: No demods subscribed. Call easy_sub([...]) first.")
        if not nodes:
            raise AssertionError(f"{__name__}: No data_nodes specified.")
        
        channels = {}
        for d in demods:
            raw = self._device.demods[d].sample()   
            got = {}
            for node in nodes:
                got[node] = float(getattr(raw, node))  
            channels[d] = got  
            
        return channels 
    
    
    def continuous_acquisition(self):
        """
        Polls samples for 50 ms.
        Intended to be used in a a loop which calls the function repeatedly.

        Parameters
        ----------
        None

        Returns
        -------
        result : dict(str : np.ndarray)
            Samples polled during the last interval of poll and the time in between two polls.
        
        Raises
        ------
        EOFerror
            If sample loss is detected.
        """
        nodes = self.get_data_nodes()
        gotten_traces = {}

        # Polling Data: session.poll(recording_time, timeout)
        #self._session.poll(0)
        measured = self._session.poll(self.integration_time, timeout=self.timeout)
        #print(measured)

        for d in self.get_subscribed_demods():
            sample_node = self._device.demods[d].sample
            #print(sample_node)
            
            if sample_node not in measured:
                continue

            block = measured[sample_node]  
            
            # --- Sample-loss detection
            timeinfo = block.get("time", {})
            if timeinfo.get("dataloss") or timeinfo.get("blockloss"):
                raise RuntimeError(
                    f"{__name__}: Sample loss detected on demod {d} "
                    f"(dataloss={timeinfo.get('dataloss')}, blockloss={timeinfo.get('blockloss')})"
                )

            for node in nodes:
                if node in block:
                    gotten_traces[f"{node}{d}"] = block[node]

            if "x" in nodes and "y" in nodes and f"x{d}" in gotten_traces and f"y{d}" in gotten_traces:
                gotten_traces[f"r{d}"] = np.hypot(gotten_traces[f"x{d}"], gotten_traces[f"y{d}"])
            #print("TIS ARE THE WONDERFULL TRACES LOOK AND SEE:", gotten_traces)

        return gotten_traces


    def sample_averaged(self, avgs):
        """
        Software averages samples before returning.

        Parameters
        ----------
        avgs : int

        Returns
        -------
        result : dict(str : np.float64)
            Samples polled during the last interval of poll and the time in between two polls.
        
        Raises
        ------
        EOFerror
            If sample loss is dected.
        """
        
        node_lengths = {}
        cumulated_avgs = {}
        #self._session.poll(0)
        #self.daq.flush()
        
        measured = self.continuous_acquisition()
        for node, values in measured.items(): 
            count = len(values)
            if count >= avgs:
                values = values[:avgs]
                node_lengths[node] = avgs
            else:
                node_lengths[node] = count
            cumulated_avgs[node] = np.sum(values)
        
        while(not all(length >= avgs for length in node_lengths.values())):
            measured = self.continuous_acquisition()
            for node, values in measured.items():
                count = node_lengths[node] + len(values)
                if count >= avgs:
                    values = values[:avgs - node_lengths[node]]
                    node_lengths[node] = avgs
                else:
                    node_lengths[node] = count
                cumulated_avgs[node] += np.sum(values)
        result = {node: values/avgs for node, values in cumulated_avgs.items()}        
        return result    
          
    def convert_reader(self, reader, *, v_gain, voltage_divider=False, divider_factor=1.0):
        """
        Wrappt a Reader and convert only x0/y0 (and set r0 new).
        timestamp0 remains.
        
        Parameters
        ----------
        reader
        v_gain
        voltage_divider: bool
        divider_factor = 1.0
        
        Return
        ------
        x|y = (x|y*devider_factor)/v_gain
        r out of x and y
        """
        def wrapped():
            d = reader()
            out = dict(d)

            # nur wenn x0/y0 existieren und nicht leer sind
            if "x0" in out and "y0" in out and len(out["x0"]) > 0:
                x = out["x0"].astype(float, copy=False)
                y = out["y0"].astype(float, copy=False)

                if voltage_divider:
                    x = x * divider_factor
                    y = y * divider_factor

                x = x / v_gain
                y = y / v_gain

                out["x0"] = x
                out["y0"] = y
                out["r0"] = np.hypot(x, y)

            return out
        return wrapped
        
    def _do_set_subscribed_demods(self, newdemods):
        typerr = TypeError(f"{__name__}: Cannot set {newdemods} as subscribed_demods. Must be a list of int.")
        for element in newdemods:
            if not isinstance(element, int):
                raise typerr  
        logging.debug(__name__ + ' : setting subscribed demods to %s', newdemods)
        # Unsubscribe all previous
        for d in (self.get_subscribed_demods() or []):
            try:
                self._device.demods[d].sample.unsubscribe()
            except Exception:
                pass
        # Subscribe new
        for d in newdemods:
            self._device.demods[d].sample.subscribe()
       
    
    def _do_set_data_nodes(self, newnode):
        """
        set data nodes
        posible nodes: "timestamp", "x", "y", "frequency", "phase", "dio", "trigger", "auxin0", "auxin1" """
        allowed_nodes = {"timestamp", "x", "y", "frequency", "phase", "dio", "trigger", "auxin0", "auxin1"}
        typerr = TypeError("%s: Cannot set %s as data_nodes. Object must be a list of strings." % (__name__, newnode))
        if not isinstance(newnode, list):
            raise typerr
        for element in newnode:
            if not isinstance(element, str):
                raise typerr         
            if element not in allowed_nodes:
                raise ValueError(f"{__name__}: {element} is not an allowed data_node. The allowed data_nodes are {allowed_nodes}.")
        logging.debug(__name__ + ' : setting data_nodes to %s' % (newnode))
    
    def labone_fft_demod(self, demod=0, cols=65536, timeout=10):
        """
        LabOne native FFT using DAQ module (identical to Web UI FFT tab).
        """

        daq = self._session.modules.daq

        daq.grid.mode(4)                # FFT mode
        daq.type(0)
        daq.preview(1)
        daq.grid.rows(10)
        daq.grid.rowrepetition(1)
        daq.grid.waterfall(1)
        daq.grid.overwrite(1)

        daq.device(self._device_id)
        daq.historylength(10)
        daq.delay(0)

        daq.spectrum.enable(1)
        daq.grid.cols(int(cols))
        daq.clearhistory(1)
        daq.endless(0)

        # FFT output nodes (UI identical)
        fft_filter = f"/{self._device_id}/demods/{demod}/sample.xiy.fft.abs.filter"
        fft_avg    = f"/{self._device_id}/demods/{demod}/sample.xiy.fft.abs.avg"

        daq.subscribe(fft_filter)
        daq.subscribe(fft_avg)

        daq.execute()

        import time
        t0 = time.time()
        result = {}

        while time.time() - t0 < timeout:
            data = daq.read()
            if data:
                result = data
            if daq.progress()[0] >= 1.0 or daq.finished():
                break
            time.sleep(0.1)

        daq.finish()
        daq.unsubscribe("*")

        if not result:
            raise TimeoutError("No FFT data returned from LabOne.")

        return result
        
        
        
#%%
if __name__ == "__main__":
    qkit.start()
    #%% Create the device
    UHFLI = qkit.instruments.create("UHFLI", "ZI_UHFLI_SemiCon_v2", device_id = "dev2587")
    #%% Lockin Settings   
# =============================================================================
    UHFLI.activate_ch0()
    UHFLI.easy_sub([0])
    UHFLI.set_data_nodes(["x", "y"])
#     
#     UHFLI.set_ch1_input_ac_coupling(True)
#     UHFLI.set_ch1_input_50ohm(True)
#     UHFLI.set_ch1_input_range(0.5)
#     
    UHFLI.set_dem0_demod_enable(True)
#     UHFLI.set_dem1_sample_rate(14e6)
#     UHFLI.set_dem1_filter_order(4)
#     UHFLI.set_dem1_filter_timeconst(1e-3)
#     UHFLI.set_dem1_demod_harmonic(1)
#     UHFLI.set_dem1_trigger_mode("continuous")
# 
#     UHFLI.set_ch1_carrier_freq(400e3)
#     UHFLI.set_ch1_output(True)
#     UHFLI.set_ch1_output_amp_enable(True)
#     UHFLI.set_ch1_output_range(1.5)
#     UHFLI.set_ch1_output_amplitude(0.25)

    print("subscribed_demods:", UHFLI.get_subscribed_demods())
    print("sample node path:", UHFLI._device.demods[0].sample)
    print("demod0 enabled:", UHFLI.get_dem0_demod_enable())
    
    #_ = UHFLI._session.poll(0)      # optional "flush"
    data = UHFLI._session.poll(0.05)
    print(data.keys())


# =============================================================================
    #%% Get a sample
    UHFLI.activate_ch0()
    #UHFLI.activate_ch1()
    #UHFLI.daq.flush()
    print(UHFLI.sample_averaged(100)["x0"])
    #print(UHFLI.find_slowest_demod())

    #%% Sample chx
    print(UHFLI.sample_dem(0))
    #Continuous acquisition Test (ein Block)
    traces = UHFLI.continuous_acquisition()
    print("Got keys:", sorted(traces.keys()))
    if "x0" in traces:
        print("len(x0):", len(traces["x0"]))