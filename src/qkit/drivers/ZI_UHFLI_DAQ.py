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

    Readout modes (set_readout_mode, applied at the next arm()):
        "gated"      (default) demod0 sends samples only while the trigger input is high
        "continuous" demod0 streams all samples; only up to MAX_CONTINUOUS_RATE
        "edge"       demod0 sends ONE sample per rising edge. The DAQ module is NOT used in this
                     mode (all samples carry the same trigger bits, so its edge trigger never fires);
                     the demod stream is read directly and cut into grids of `rows` samples.
                     cols is always 1.
    In gated/continuous mode the DAQ module starts a window on the rising edge of TrigIn3.

    Continuous streaming above MAX_CONTINUOUS_RATE overloads the network (the data server drops the
    device). The driver therefore never lets demod0 stream continuously above it:
      - set_continuous_readout() (idle state after a measurement) lowers the device rate to the limit
        and stores the measurement rate;
      - setting a higher rate while demod0 streams continuously only stores it;
      - get_dem0_sample_rate() reports the stored measurement rate, so Spin Excite and the grid setup
        use the rate the measurement will run at;
      - arm() switches to the gated/edge transfer FIRST and only then raises the device rate;
      - a measurement in continuous mode above the limit is refused.
    """

    # LabOne DAQ module trigger type. 6 = hardware trigger (uses triggernode).
    TRIGGER_TYPE = 6

    # demods/0/trigger value per readout mode (checked: gated = 32 and edge = 1 use the same input)
    DEMOD_TRIGGER = {
        "continuous": 0,
        "gated": 32,
        "edge": 1,
    }

    # Highest demod0 rate for continuous streaming (Hz); change per session with set_max_continuous_rate().
    MAX_CONTINUOUS_RATE = 100e3

    # UNVERIFIED meaning of the header flag bits, so filtering is off by default.
    USE_FLAGS = False
    
    # defaults on class level: also valid for instances created before a driver update
    _rows, _cols, _count = 1, 1, 1
    _edge_buf = None
    _edge_done = 0
    _rate_before_idle = None    # rate saved when set_continuous_readout() lowered it

    @property
    def _edge_path(self):
        return f"/{self._device_id.lower()}/demods/0/sample"

    def __init__(self, name, device_id):

        self._device_id = device_id
        super().__init__(name, self._device_id)
        # ======================================================
        # DAQ MODULE
        # ======================================================
        self._daq_module = self._session.daq_server.dataAcquisitionModule()
        self._daq_module.set("device", self._device_id)
        self._readout_mode = "gated"

        # grid geometry (stored locally for edge mode)
        self._rows, self._cols, self._count = 1, 1, 1
        # edge mode: direct demod stream
        self._edge_buf = None
        self._edge_done = 0

        # ======================================================
        # QKIT FUNCTIONS
        # ======================================================
        self.add_function("setup_triggered_readout")
        self.add_function("set_continuous_readout")
        self.add_function("set_readout_mode")
        self.add_function("get_readout_mode")
        self.add_function("set_max_continuous_rate")
        self.add_function("get_max_continuous_rate")
        self.add_function("sub_dem0")

        self.add_function("set_daq_measurement_count")
        self.add_function("set_daq_sample_count")
        self.add_function("set_daq_grid")

        self.add_function("arm")
        self.add_function("finished")
        self.add_function("read")
        self.add_function("stop")

    # ==========================================================
    # READOUT MODE
    # ==========================================================
    def set_readout_mode(self, mode):
        """'gated' (default), 'continuous' or 'edge'. Takes effect at the next arm()."""
        if mode not in self.DEMOD_TRIGGER:
            raise ValueError(f"mode must be one of {list(self.DEMOD_TRIGGER)}")
        self._readout_mode = mode

    def get_readout_mode(self):
        return self._readout_mode

    # ==========================================================
    # CONTINUOUS RATE LIMIT
    # ==========================================================
    def set_max_continuous_rate(self, rate):
        """Highest demod0 rate (Hz) allowed while streaming continuously."""
        self.MAX_CONTINUOUS_RATE = float(rate)

    def get_max_continuous_rate(self):
        return self.MAX_CONTINUOUS_RATE

    def _check_continuous_rate(self):
        rate = self.get_dem0_sample_rate()
        if rate > self.MAX_CONTINUOUS_RATE:
            raise ValueError(
                f"demod0 rate {rate/1e3:.1f} kHz is above the continuous limit "
                f"({self.MAX_CONTINUOUS_RATE/1e3:.0f} kHz); lower the sample rate or use readout mode 'gated'.")

    def _restore_sample_rate(self):
        """Set back the stored measurement rate on the device (no-op if nothing is stored).
        Call only when demod0 is no longer streaming continuously."""
        if self._rate_before_idle is not None:
            rate, self._rate_before_idle = self._rate_before_idle, None
            self._device.demods[0].rate(rate)       # directly, bypassing the idle limit

    def _do_set_sample_rate(self, newrate, channel):
        """While demod0 streams continuously, a rate above the limit is only stored (applied in arm());
        otherwise it is set directly."""
        if (channel == 0 and newrate > self.MAX_CONTINUOUS_RATE
                and int(self._device.demods[0].trigger()) == 0):
            self._rate_before_idle = float(newrate)
            self._device.demods[0].rate(self.MAX_CONTINUOUS_RATE)
            log.info(f"demod0 streams continuously: {newrate/1e3:.1f} kHz stored for the next measurement, "
                     f"{self.MAX_CONTINUOUS_RATE/1e3:.0f} kHz set for now")
            return
        if channel == 0:
            self._rate_before_idle = None           # an explicit rate replaces a stored one
        super()._do_set_sample_rate(newrate, channel)

    def _do_get_sample_rate(self, channel):
        """The rate the next measurement runs at (the stored one while idling at the limit)."""
        if channel == 0 and self._rate_before_idle is not None:
            return float(self._rate_before_idle)
        return super()._do_get_sample_rate(channel)

    # ==========================================================
    # DAQ CONFIGURATION
    # ==========================================================
    def setup_triggered_readout(self, debug=False):
        """
        Configure the DAQ module for triggered, grid-based acquisition.
        Does NOT touch grid/rows, grid/cols, count or holdoff/time: those are set by
        set_daq_measurement_count / set_daq_sample_count / set_daq_grid.
        debug=True is kept for compatibility and is the same as set_readout_mode('continuous').
        """
        if debug:
            self._readout_mode = "continuous"
        self._daq_module.set("type", self.TRIGGER_TYPE)
        self._limit_continuous_rate()       # continuous while arming -> at most MAX_CONTINUOUS_RATE
        self._device.demods[0].trigger(0)   # continuous while arming; the mode is applied in arm()
        self._daq_module.set("triggernode", f"/{self._device_id}/demods/0/sample.TrigIn3")
        self._daq_module.set("edge", 1)             # rising
        self._daq_module.set("holdoff/count", 0)    # number of skipped triggers
        self._daq_module.set("delay", 0)            # delay between trigger and acquisition

        self._daq_module.set("grid/mode", 4)        # exact, no interpolation
        self._daq_module.set("grid/direction", 0)   # forward
        self._daq_module.set("grid/repetitions", 1) # no internal averaging, one grid = one average

    def set_continuous_readout(self):
        """Counterpart to setup_triggered_readout: demod0 transfers data continuously again,
        at most at MAX_CONTINUOUS_RATE (a higher rate is lowered and restored at the next setup)."""
        self._limit_continuous_rate()
        self._device.demods[0].trigger(0)

    def _limit_continuous_rate(self):
        """Lower the device rate to MAX_CONTINUOUS_RATE (storing the measurement rate) if it is higher."""
        rate = float(self._device.demods[0].rate())
        if rate > self.MAX_CONTINUOUS_RATE:
            if self._rate_before_idle is None:
                self._rate_before_idle = rate
            self._device.demods[0].rate(self.MAX_CONTINUOUS_RATE)
            log.info(f"demod0 rate lowered from {rate/1e3:.1f} kHz to "
                     f"{self.MAX_CONTINUOUS_RATE/1e3:.0f} kHz for continuous streaming")

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
        self._rows = int(meas_num)
        self._daq_module.set("grid/rows", self._rows)

    def set_daq_sample_count(self, sample_num):
        """Samples per window (grid columns). Set the demod sample rate BEFORE calling this."""
        sample_num = int(sample_num)
        if self._readout_mode == "edge":
            sample_num = 1                      # one sample per rising edge
        self._cols = sample_num
        self._daq_module.set("grid/cols", sample_num)
        self._daq_module.set("holdoff/time", sample_num / self.get_dem0_sample_rate())

    def set_daq_grid(self, grid_num):
        """Number of grids to acquire = number of averages."""
        self._count = int(grid_num)
        self._daq_module.set("count", self._count)

    # ==========================================================
    # ACQUISITION
    # ==========================================================
    def arm(self):
        if self._readout_mode == "edge":
            # edge mode: no DAQ module, read the demod stream directly (one sample = one window)
            d = self._session.daq_server
            self._device.demods[0].trigger(self.DEMOD_TRIGGER["edge"])
            self._restore_sample_rate()         # measurement rate only after continuous streaming is off
            d.sync()
            d.subscribe(self._edge_path)
            d.poll(0.02, 10, 0, True)           # discard samples from before arming
            self._edge_buf = {"x": [], "y": [], "timestamp": []}
            self._edge_done = 0
            return
        if self._readout_mode == "continuous":
            self._check_continuous_rate()   # refuse before streaming at a rate the network can't handle
        self._daq_module.execute()
        value = self.DEMOD_TRIGGER[self._readout_mode]
        if value:
            self._device.demods[0].trigger(value)
            self._session.daq_server.sync()
            self._restore_sample_rate()     # measurement rate only after continuous streaming is off

    def _edge_poll(self):
        """collect new edge samples into the buffer, return the number of buffered samples"""
        data = self._session.daq_server.poll(0.01, 10, 0, True)
        s = data.get(self._edge_path)
        if s is not None and len(s["timestamp"]):
            for k in ("x", "y", "timestamp"):
                self._edge_buf[k].append(np.asarray(s[k], dtype=float))
        return sum(len(a) for a in self._edge_buf["x"])

    def finished(self):
        """Non-blocking. True if all requested grids are acquired."""
        if self._readout_mode == "edge":
            if self._edge_buf is None:
                return False
            n = self._edge_poll()
            return self._edge_done + n // max(self._rows, 1) >= self._count
        return bool(self._daq_module.finished())

    def stop(self):
        """Safe to call repeatedly: stop, discard leftover data, drop subscriptions."""
        if self._edge_buf is not None:
            try:
                self._session.daq_server.unsubscribe(self._edge_path)
            except Exception:
                pass
            self._edge_buf = None
        self._daq_module.finish()
        self._daq_module.read(True)
        self._daq_module.unsubscribe("*")

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
        Return all complete grids since the last call (only the requested signals):
        {"demod0": {"x"|"y"|"r"|"theta"|"timestamp": array(n, rows, cols)}}
        or {} if there is no new data.
        """
        if self._readout_mode == "edge":
            return self._edge_read(signals)
        return self._daq_read(signals)

    # ---------------- edge mode: direct demod stream ----------------
    def _edge_read(self, signals):
        if self._edge_buf is None:
            return {}
        self._edge_poll()
        buf = {k: (np.concatenate(v) if v else np.empty(0)) for k, v in self._edge_buf.items()}
        rows = max(self._rows, 1)
        n_new = min(len(buf["x"]) // rows, self._count - self._edge_done)
        if n_new <= 0:
            self._edge_buf = {k: [a] for k, a in buf.items()}
            return {}
        take = n_new * rows
        x, y = buf["x"][:take], buf["y"][:take]
        ts = buf["timestamp"][:take] * float(self._device.system.properties.timebase())
        self._edge_buf = {k: [a[take:]] for k, a in buf.items()}      # keep the rest for the next grid
        self._edge_done += n_new
        shape = (n_new, rows, 1)
        out = {}
        for sgl in signals:
            if sgl == "x":
                out["x"] = x.reshape(shape)
            elif sgl == "y":
                out["y"] = y.reshape(shape)
            elif sgl == "r":
                out["r"] = np.hypot(x, y).reshape(shape)
            elif sgl == "theta":
                out["theta"] = np.arctan2(y, x).reshape(shape)
            elif sgl == "timestamp":
                out["timestamp"] = ts.reshape(shape)
        return {"demod0": out}

    # ---------------- gated / continuous: DAQ module ----------------
    def _daq_read(self, signals=("x", "y", "r", "theta", "timestamp")):
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