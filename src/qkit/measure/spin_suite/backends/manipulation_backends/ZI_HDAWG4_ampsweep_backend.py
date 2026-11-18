"""
ZI_HDAWG4_ampsweep_backend
==========================
Plays a 2D voltage grid (e.g. a P1 x P2 video map) on one HDAWG core with a single cycle
waveform and the AWG command table: before every repetition the command table sets the
amplitudes of the two channels. Waveform memory = one cycle, independent of the grid size.

Requirements for the pulse (checked in configure()):
  * x channel proportional to the x voltage, y channel proportional to the y voltage
  * no fixed (voltage-independent) part, no cross-talk between x and y
  * marker independent of the voltages
The simplified video pulse (0 -> +V -> 0 -> -V -> 0) fulfils this.

Mapping: x -> first channel of the core (Ch1), y -> second channel (Ch2),
marker -> Trig1/Trig3 (marker 1 of wave 1) or Trig2/Trig4 (marker 1 of wave 2).

Output range: with auto_range=True (default) configure() picks the smallest HDAWG output range
that fits the grid. The range is switched in start() and restored in stop(), like the output gains.

Usage:
    backend = ZI_HDAWG4_ampsweep_backend(hartwig, trace_calls=True)
    backend.configure(pulse_cycle, params, x_key="v_P1_read_B", y_key="v_P2_read_B")
    pulse_grid = backend.readout_pulse()                    # light pulse for Exciting (windows only)
    excite = Exciting(readout_backend, backend, (pulse_grid, params), ...)
"""
import json
import time
import numpy as np
from qupulse.pulses import ForLoopPT
from qupulse.pulses.plotting import render

try:
    from .ZI_HDAWG4_double_backend import ZI_HDAWG4_double_backend
except ImportError:
    from ZI_HDAWG4_double_backend import ZI_HDAWG4_double_backend


# =====================================================================================================
# device part: waveform, command table, sequencer program
# =====================================================================================================
class HDAWGAmpSweepPlayer:
    FS_FACTOR = 1.0   # output voltage at wave = gain = 1 as fraction of the range (0.5 if range is Vpp)
    RANGES = (0.2, 0.4, 0.6, 0.8, 1.0, 2.0, 3.0, 4.0, 5.0)   # V, HDAWG output ranges

    def __init__(self, awg, core=0):
        self.daq = next(getattr(awg, a) for a in ("daq", "_daq", "daq_server", "_daq_server") if hasattr(awg, a))
        self.dev = next(getattr(awg, a).lower() for a in ("device_id", "_device_id", "device", "_device", "serial", "dev")
                        if isinstance(getattr(awg, a, None), str))
        self.core, self.base = core, f"/{self.dev}/awgs/{core}"
        self.schema = json.loads(self._get_string(f"{self.base}/commandtable/schema"))
        self.matrix = '"amplitude00"' in json.dumps(self.schema)
        self.uploaded = False
        self.target_ranges = None          # output ranges used while playing (None = keep the current ones)
        self._saved = {}

    # ---------------- helpers ----------------
    def _get_string(self, path):
        try:
            return self.daq.getString(path)
        except Exception:
            r = self.daq.get(path, flat=True)[path]
            v = r[0]["vector"] if isinstance(r, list) else r["vector"]
            v = v[0] if isinstance(v, (list, tuple)) else v
            return v if isinstance(v, str) else bytes(v).decode()

    def _range_path(self, i):
        return f"/{self.dev}/sigouts/{2*self.core + i}/range"

    def output_full_scale(self):
        return tuple(self.daq.getDouble(self._range_path(i)) * self.FS_FACTOR for i in (0, 1))

    def plan_ranges(self, v1, v2, auto=True, margin=1.05, max_ranges=None):
        """output ranges for the needed peak voltages v1 (first channel) and v2 (second channel) at the AWG,
        never above max_ranges[i] (from the AWG driver's voltage limit). auto=False keeps the current ranges.
        The ranges are applied in start() and restored in stop()."""
        current = [self.daq.getDouble(self._range_path(i)) for i in (0, 1)]
        if not auto:
            self.target_ranges = None
            return current
        out = []
        for i, v in enumerate((v1, v2)):
            need = v / self.FS_FACTOR
            top = max_ranges[i] if max_ranges else self.RANGES[-1]
            allowed = [r for r in self.RANGES if r <= top + 1e-9]
            fits = [r for r in allowed if r >= need * margin] or [r for r in allowed if r >= need]
            if not fits:
                raise ValueError(f"needs {v:.3f} V at the AWG, no allowed output range fits (max {top} V)")
            out.append(fits[0])
        self.target_ranges = out
        return out

    def _set_saving(self, path, value, kind="double"):
        """set a node and remember its old value (restored in stop())"""
        get = self.daq.getDouble if kind == "double" else self.daq.getInt
        put = self.daq.setDouble if kind == "double" else self.daq.setInt
        old = get(path)
        if abs(old - value) > 1e-9:
            self._saved.setdefault(path, (old, put))
            put(path, value)

    def prepare_outputs(self, fix=True):
        """static AWG gains must be diagonal 1 / off-diagonal 0, plain mode, no core sync"""
        issues = []
        for o in (0, 1):
            for k in (0, 1):
                path = f"{self.base}/outputs/{o}/gains/{k}"
                want = 1.0 if o == k else 0.0
                try:
                    val = self.daq.getDouble(path)
                    if abs(val - want) > 1e-6:
                        issues.append(f"{path} = {val} (want {want})")
                        if fix:
                            self._set_saving(path, want)
                except Exception:
                    pass
            try:
                path = f"{self.base}/outputs/{o}/modulation/mode"
                if self.daq.getInt(path) != 0:
                    issues.append(f"{path} != 0 (plain)")
                    if fix:
                        self._set_saving(path, 0, "int")
            except Exception:
                pass
        try:
            self._set_saving(f"{self.base}/synchronization/enable", 0, "int")
        except Exception:
            pass
        return issues

    # ---------------- build ----------------
    def program(self, wave1, wave2, mark, marker_bit, g1, g2, prescaler):
        g1, g2 = np.asarray(g1, float), np.asarray(g2, float)
        if max(np.abs(g1).max(), np.abs(g2).max()) > 1:
            raise ValueError(f"amplitude > full scale (max gain {max(np.abs(g1).max(), np.abs(g2).max()):.3f}): "
                             f"increase the output range or reduce the voltages")
        n1, n2 = len(g1), len(g2)
        dg1 = (g1[-1] - g1[0]) / (n1 - 1) if n1 > 1 else 0.0
        dg2 = (g2[-1] - g2[0]) / (n2 - 1) if n2 > 1 else 0.0
        if not (np.allclose(np.diff(g1), dg1) and np.allclose(np.diff(g2), dg2)):
            raise ValueError("grid values must be equally spaced")

        amp = lambda a, inc: {"value": float(a), "increment": bool(inc)}
        if self.matrix:
            A = lambda a1, i1, a2, i2: {"amplitude00": amp(a1, i1), "amplitude01": amp(0, False),
                                        "amplitude10": amp(0, False), "amplitude11": amp(a2, i2)}
        else:
            A = lambda a1, i1, a2, i2: {"amplitude0": amp(a1, i1), "amplitude1": amp(a2, i2)}
        W = {"waveform": {"index": 0}}
        self.table = [{"index": 0, **W, **A(g1[0], False, g2[0], False)},   # first grid point
                      {"index": 1, **W, **A(dg1,   True,  0,     True)},    # next x point
                      {"index": 2, **W, **A(g1[0], False, dg2,   True)}]    # next y row, x back to start

        n = len(wave1)
        m1, m2 = ("true", "false") if marker_bit == 0 else ("false", "true")
        row = f"repeat({n1 - 1}) {{ executeTableEntry(1); }}" if n1 > 1 else ""
        rows = f"repeat({n2 - 1}) {{ executeTableEntry(2); {row} }}" if n2 > 1 else ""
        self.seqc = (f"wave w1 = placeholder({n}, {m1}, false);\n"
                     f"wave w2 = placeholder({n}, {m2}, false);\n"
                     f"assignWaveIndex(1, w1, 2, w2, 0);\n"
                     f"while (true) {{\n  executeTableEntry(0);\n  {row}\n  {rows}\n}}\n")
        self.wave1, self.wave2 = np.asarray(wave1, float), np.asarray(wave2, float)
        self.markers = (np.asarray(mark) > 0.5).astype(np.uint16) << marker_bit
        self.prescaler = prescaler
        self.uploaded = False

    # ---------------- device ----------------
    def upload(self):
        from zhinst.core import compile_seqc
        from zhinst.utils import convert_awg_waveform
        d = self.daq
        d.setInt(f"{self.base}/enable", 0)
        d.setInt(f"{self.base}/time", self.prescaler)
        rate = 2.4e9 / 2**self.prescaler
        elf, _ = compile_seqc(self.seqc, d.getString(f"/{self.dev}/features/devtype"),
                              d.getString(f"/{self.dev}/features/options"), self.core, samplerate=rate)
        d.setVector(f"{self.base}/elf/data", elf)
        t0 = time.time()
        while not d.getInt(f"{self.base}/ready"):
            if time.time() - t0 > 30:
                raise RuntimeError("ELF upload: AWG not ready after 30 s")
            time.sleep(0.05)
        d.setVector(f"{self.base}/waveform/waves/0", convert_awg_waveform(self.wave1, self.wave2, self.markers))
        ct = {"header": {"version": self.schema.get("version", "1.0.0")}, "table": self.table}
        d.setVector(f"{self.base}/commandtable/data", json.dumps(ct))   # always after the program
        d.sync()
        status = d.getInt(f"{self.base}/commandtable/status")
        if not status & 1:
            raise RuntimeError(f"command table upload failed (status {status})")
        self.uploaded = True

    def start(self, fix_outputs=True):
        if not self.uploaded:
            raise RuntimeError("nothing uploaded")
        if self.target_ranges is not None:                  # output range for this grid (restored in stop)
            for i, r in enumerate(self.target_ranges):
                self._set_saving(self._range_path(i), r)
            self.daq.sync()
        issues = self.prepare_outputs(fix=fix_outputs)
        if issues:
            print("[ampsweep] output settings " + ("corrected" if fix_outputs else "WRONG") + ": " + "; ".join(issues))
        self.daq.setInt(f"{self.base}/single", 0)          # free running, like the qupulse backend
        self.daq.setInt(f"{self.base}/enable", 1)

    def stop(self, restore=True):
        self.daq.setInt(f"{self.base}/enable", 0)
        if restore:
            for path, (old, put) in self._saved.items():
                put(path, old)
            self._saved = {}


# =====================================================================================================
# backend for Exciting
# =====================================================================================================
class ZI_HDAWG4_ampsweep_backend(ZI_HDAWG4_double_backend):

    _OVERRIDDEN = ("build", "load", "upload", "run", "stop", "register_program", "arm_program",
                   "run_program", "remove_program", "clear_programs", "run_current_program", "load_waveform")

    def __init__(self, awg, *args, core=0, fix_output_gains=True, trace_calls=False, **kwargs):
        super().__init__(awg, *args, **kwargs)
        self.player = HDAWGAmpSweepPlayer(awg, core)
        self.awg = awg
        self.fix_output_gains = fix_output_gains
        self.trace_calls = trace_calls
        self.cfg = None
        print(f"[ampsweep] {self.player.dev} core {core}, command table schema "
              f"{self.player.schema.get('version')}, {'amplitude00/11' if self.player.matrix else 'amplitude0/1'}")
        others = sorted({n for cls in type(self).__mro__[1:] if cls is not object
                         for n, v in vars(cls).items() if callable(v) and not n.startswith("_")}
                        - set(self._OVERRIDDEN) - {"configure", "grid_pulse", "readout_pulse", "axes_info"})
        if trace_calls and others:
            print(f"[ampsweep] inherited, not replaced: {others}")

    # ---------------- configuration ----------------
    def configure(self, pulse_cycle, parameters, x_key="v_P1_read_B", y_key="v_P2_read_B",
                  x_channel="AWG_Ch1", y_channel="AWG_Ch2", marker_channel="AWG_Trig2", prescaler=0,
                  auto_range=True):
        """render one cycle with qupulse, check that it can be played as an amplitude sweep and build
        waveform, gains and command table. The grid comes from <key>_start/_stop/_inc in parameters.
        auto_range=True: pick the smallest output range that fits the grid (applied in start())."""
        p = dict(parameters)
        xv = np.arange(p[f"{x_key}_start"], p[f"{x_key}_stop"], p[f"{x_key}_inc"], dtype=float)
        yv = np.arange(p[f"{y_key}_start"], p[f"{y_key}_stop"], p[f"{y_key}_inc"], dtype=float)
        rate = 2.4e9 / 2**prescaler
        v_ref = float(max(np.abs(xv).max(), np.abs(yv).max(), 1.0))
        chans = (x_channel, y_channel, marker_channel)

        def rend(vx, vy):
            prog = pulse_cycle.create_program(parameters=dict(p, **{x_key: vx, y_key: vy}))
            dur = float(prog.duration)
            n = int(round(dur * 1e-9 * rate))
            volt = render(prog, sample_rate=rate * 1e-9)[1]
            missing = [c for c in chans if c not in volt]
            if missing:
                raise KeyError(f"channels {missing} not in the pulse (has {sorted(volt)})")
            return {c: np.asarray(volt[c][:n], float) for c in chans}, dur

        r00, dur = rend(0.0, 0.0)
        rx, _ = rend(v_ref, 0.0)
        ry, _ = rend(0.0, v_ref)
        r1, _ = rend(v_ref, v_ref)
        r2, _ = rend(2 * v_ref, 2 * v_ref)
        tol = lambda a: 1e-3 * max(np.abs(a).max(), 1e-12)
        x, y, m = chans
        problems = []
        if np.abs(r00[x]).max() > tol(rx[x]) or np.abs(r00[y]).max() > tol(ry[y]):
            problems.append("output is not 0 at 0 V (pulse has a fixed part)")
        if np.abs(rx[y]).max() > tol(ry[y]):
            problems.append(f"{y} depends on {x_key}")
        if np.abs(ry[x]).max() > tol(rx[x]):
            problems.append(f"{x} depends on {y_key}")
        if np.abs(r2[x] - 2 * r1[x]).max() > tol(r1[x]) or np.abs(r2[y] - 2 * r1[y]).max() > tol(r1[y]):
            problems.append("output not proportional to the voltage")
        if np.any((r00[m] > 0.5) != (r1[m] > 0.5)):
            problems.append("marker depends on the voltages")
        if not np.any(r1[m] > 0.5):
            problems.append("marker never high")
        if problems:
            raise ValueError("pulse cannot be played as amplitude sweep:\n  - " + "\n  - ".join(problems))

        A1, A2 = np.abs(rx[x]).max(), np.abs(ry[y]).max()          # volts at the AWG for v_ref
        w1, w2, mk = rx[x] / A1, ry[y] / A2, r1[m]
        pad = (-len(w1)) % 16
        w1, w2, mk = np.pad(w1, (0, pad)), np.pad(w2, (0, pad)), np.pad(mk, (0, pad))

        # voltage limit and allowed ranges from the AWG driver (single source of truth)
        v_peak = (np.abs(xv).max() / v_ref * A1, np.abs(yv).max() / v_ref * A2)
        outs = (2 * self.player.core + 1, 2 * self.player.core + 2)          # physical outputs 1..4
        if hasattr(self.awg, "check_voltage") and hasattr(self.awg, "max_output_range"):
            for o, v in zip(outs, v_peak):
                self.awg.check_voltage(o, v)                                 # raises above the limit
            max_r = [self.awg.max_output_range(o) for o in outs]
        else:
            print("[ampsweep] WARNING: AWG driver has no check_voltage(): voltage limit NOT checked")
            max_r = None
        # output ranges: smallest allowed range that fits the largest grid voltage of each channel
        rg1, rg2 = self.player.plan_ranges(*v_peak, auto=auto_range, max_ranges=max_r)
        fs1, fs2 = rg1 * self.player.FS_FACTOR, rg2 * self.player.FS_FACTOR
        g1, g2 = xv / v_ref * A1 / fs1, yv / v_ref * A2 / fs2
        marker_bit = 0 if marker_channel[-1] in "13" else 2
        self.player.program(w1, w2, mk, marker_bit, g1, g2, prescaler)

        t_cycle = len(w1) / rate * 1e9
        self.cfg = dict(pulse_cycle=pulse_cycle, parameters=p, x_key=x_key, y_key=y_key,
                        x_values=xv, y_values=yv, t_cycle_ns=t_cycle, t_cycle_qupulse_ns=dur,
                        prescaler=prescaler, n_windows=len(xv) * len(yv), output_ranges=(rg1, rg2))
        if abs(t_cycle - dur) > 1e9 / rate * 16:
            print(f"[ampsweep] WARNING: cycle {t_cycle:.0f} ns on the AWG vs {dur:.0f} ns in qupulse")
        print(f"[ampsweep] grid {len(yv)} ({y_key}) x {len(xv)} ({x_key}), cycle {t_cycle/1e3:.2f} us "
              f"({len(w1)} samples at {rate/1e6:g} MSa/s), {len(xv)*len(yv)*t_cycle/1e6:.1f} ms per grid, "
              f"max {np.abs(g1).max()*fs1*1e3:.1f} / {np.abs(g2).max()*fs2*1e3:.1f} mV at the AWG, "
              f"output range {rg1:g} / {rg2:g} V")
        return self

    def grid_pulse(self):
        """qupulse grid (y outer, x inner) matching the configured sweep (full pulse, slow in Exciting)"""
        c = self._need_cfg()
        xk, yk = c["x_key"], c["y_key"]
        inner = ForLoopPT(c["pulse_cycle"], xk, (f"{xk}_start", f"{xk}_stop", f"{xk}_inc"))
        self._light_readout = False
        return ForLoopPT(inner, yk, (f"{yk}_start", f"{yk}_stop", f"{yk}_inc"))

    def readout_pulse(self, channels=("AWG_Ch1", "AWG_Ch2", "AWG_Trig2"), window="measurement"):
        """Lightweight pulse for Exciting: the same number and length of measurement windows as the
        configured grid, but each cycle only t_meas long and all channels at 0. Exciting renders and
        instantiates this instead of the full grid; the AWG plays the real grid from the command table."""
        c = self._need_cfg()
        from qupulse.pulses import RepetitionPT, PointPT, AtomicMultiChannelPT
        t_meas = float(c["parameters"]["t_meas"])            # ns, as a number (no expression)
        cycle = AtomicMultiChannelPT(
            *[PointPT([(0, 0), (t_meas, 0, "hold")], channel_names=(ch,)) for ch in channels],
            measurements=[(window, 0, t_meas)])
        self._light_readout = True
        return RepetitionPT(cycle, c["n_windows"])

    def axes_info(self):
        c = self._need_cfg()
        return {"x_key": c["x_key"], "y_key": c["y_key"],
                "P1_uV": c["x_values"].tolist(), "P2_uV": c["y_values"].tolist(),
                "order": f"{c['y_key']} outer, {c['x_key']} inner", "t_cycle_ns": c["t_cycle_ns"],
                "prescaler": c["prescaler"], "output_ranges_V": list(c["output_ranges"]),
                "player": "HDAWG command table (ZI_HDAWG4_ampsweep_backend)"}

    # ---------------- internal ----------------
    def _need_cfg(self):
        if self.cfg is None:
            raise RuntimeError("call configure(pulse_cycle, parameters, ...) first")
        return self.cfg

    def _trace(self, name, a=(), k=None):
        if self.trace_calls:
            print(f"[ampsweep] {name}(" + ", ".join([type(x).__name__ for x in a] + list((k or {}).keys())) + ")")

    def _check_program(self, args, kwargs):
        """compare duration of a qupulse program handed over by Exciting with the configured grid"""
        if getattr(self, "_light_readout", False):
            return
        c = self.cfg
        for obj in list(args) + list((kwargs or {}).values()):
            dur = getattr(obj, "duration", None)
            if dur is None or not hasattr(obj, "children"):
                continue
            expected = c["n_windows"] * c["t_cycle_qupulse_ns"]
            if abs(float(dur) - expected) > 1:
                print(f"[ampsweep] WARNING: program {float(dur)/1e6:.3f} ms, configured grid {expected/1e6:.3f} ms "
                      f"-> did you pass backend.readout_pulse() or grid_pulse() to Exciting?")

    def _upload(self, name, a, k):
        self._trace(name, a, k)
        self._need_cfg()
        self._check_program(a, k)
        if not self.player.uploaded:
            self.player.upload()
            print("[ampsweep] program, waveform and command table uploaded")

    def _start(self, name, a, k):
        self._trace(name, a, k)
        if not self.player.uploaded:
            self._upload(name, a, k)
        self.player.start(fix_outputs=self.fix_output_gains)

    # ---------------- interface used by Exciting (both naming styles) ----------------
    def build(self, *a, **k):            self._trace("build", a, k); self._need_cfg(); self._check_program(a, k)
    def load(self, *a, **k):             self._upload("load", a, k)
    def upload(self, *a, **k):           self._upload("upload", a, k)
    def register_program(self, *a, **k): self._upload("register_program", a, k)
    def arm_program(self, *a, **k):      self._upload("arm_program", a, k)
    def run(self, *a, **k):              self._start("run", a, k)
    def run_program(self, *a, **k):      self._start("run_program", a, k)
    def run_current_program(self, *a, **k): self._start("run_current_program", a, k)
    def stop(self, *a, **k):             self._trace("stop", a, k); self.player.stop(restore=True)
    def remove_program(self, *a, **k):   self._trace("remove_program", a, k); self.player.stop(restore=True)
    def clear_programs(self, *a, **k):   self._trace("clear_programs", a, k); self.player.stop(restore=True)
    def load_waveform(self, *a, **k):    self._upload("load_waveform", a, k)