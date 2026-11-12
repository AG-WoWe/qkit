# -*- coding: utf-8 -*-
"""
Manipulation backend for one or two HDAWG4 (hartwig and ludwig) in 2x2 mode.

    Ch1, Ch2, Trig1, Trig2  -> hartwig, core 0
    Ch3, Ch4, Trig3, Trig4  -> hartwig, core 1
    Ch5, Ch6, Trig5, Trig6  -> ludwig,  core 0
    Ch7, Ch8, Trig7, Trig8  -> ludwig,  core 1

Safety features:
    * Only cores that received a waveform in the last load_waveform() are started, all other
      cores are switched off, so no stale program keeps playing.
    * The core synchronisation of the HDAWG is handled here: it is switched on for the cores
      in use (if both cores of an AWG are used) and off otherwise. Synchronised cores start
      at the same time, but only once all of them are enabled.
    * Free-running cores of one AWG must have exactly the same cycle length, otherwise their
      pulses drift against each other. This is checked before the upload.
    * The sample rate must not change between building the waveform, uploading and starting.

Needs the ZI_HDAWG4 driver with upload_waveform() that adds zero waves for markers and with
start_playback(cores=...) / stop_playback(cores=...).
"""
import numpy as np

from qkit.measure.spin_suite.backends.manipulation_backends.MA_backend_base import MA_backend_base


class ZI_HDAWG4_double_backend(MA_backend_base):
    def __init__(self, hartwig, ludwig=None):
        self.hartwig = hartwig
        self.ludwig = ludwig
        self._devices = [d for d in (self.hartwig, self.ludwig) if d is not None]

        self.manage_sync = True       # let the backend switch the core synchronisation
        self.check_rates = True       # raise an error if a sample rate changed after the waveform was built

        self._active = {d: set() for d in self._devices}   # device -> cores uploaded in the last load_waveform
        self._rate_at_build = {}                           # (device, core) -> rate the waveform was sampled with (Sa/s)
        self._rate_at_load = {}                            # (device, core) -> rate at upload (Sa/s)

        # (device, core, name of the channel on that core) for every backend channel
        self._layout = {}
        for n in range(1, 9):
            device = self.hartwig if n <= 4 else self.ludwig
            if device is None:
                continue
            core = ((n - 1) % 4) // 2
            local = (n - 1) % 2 + 1
            self._layout[f"Ch{n}"] = (device, core, f"Ch{local}")
            self._layout[f"Trig{n}"] = (device, core, f"Trig{local}")

        # <name>_get_sample_rate has to exist before the channel is registered
        for name, (device, core, _) in self._layout.items():
            setattr(self, f"{name}_get_sample_rate", self._make_rate_getter(device, core))

        for prefix in ("Ch", "Trig"):
            for n in range(1, 9):
                if f"{prefix}{n}" in self._layout:
                    self.register_channel(f"{prefix}{n}", "V")

    # ------------------------------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------------------------------
    def _name(self, device):
        return "hartwig" if device is self.hartwig else "ludwig"

    def _make_rate_getter(self, device, core):
        def get_sample_rate():
            rate = device.get_sampling_rate(core=core)
            self._rate_at_build[(device, core)] = rate       # remember what the waveform is sampled with
            return rate * 1e-9
        return get_sample_rate

    @staticmethod
    def _padded_length(n):
        # the driver extends every waveform to a multiple of 16 samples (at least 32)
        return max(32, int(np.ceil(n / 16)) * 16)

    @staticmethod
    def _set_cores(device, cores, value):
        if not cores:
            return
        if value:
            device.start_playback(cores=tuple(sorted(cores)))
        else:
            device.stop_playback(cores=tuple(sorted(cores)))

    def _set_sync(self, device, active):
        # synchronised cores only start when all of them are enabled:
        # on for the cores in use (if more than one), off for the rest
        for core in (0, 1):
            on = int(core in active and len(active) > 1)
            try:
                device.daq.setInt(f"/{device.device}/awgs/{core}/synchronization/enable", on)
            except Exception as e:
                print(f"WARNING {self._name(device)}: could not set the synchronisation of core {core} ({e}). "
                      f"The cores may start at different times.")

    def _check_rate(self, device, core, reference, when):
        now = device.get_sampling_rate(core=core)
        if reference is not None and not np.isclose(now, reference, rtol=1e-9):
            message = (f"{self._name(device)} core {core}: the sample rate changed {when} "
                       f"({reference:.6g} -> {now:.6g} Sa/s). Set the prescaler before building the measurement.")
            if self.check_rates:
                raise RuntimeError(message)
            print("WARNING " + message)
        return now

    # ------------------------------------------------------------------------------------------
    # interface used by the measurement
    # ------------------------------------------------------------------------------------------
    def run(self):
        # the rate must still be the one the waveforms were uploaded for
        for device in self._devices:
            for core in self._active.get(device, set()):
                self._check_rate(device, core, self._rate_at_load.get((device, core)), "after the upload")

        # devices that wait for a trigger are armed first, the free-running one starts last
        for device in sorted(self._devices, key=lambda d: not getattr(d, "_use_trigger", False)):
            active = self._active.get(device, set())
            self._set_cores(device, {0, 1} - active, 0)
            if self.manage_sync:
                self._set_sync(device, active)
            self._set_cores(device, active, 1)

    def stop(self):
        for device in self._devices:
            self._set_cores(device, {0, 1}, 0)

    def load_waveform(self, wave_data):
        # the array is the first item of the 'samples' list
        wave_dict = {key: value["samples"][0] for key, value in wave_data.items()}

        # one wave dict per (device, core), keys renamed to Ch1/Ch2/Trig1/Trig2
        per_core = {}
        for name, array in wave_dict.items():
            if name not in self._layout:
                raise KeyError(f"Channel {name} is not available (is the second AWG connected?)")
            device, core, local = self._layout[name]
            per_core.setdefault((device, core), {})[local] = array

        self.stop()                                   # nothing plays while the waveforms are exchanged
        self._active = {device: set() for device in self._devices}
        self._rate_at_load = {}

        # --- checks before anything is uploaded ---
        cycle = {}                                    # (device, core) -> cycle length in s
        for (device, core), core_dict in per_core.items():
            lengths = {len(array) for array in core_dict.values()}
            if len(lengths) != 1:
                raise ValueError(f"{self._name(device)} core {core}: waves and markers have different lengths "
                                 f"{ {k: len(v) for k, v in core_dict.items()} }")
            rate = self._check_rate(device, core, self._rate_at_build.get((device, core)),
                                    "after the waveform was built")
            self._rate_at_load[(device, core)] = rate
            cycle[(device, core)] = self._padded_length(lengths.pop()) / rate

        for device in self._devices:
            if getattr(device, "_use_trigger", False):
                continue                              # triggered cores are re-aligned by every trigger
            cycles = {core: t for (dev, core), t in cycle.items() if dev is device}
            if len(cycles) == 2 and not np.isclose(cycles[0], cycles[1], rtol=1e-12, atol=0):
                raise ValueError(
                    f"{self._name(device)}: the two cores have different cycle lengths "
                    f"(core 0: {cycles[0]*1e6:.6f} us, core 1: {cycles[1]*1e6:.6f} us), their pulses would "
                    f"drift against each other. Use the same sampling prescaler on both cores.")

        # --- upload ---
        try:
            for (device, core), core_dict in per_core.items():
                device.upload_waveform(core, core_dict)   # adds zero waves for markers without a wave
                self._active[device].add(core)
        except Exception:
            # leave a defined state: everything stopped, nothing marked as ready
            self.stop()
            self._active = {device: set() for device in self._devices}
            self._rate_at_load = {}
            raise

        for device in self._devices:
            unused = sorted({0, 1} - self._active[device])
            if unused:
                print(f"{self._name(device)}: core(s) {unused} not used and switched off.")