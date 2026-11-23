# -*- coding: utf-8 -*-
"""
Combined readout backend: several readout backends behind one object, so that one Exciting
measurement records all of them in the same pulse train (e.g. ADwin DC current and UHFLI lock-in
at the same time).

Every measurement registered in a sub-backend (e.g. "input1" of the ADwin backend, "demod0" of the
UHFLI backend) is registered here under the same name, with the same unit and data nodes. The
per-measurement methods (<name>_get_sample_rate, _set_measurement_count, _set_sample_count,
_set_averages, _activate, _deactivate) are forwarded to the sub-backend that owns the measurement.

arm(), finished(), read() and stop() are applied to every sub-backend that has at least one active
measurement; read() merges their data dicts.

Usage:
    readout_backend_DCRF = Combined_readout_backend(readout_backend_DC, readout_backend_RF)
    excite = Exciting(readout_backend_DCRF, manipulation_backend_DC, (full_pt, parameters),
                      measurement_mapping={"meas_dc": "input1", "meas_rf": "demod0"}, ...)
"""
from qkit.measure.spin_suite.backends.readout_backends.RO_backend_base import RO_backend_base

_FORWARDED = ("get_sample_rate", "set_sample_rate", "set_measurement_count", "set_sample_count",
              "set_averages", "activate", "deactivate")


class Combined_readout_backend(RO_backend_base):
    def __init__(self, *backends):
        super().__init__()
        if not backends:
            raise ValueError("give at least one readout backend")
        self.backends = list(backends)
        self._owner = {}                 # measurement name -> sub-backend
        self._active = set()             # active measurement names
        self._done = set()               # sub-backends that have delivered everything in this run

        for backend in self.backends:
            for name, info in backend._registered_measurements.items():
                if name in self._owner:
                    raise ValueError(f"measurement '{name}' exists in {self._owner[name]} and {backend}")
                self._owner[name] = backend
                for method in _FORWARDED:
                    target = getattr(backend, f"{name}_{method}", None)
                    if target is not None:
                        setattr(self, f"{name}_{method}", self._forward(name, method, target))
                self.register_measurement(name, info["unit"], list(info["data_nodes"]))

    # ------------------------------------------------------------------
    def _forward(self, name, method, target):
        def call(*args, **kwargs):
            result = target(*args, **kwargs)
            if method == "activate":
                self._active.add(name)
            elif method == "deactivate":
                self._active.discard(name)
            return result
        call.__name__ = f"{name}_{method}"
        return call

    def _used_backends(self):
        """sub-backends with at least one active measurement (all of them if nothing was activated yet)"""
        used = [b for b in self.backends if any(self._owner[n] is b for n in self._active)]
        return used or list(self.backends)

    # ------------------------------------------------------------------
    def arm(self):
        self._done = set()
        for backend in self._used_backends():
            backend.arm()

    def finished(self):
        return all(backend.finished() for backend in self._used_backends())

    def read(self):
        data = {}
        for backend in self._used_backends():
            if id(backend) in self._done:
                continue                       # do not read a finished backend again (no stale data)
            part = backend.read()
            if part:
                data.update(part)
            elif backend.finished():
                self._done.add(id(backend))
        return data

    def stop(self):
        errors = []
        for backend in self.backends:          # stop everything, even if one of them fails
            try:
                backend.stop()
            except Exception as e:
                errors.append(f"{backend}: {e}")
        if errors:
            raise RuntimeError("stop failed for " + "; ".join(errors))

    def __str__(self):
        return f"{self.__class__.__name__}({', '.join(str(b) for b in self.backends)})"