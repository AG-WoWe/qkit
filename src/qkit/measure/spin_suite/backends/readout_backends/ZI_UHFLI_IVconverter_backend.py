#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Feb 2026

@author: oc0612
"""
from qkit.measure.spin_suite.backends.readout_backends.ZI_UHFLI_backend_v2 import ZI_UHFLI_backend_v2
import logging 
import sys 


class ZI_UHFLI_IVconverter_backend(ZI_UHFLI_backend_v2):
    def __init__(self, UHFLI,
                 use_iv_converter: bool = False,
                 iv_converter: float = 1e8,          # V/A
                 use_voltage_divider: bool = False,
                 voltage_divider: float = 3.0):      # e.g. 3 for 1:3
        super().__init__(UHFLI)

        self.use_iv_converter = bool(use_iv_converter)
        self.iv_converter = float(iv_converter)

        self.use_voltage_divider = bool(use_voltage_divider)
        self.voltage_divider = float(voltage_divider)

    def set_iv_conversion(self, enable: bool, iv_converter: float | None = None):
        self.use_iv_converter = bool(enable)
        if iv_converter is not None:
            self.iv_converter = float(iv_converter)

    def set_voltage_divider(self, enable: bool, divider: float | None = None):
        self.use_voltage_divider = bool(enable)
        if divider is not None:
            self.voltage_divider = float(divider)

    def _apply_conversion(self, node: str, value):
        """
        Correct only r/x/y.
        1) Voltage divider: V_real = V_meas * divider
        2) I/V Converter: I = V_real /(V/A)
        """
        if node in ("r", "x", "y"):
            if self.use_voltage_divider:
                value = value * self.voltage_divider
            if self.use_iv_converter:
                value = value / self.iv_converter
        return value

    def read(self):
        data = {}

        for demod, settings in self.settings.items():
            if settings["active"]:
                data[demod] = {}
                raw_data = settings["daqM"].read()

                for node in self._registered_measurements[demod]["data_nodes"]:
                    data[demod][node] = []
                    path = f"/{self._id}/demods/{settings['demod_index']}/sample.{node}"

                    if path in raw_data:
                        for grid in raw_data[path]:
                            if grid["header"]["flags"] & 1:
                                value = grid["value"]
                                value = self._apply_conversion(node, value)
                                data[demod][node].append(value)

        return data


###########################################################################
#Call in Python:
# backend = ZI_UHFLI_IVconverter_backend(
#    UHFLI,
#    use_iv_converter=True, iv_converter=1e8,
#    use_voltage_divider=True, voltage_divider=10.0
#)
#for a new setup in Python 
# backend.set_iv_conversion(False) #no iv converter
# backend.set_voltage_divider(True, 20.0) #voltage divider with 1:20
