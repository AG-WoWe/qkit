# -*- coding: utf-8 -*-
"""
Created on Mon Ocotber 2026

@author: Daniel

Manipulation backend for two HDAWG4 (hartwig and ludwig) in 2x2 mode.

    Ch1, Ch2, Trig1, Trig2  -> hartwig, core 0
    Ch3, Ch4, Trig3, Trig4  -> hartwig, core 1
    Ch5, Ch6, Trig5, Trig6  -> ludwig,  core 0
    Ch7, Ch8, Trig7, Trig8  -> ludwig,  core 1
"""
import numpy as np

from qkit.measure.spin_suite.backends.manipulation_backends.MA_backend_base import MA_backend_base


class ZI_HDAWG4_backend(MA_backend_base):
    def __init__(self, hartwig, ludwig):
        self.hartwig = hartwig
        self.ludwig = ludwig

        # (device, core, name of the channel on that core) for every backend channel
        self._layout = {}
        for n in range(1, 9):
            device = self.hartwig if n <= 4 else self.ludwig
            core = ((n - 1) % 4) // 2
            local = (n - 1) % 2 + 1
            self._layout[f"Ch{n}"] = (device, core, f"Ch{local}")
            self._layout[f"Trig{n}"] = (device, core, f"Trig{local}")

        # <name>_get_sample_rate has to exist before the channel is registered
        for name, (device, core, _) in self._layout.items():
            setattr(self, f"{name}_get_sample_rate", self._make_rate_getter(device, core))

        for n in range(1, 9):
            self.register_channel(f"Ch{n}", "V")
        for n in range(1, 9):
            self.register_channel(f"Trig{n}", "V")

    @staticmethod
    def _make_rate_getter(device, core):
        def get_sample_rate():
            return device.get_sampling_rate(core=core) * 1e-9
        return get_sample_rate

    def run(self):
        self.hartwig.start_playback()
        self.ludwig.start_playback()

    def stop(self):
        self.hartwig.stop_playback()
        self.ludwig.stop_playback()

    def load_waveform(self, wave_data):
        # the array is the first item of the 'samples' list
        wave_dict = {key: value["samples"][0] for key, value in wave_data.items()}

        # one wave dict per (device, core), keys renamed to Ch1/Ch2/Trig1/Trig2
        per_core = {}
        for name, array in wave_dict.items():
            device, core, local = self._layout[name]
            per_core.setdefault((device, core), {})[local] = array

        # forget which cores were uploaded earlier (used by start_playback if you patched it)
        for device in (self.hartwig, self.ludwig):
            if hasattr(device, "_uploaded_cores"):
                device._uploaded_cores = set()

        for device, core, label in ((self.hartwig, 0, "hartwig core 0"),
                                    (self.hartwig, 1, "hartwig core 1"),
                                    (self.ludwig, 0, "ludwig core 0"),
                                    (self.ludwig, 1, "ludwig core 1")):
            core_dict = per_core.get((device, core))
            if not core_dict:
                print(f"No waveform provided for {label}.")
                continue
            self._fill_missing_waves(core_dict)
            device.upload_waveform(core, core_dict)

    @staticmethod
    def _fill_missing_waves(core_dict):
        # a marker without a wave on the same output needs a (zero) wave to play on
        for k in ("1", "2"):
            if f"Trig{k}" in core_dict and f"Ch{k}" not in core_dict:
                core_dict[f"Ch{k}"] = np.zeros(len(core_dict[f"Trig{k}"]))