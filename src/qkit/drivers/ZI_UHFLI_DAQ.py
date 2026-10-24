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

log = logging.getLogger(__name__)


class ZI_UHFLI_DAQ(parent.ZI_UHFLI_v3):
    """
    UHFLI with a DAQ module configured for triggered, grid-based readout.

    Grid semantics (matches spin_excite):
        grid/rows = measurement_count  (triggers = measurement windows per sequence run)
        grid/cols = sample_count       (samples per window)
        count     = averages           (number of grids = repetitions of the sequence)
    read() returns arrays of shape (n_new_grids, rows, cols).
    """

    # LabOne DAQ module trigger type. 6 = hardware trigger (uses triggernode).
    # UNVERIFIED: check against the LabOne DAQ module documentation for your version.
    TRIGGER_TYPE = 6

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
        self.add_function("stop")

    # ==========================================================
    # DAQ CONFIGURATION
    # ==========================================================
    def setup_triggered_readout(self, debug=False):
        """
        Configure the DAQ module for triggered, grid-based acquisition.
        Does NOT touch grid/rows, grid/cols, count or holdoff/time: those are set by
        set_daq_measurement_count / set_daq_sample_count / set_daq_grid.
        """
        self._daq_module.set("type", self.TRIGGER_TYPE)
        if debug:
            self._device.demods[0].trigger(0)   # demod0 transfers continuously
        else:
            self._device.demods[0].trigger(32)  # demod0 data transfer gated by Trigger Input 3
        self._daq_module.set("triggernode", f"/{self._device_id}/demods/0/sample.TrigIn3")
        self._daq_module.set("edge", 1)             # rising
        self._daq_module.set("holdoff/count", 0)    # number of skipped triggers
        self._daq_module.set("delay", 0)            # delay between trigger and acquisition

        self._daq_module.set("grid/mode", 4)        # exact, no interpolation (UNVERIFIED)
        self._daq_module.set("grid/direction", 0)   # forward
        self._daq_module.set("grid/repetitions", 1) # no internal averaging, one grid = one average

    # ==========================================================
    # SUBSCRIPTIONS
    # ==========================================================
    def sub_dem0(self, signals=("x", "y", "r", "theta")):
        """Subscribe only the requested signals (less data from the lock-in)."""
        demods = 0
        for sig in signals:
            if sig in ("x", "y", "r", "theta"):
                self._daq_module.subscribe(f"/{self._device_id}/demods/{demods}/sample.{sig}")

    # ==========================================================
    # GRID CONFIGURATION
    # ==========================================================
    def set_daq_measurement_count(self, meas_num):
        """Number of triggered measurement windows per sequence run (grid rows)."""
        self._daq_module.set("grid/rows", int(meas_num))

    def set_daq_sample_count(self, sample_num):
        """Samples per window (grid columns). Set the demod sample rate BEFORE calling this."""
        sample_num = int(sample_num)
        self._daq_module.set("grid/cols", sample_num)
        trigger_duration = sample_num / self.get_dem0_sample_rate()
        self._daq_module.set("holdoff/time", trigger_duration)

    def set_daq_grid(self, grid_num):
        """Number of grids to acquire = number of averages."""
        self._daq_module.set("count", int(grid_num))

    # ==========================================================
    # ACQUISITION
    # ==========================================================
    def arm(self):
        self._daq_module.execute()

    def finished(self):
        """Non-blocking. True if the DAQ module has acquired all requested grids."""
        return bool(self._daq_module.finished())

    def stop(self):
        """Safe to call repeatedly: stop, discard leftover data, drop subscriptions."""
        self._daq_module.finish()
        self._daq_module.read(True)
        self._daq_module.unsubscribe("*")

    # UNVERIFIED meaning of the header flag bits, so filtering is off by default.
    USE_FLAGS = False

    @classmethod
    def _chunk_complete(cls, chunk):
        if not cls.USE_FLAGS:
            return True
        flags = chunk.get("header", {}).get("flags")
        if flags is None:
            return True
        # flags can be an array; require bit 0 on all entries
        return bool(np.all(np.atleast_1d(flags).astype(int) & 1))

    def read(self, signals=("x", "y", "r", "theta", "timestamp")):
        """
        Return all grids completed since the last call (only the requested signals):
        {"demod0": {"x"|"y"|"r"|"theta"|"timestamp": array(n, rows, cols)}}
        or {} if there is no new complete grid.
        """
        data = self._daq_module.read(True)
        timebase = float(self._device.system.properties.timebase())

        sig = [s for s in signals if s in ("x", "y", "r", "theta")]
        if not sig:
            raise ValueError("read: at least one of x, y, r, theta is needed")
        values, stamps = {}, []
        for path, chunks in data.items():
            if "sample" not in path.lower():
                continue
            name = path.split(".")[-1]
            if name not in sig:
                continue
            arrs, ts = [], []
            for chunk in chunks:
                if not self._chunk_complete(chunk):
                    continue
                val = np.atleast_2d(np.asarray(chunk["value"], dtype=float))
                arrs.append(val)
                t = np.asarray(chunk["timestamp"], dtype=float).ravel() * timebase
                if t.size == val.size:
                    t = t.reshape(val.shape)
                elif t.size == val.shape[-1]:
                    t = np.tile(t, (val.shape[0], 1))
                else:
                    t = np.full(val.shape, np.nan)
                ts.append(t)
            if arrs:
                values[name] = np.stack(arrs)
                if name == sig[0]:
                    stamps = ts

        if len(values) < len(sig):
            return {}
        n = min(len(v) for v in values.values())
        if n == 0:
            return {}
        out = {name: v[:n] for name, v in values.items()}
        if "timestamp" in signals:
            first = out[sig[0]]
            out["timestamp"] = np.stack(stamps[:n]) if len(stamps) >= n else np.full_like(first, np.nan)
        return {"demod0": out}