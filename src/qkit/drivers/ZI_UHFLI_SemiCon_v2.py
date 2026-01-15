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
        
        self._FLAG_THROW = 0x0004
        self._FLAG_DETECT = 0x0008
        self.integration_time = 0.2 #in s
        self.timeout = 100 #in ms
        
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
        
    def create_daq_module(self):
        """Create a *new* LabOne Data Acquisition Module instance (unmanaged)."""
        # Toolkit provides a factory for DAQ modules.
        return self.session.create_daq_module()
    
    
    # ================= CONVENIENCE =================
    def activate_ch0(self):
        self.set_dem0_demod_enable(True)
        self.set_ch0_output(True)
        demods = list(self.get_subscribed_demods())  # bei uns statt get_daq_sample_path()
        if 0 not in demods:
            demods.append(0)
        self.easy_sub(demods)
        self.set_data_nodes(["x", "y", "timestamp"])

    def activate_ch1(self):
        self.set_dem4_demod_enable(True)
        self.set_ch1_output(True)
        demods = list(self.get_subscribed_demods())  
        if 4 not in demods:
            demods.append(4)
        self.easy_sub(demods)
        self.set_data_nodes(["x", "y", "timestamp"])
    
    def deactivate_ch0(self):
        self.set_dem0_demod_enable(False)
        self.set_ch0_output(False)

        demods = [d for d in self.get_subscribed_demods() if d != 0]
        self.easy_sub(demods)

    def deactivate_ch1(self):
        self.set_dem4_demod_enable(False)
        self.set_ch1_output(False)

        demods = [d for d in self.get_subscribed_demods() if d != 4]
        self.easy_sub(demods)
        
   
    def sample_dem(self, channel: int) -> Dict[str, float]:
        assert self.get(f"dem{channel}_demod_enable"), f"{__name__}: Demod {channel} is not enabled."

        raw = self._device.demods[channel].sample()   
        nodes = self.get_data_nodes()

        out: Dict[str, float] = {}
        for node in nodes:
            out[f"{node}{channel}"] = float(raw[node])  

        if "x" in nodes and "y" in nodes:
            out[f"r{channel}"] = float(np.hypot(out[f"x{channel}"], out[f"y{channel}"]))
        return out

   
    
    def easy_sub(self, demod_indices):
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
        
    def continuous_acquisition0(self):
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
        measured = self.daq.poll(self.integration_time, self.timeout, self._FLAG_THROW | self._FLAG_DETECT, True)
        nodes = self.get_data_nodes()
        gotten_traces = {}
        for path in measured.keys():
            demod_index = path.split('demods/')[1][0]
            for node in nodes:
                gotten_traces[f"{node}{demod_index}"] = measured[path][node]
            if "x" in nodes and "y" in nodes:
                gotten_traces[f"r{demod_index}"] = np.sqrt(gotten_traces[f"x{demod_index}"]**2 + gotten_traces[f"y{demod_index}"]**2)
        return gotten_traces    
    
    def continuous_acquisition1(self):
        """
        Polls samples for integration_time.
        Intended to be used in a loop which calls the function repeatedly.
        """

        nodes = self.get_data_nodes()
        gotten_traces = {}

        # Toolkit poll (Flags optional je nach Version)
        #try:
         #   from zhinst.toolkit.session import PollFlags
          #  measured = self._session.poll(self.integration_time, flags=PollFlags.DETECT_AND_THROW)
        #except Exception:
        measured = self._session.poll(self.integration_time)

        # statt über measured.keys() zu gehen, benutzen wir die bekannten Demods
        for d in self.get_subscribed_demods():
            path = self._device.demods[d].sample.path
            if path not in measured:
                continue

            block = measured[path]
            if isinstance(block, list) and len(block) > 0:
                block = block[0]

            for node in nodes:
                if node in block:
                    gotten_traces[f"{node}{d}"] = block[node]

            if "x" in nodes and "y" in nodes and f"x{d}" in gotten_traces and f"y{d}" in gotten_traces:
                gotten_traces[f"r{d}"] = np.sqrt(
                    gotten_traces[f"x{d}"]**2 + gotten_traces[f"y{d}"]**2
            )

        return gotten_traces
    
    def continuous_acquisition(self):
        nodes = self.get_data_nodes()
        gotten_traces = {}

        # Polling Data: session.poll(recording_time, timeout)  (timeout als keyword!)
        # Siehe LabOne Manual
        measured = self._session.poll(self.integration_time, timeout=self.timeout)

        for d in self.get_subscribed_demods():
            sample_node = self._device.demods[d].sample

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