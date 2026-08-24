#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Aug 21 2026

@author: Daniel
"""
import qkit
import qkit.drivers.ZI_UHFLI_v3 as parent

import numpy as np
import logging
import time

from zhinst.toolkit import Session

log = logging.getLogger(__name__)

class ZI_UHFLI_DAQ(parent.ZI_UHFLI_v3):
    
    def __init__(self, name, device_id):
        
        self._device_id = device_id
        super().__init__(name, self._device_id)
        # ======================================================
        # DAQ MODULE
        # ======================================================
        self._daq_module = self._session.daq_server.dataAcquisitionModule()
        self._daq_module.set("device", self._device_id)

        # ======================================================
        # QKIT FUNCTIONS
        # ======================================================
        self.add_function("setup_triggered_readout")
        self.add_function("sub_dem0")

        self.add_function("set_daq_measurement_count")
        self.add_function("set_daq_sample_count")
        self.add_function("set_daq_grid")

        self.add_function("arm")
        self.add_function("finished")
        self.add_function("read")
        # self.add_function("stop")  

    # ==========================================================
    # DAQ CONFIGURATION
    # ==========================================================
    def setup_triggered_readout(self, debug = False):  
        """
        Configure the Zurich Instruments DAQ module for
        triggered acquisition.
        """
        self._daq_module.set("type", 0) # Continous acquisition mode
        if debug:
            self._device.demods[0].trigger(0) # Set demod0 trigger to continuous    
        else:
            self._device.demods[0].trigger(32) # Set demod0 trigger to high for Trigger Input 3
            self._daq_module.set('triggernode', '/dev2587/demods/0/sample.TrigIn3') # Set trigger node from DAQ to Trigger Input 3
        self._daq_module.set('edge', 1) # Set trigger to rising
        self._daq_module.set("holdoff/time", 0) # Hold of time before being rearmed
        self._daq_module.set("count", 0) # Number of skipped triggers
        self._daq_module.set("delay", 0) # Delay time after trigger before starting acquisition

    # ==========================================================
    # SUBSCRIPTIONS
    # ==========================================================
    def sub_dem0(self):  
        demods = 0
        signal_node_x = f"/{self._device_id}/demods/{demods}/sample.x"
        signal_node_y = f"/{self._device_id}/demods/{demods}/sample.y"
        signal_node_r = f"/{self._device_id}/demods/{demods}/sample.r"
        signal_node_theta = f"/{self._device_id}/demods/{demods}/sample.theta" 

        self._daq_module.subscribe(signal_node_x)
        self._daq_module.subscribe(signal_node_y)
        self._daq_module.subscribe(signal_node_r)
        self._daq_module.subscribe(signal_node_theta)

    # ==========================================================
    # GRID CONFIGURATION
    # ==========================================================
    def set_daq_measurement_count(self, meas_num):
        """
        Set the number of triggered measurements.
        """
        self._daq_module.set("grid/count", meas_num)


    def set_daq_sample_count(self, sample_num):
        """
        Set the number of samples acquired per trigger.
        """
        self._daq_module.set("grid/cols", sample_num)

        trigger_duration = (
            sample_num / self.get_dem0_sample_rate()
        )

        self._daq_module.set("holdoff/time", trigger_duration)


    def set_daq_grid(self, grid_num):
        """
        Set the number of grid rows/averages.
        """
        self._daq_module.set("grid/rows", grid_num)

        
    # ==========================================================
    # ACQUISITION
    # ==========================================================
    def arm(self):
        self._daq_module.execute()

    def finished(self):
        while not self._daq_module.finished():
            time.sleep(1e-3)

    def read(self):
        data = self._daq_module.read(True)
        out = {"demod0": {"x": [], "y": [], "r": [], "theta": [], "timestamp": []}}
        for key, sample in data.items():
            if "sample" not in key.lower():
                continue
            name = key.split(".")[-1]
            if name in out["demod0"]:
                out["demod0"][name] = sample[0]["value"].flatten().tolist()
            if name == "r":
                out["demod0"]["timestamp"] = (sample[0]["timestamp"].flatten() * self._device.system.properties.timebase()).tolist()
        return out


