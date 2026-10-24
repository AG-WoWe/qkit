#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mo Jan  26 10:21:24 2026

@author: lr1740
"""
import time

from qkit.measure.spin_suite.backends.readout_backends.RO_backend_base import RO_backend_base


class ZI_UHFLI_backend_v3(RO_backend_base):

    def __init__(self, UHFLI, read_timeout=0.5, nodes=("r",)):
        """
        Parameters
        ----------
        UHFLI :
            Instance of ZI_UHFLI_DAQ.
        read_timeout : float
            Maximum time (s) read() waits for new data before returning {}.
        nodes : sequence of str
            Which values are transferred and saved: any of "x", "y", "r", "theta", "timestamp".
        """
        super().__init__()

        nodes = list(nodes)
        if not nodes or any(n not in ("x", "y", "r", "theta", "timestamp") for n in nodes):
            raise ValueError("nodes must be a non-empty subset of x, y, r, theta, timestamp")
        if all(n == "timestamp" for n in nodes):
            raise ValueError("timestamp alone is not enough, add at least one of x, y, r, theta")

        self.UHFLI = UHFLI
        self._id = self.UHFLI._device_id
        self._read_timeout = read_timeout
        self._nodes = nodes

        self._averages = 1
        self._received = 0

        # Register measurements: these nodes define the datasets in the file
        self.register_measurement("demod0", "V", self._nodes)

    # ------------------------------------------------------------------
    # Sample rate (spin_excite only READS it; set it before creating Exciting)
    # ------------------------------------------------------------------
    def demod0_set_sample_rate(self, rate=None, oversampling=10):
        """
        rate : float, optional
            Sample rate in Hz, set directly.
        oversampling : float
            Used if no rate is given: rate = oversampling * filter bandwidth.
        """
        if rate is None:
            self.UHFLI.set_sampling_rate(0, oversampling)
        else:
            self.UHFLI.set_dem0_sample_rate(rate)

    def demod0_get_sample_rate(self):
        return self.UHFLI.get_dem0_sample_rate()  # Hz

    # ------------------------------------------------------------------
    # Configuration (called by Settings.load in this order)
    # ------------------------------------------------------------------
    def demod0_set_measurement_count(self, meas_num):
        self.UHFLI.set_daq_measurement_count(meas_num)

    def demod0_set_sample_count(self, sample_num):
        self.UHFLI.set_daq_sample_count(sample_num)

    def demod0_set_averages(self, grid_num):
        self._averages = int(grid_num)
        self.UHFLI.set_daq_grid(grid_num)

    def demod0_activate(self):
        self.UHFLI.set_dem0_demod_enable(True)
        self._registered_measurements["demod0"]["active"] = True

    def demod0_deactivate(self):
        self.UHFLI.set_dem0_demod_enable(False)
        self._registered_measurements["demod0"]["active"] = False

    # ------------------------------------------------------------------
    # Acquisition control
    # ------------------------------------------------------------------
    def arm(self):
        self._received = 0
        self.UHFLI.setup_triggered_readout()
        self.UHFLI.sub_dem0(self._nodes)   # subscribe only what is saved, before execute
        self.UHFLI.arm()

    def finished(self):
        # Non-blocking; True once all averages have been handed out by read().
        return self._received >= self._averages

    def read(self):
        """
        Returns only data captured since the last call:
        {"demod0": {node: array(n_new, measurement_count, sample_count)}}
        Waits up to read_timeout for data, then returns {}.
        """
        deadline = time.time() + self._read_timeout
        while True:
            data = self.UHFLI.read(self._nodes)
            if data or time.time() > deadline:
                break
            time.sleep(1e-2)
        if not data:
            return {}

        # Never hand out more averages than requested
        remaining = self._averages - self._received
        for node, arr in data["demod0"].items():
            data["demod0"][node] = arr[:remaining]
        self._received += len(next(iter(data["demod0"].values())))
        return data

    def stop(self):
        # Called before every arm and at the end of a measurement; safe to repeat.
        self.UHFLI.stop()
        self._received = 0