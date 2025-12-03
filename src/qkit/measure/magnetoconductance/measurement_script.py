''' The measurement script classes measure1D and measure2D are able to describe and run
    1D or 2D measurements. Therefore several vars must be set. These variables describe
    the working points (wp) to sweep between during the measurement.
    For a 1D measurement (measure1D) only two wps are used, one for the start and one for the stop
    of a sweep. For the 2D measurement (measure2D) these start and stop working point can change after
    each sweep by stepping a parameter of the wps, creating a 2D map with step and sweep parameter.
    The measurements can run with and without lockin signal, to disable the lockin its amplitude
    needs to be set to zero.

    *Required keywords:
        -adwin:  *adwin instrument

    (all below listed variables are saved as dictionaries,
    some vars vaulues are restricted to certain values,
    these are defined in the init of the class as valid values)

        -wp_params: *including all parameters that are needed to define a wp
                    *params of wp_params:
                        +phi, theta, psi, bp, bt, mode (vector3d params)
                        +vd, vg (bias and gate voltage)
                    *more informations in WorkingPoint class
                    *if a param is used as step or sweep var
                     it is not needed, because the value will be overwritten

        -sweep:     *vars to generate virtual sweep values array
                    *name, start, stop, unit
                    *optional: rate, duration
                    *if no rate or duration is set, valids['maxrate'] of sweep var will be used

        -step:      *vars to generate step values array (only needed for 2D measurement)
                    *name, start, stop, stepsize, unit
                    *stop value is incuded in step values array

        -lockin:    *vars for the lockin signal, must be set even if no lockin signal should be used,
                     because of adwin driver (will be fixed later, for now set amplitude to zero for no lockin)
                    *freq, amp, tao, init_time, (sample_rate), phase, maf

        -inputs:    *inputs to measure and return from adwin instrument
                    *raw, inph, quad (for "inph" and "quad" is a lockin signal required)
                    *optional: retrace, difference (default=False, describes if retrace is measured/
                    difference is calculated)
                    *if "save" is set in data, needed inputs will be generated automatically

        -save:      *vars that should be saved from the measurement
                    *traces (raw, inph, quad, amp, phase), inputs (trace, retrace, difference)

        -plot:      *vars that should be plotted immediately from the measurement (same structure as "save")
                    *traces and inputs in "plot" will automatically be added to "save",
                     cause its required to save the data to plot it with qviewkit.

    *Optional keywords:
        -readout_freq:  *frequency for live-readout, if set to zero live-readout is disabled

        -h5_path:       *path of .h/hdf5 file to extract and load measurement config
                         from previous measurement

                     
    *ToDo:   
        -B to zero, all to zero (can be done very easily manual)

'''

import tkinter as tk
import threading
import json
import time
import logging as log
import numpy as np
import h5py
from qkit.measure.magnetoconductance.spin_tune_ST import Tuning_ST
from qkit.drivers.adwinlib.working_point import WorkingPoint
from qkit.drivers.adwin_spin_transistor import adwin_spin_transistor
from qkit.drivers.adwin_spin_transistor_virtual import adwin_spin_transistor_virtual


# ----------------------------- Utilities & Errors -----------------------------

class SettingsError(Exception):
    """Raise Error if settings for Measurement script are invalid"""

def calc_r(x, y):
    ''' calc func for amplitude from lockin'''
    return np.sqrt(np.square(x) + np.square(y))

def calc_theta(x, y):
    ''' calc func for phase shift from lockin'''
    return np.arctan2(y, x)


# ----------------------------- Base Class -------------------------------------

class Measure1D:
    """Base class for 1D measurements

    Subclasses must implement:
      - prepare_measurement_datasets()
      - set_parameter()
      - add_view()
      - start_measurement()

    Optional (override if needed):
      - generate_steps()  (only for 2D)
    """

    def __init__(self, adwin: adwin_spin_transistor|adwin_spin_transistor_virtual, readout_freq = 0, h5_path: str | None = None, **kwargs):
        # Valid maps & limits
        self.valids = {
            'step': {'vg', 'vd', 'N', 'bt', 'bp', 'phi', 'psi', 'theta'},
            'sweep': {'vg', 'vd', 'bt', 'bp', 'phi', 'psi', 'theta', 'time'},
            'mode': {'normal', 'sweep'},
            'traces': {'trace', 'retrace', "difference"},
            'inputs': {'raw', 'inph', 'quad'},
            'calc': {'amp': ['inph', 'quad'], 'phase': ['inph', 'quad']},
            'calc_func': {'amp': calc_r, 'phase': calc_theta},
            'maxrate': {'bx': 0.3, 'by': 0.3, 'bz': 0.3, 'bp': 0.3,
                        'bt': 0.3, 'vg': 0.1, 'vd': 0.1, 'time': 1e6},
            'unit': {'inph': 'S', 'quad': 'S', 'raw': 'I', 'amp': 'S', 'phase': 'rad'},
        }

        self.setup_params()
        self.def_setter()

        # Load config from h5 file if path given
        if h5_path is not None:
            self.load_config(h5_path)
        # Set readout frequency for sweep (default: 0 -> readout after sweep finished)
        self._sweep_readout_freq = readout_freq
        # Allow passing dicts like sweep= {...}, step={...}, etc.
        self.set(**kwargs)

        # Instruments & tuning
        self.adwin = adwin
        self.tune = Tuning_ST()
        self.tune.qviewkit_singleInstance = True

        # Working points (initialized after adwin available)
        adwin_outputs = self.adwin.list_connected_outputs()
        self.wp_start = WorkingPoint(adwin_outputs, magnet='vector3d')
        self.wp_stop = WorkingPoint(adwin_outputs, magnet='vector3d')

        self.generate_sweep()       # generate sweep values

        # create stop event
        self.stop_event = threading.Event()

        # create GUI-Window
        self.gui_window = tk.Tk()

    # ----------------------- Configuration -----------------------

    def setup_params(self):
        ''' setup params for the measurement'''
        self._wp_params = {'vd': 0, 'vg': 0, 'theta': 0, 'phi': 0, 'psi': 0,
                           'bp': 0, 'bt': 0, 'mode': None}
        self._sweep = {'name': None, 'start': None, 'stop': None,
                       'unit': None, 'rate': None, 'duration': None,
                       'values': None, 'wait_time': None}
        # self._step = {'name': None, 'start': None, 'stop': None, 'unit': None,
        #               'step_size': None, 'values': None, 'init_time': None,
        #               'wait_time': None}
        self._pulse = {'name': 'vd', 'amp': None, 'rate': None, 'unit': 'V',
                       'delay_time': 0.0, 'wait_time': 0.0, 'traces': []}
        self._trigger = {'pulse': set(), 'sweep': set(), 'delay_time':0.0}
        self._lockin = {'freq': None, 'amp': None, 'tao': None,
                        'init_time': None, 'sample_rate': 500e3,
                        'phase': None, 'maf': None}
        self._inputs = {'retrace': False, 'difference': False, 'inputs': []}
        self._plot = {'inph': set(), 'quad': set(), 'raw': set(), 'amp': set(), 'phase': set()}
        self._save = {'inph': set(), 'quad': set(), 'raw': set(), 'amp': set(), 'phase': set()}
        self._temp = {}
        self._plot_dss = []

    def def_setter(self):
        ''' define setter funcs for measurement config params'''
        self.set_functions = {
            'wp_params': self.set_wp_params,
            'sweep': self.set_sweep,
            'step': self.set_step,
            'pulse': self.set_pulse,
            'trigger': self.set_trigger,
            'lockin': self.set_lockin,
            'plot': self.set_plot,
            'save': self.set_save}

    # ----------------------- Build/Activate the pipeline -----------------------

    def init_measurement(self):
        ''' genererate measurement setup'''
        self.add_saves()            # generate data save and temp dicts
        self.add_inputs()           # generate ADwin inputs

        self.start_lockin()         # start lockin signal
        self.update_lockin()        # get real lockin data from adwin
        
        self.init_wps()             # init start and stop wp of first sweep
        self.sweep_to_startpoint()  # start sweep to the first wp
        
        self.create_inputs()        # create a dict of the input nodes
        self.register_measurement() # register measure function
        self.register_trigger()     # register trigger function
        self.set_node_bounds()      # create bounds for input variables
        self.activate_measurement() # activate measurement
        self.activate_trigger()     # activate trigger
        self.set_parameter()        # set x/y coordinate parameter (subclass specific)
        self.prepare_measurement_datasets()  # subclass specific
        self.prepare_measurement_datafile()

        self.show_plots()           # determine names from datasets to plot
        self.add_view()             # add view datasets (subclass specific)



    # ----------------------- Trigger functions -----------------------

    def trigger_trace(self):
        ''' trigger trace sweep if live readout and initialize data dict'''
        self.trace = {}
        direction = 1
        if 'trace' in self._trigger['pulse']:
            self.adwin.send_trigger()
        if 'trace' in self._pulse.get('traces', []):
            time.sleep(self._pulse['delay_time'])
            # pulse vd before trace measurement
            pulse = self._pulse['name']
            temp = self.wp_start.outs[pulse]
            self.wp_start.set(**{pulse: self._pulse['amp']+temp})
            self._pulse['duration'] = self._pulse['amp'] / self._pulse['rate']
            self.adwin.sweep(self.wp_start.outs, duration=self._pulse['duration'], wait=True, clearFIFO=True)
            time.sleep(self._pulse['wait_time'])
            self.wp_start.set(**{pulse: temp})
            self.adwin.sweep(self.wp_start.outs, duration=self._pulse['duration'], wait=True, clearFIFO=True)
        if 'trace' in self._trigger['sweep']:
            self.adwin.send_trigger()

        if self._sweep_readout_freq == 0:
            pass
        else:
            self.adwin.sweep(self.wp_stop.outs, duration=self._sweep['duration'], wait=False, clearFIFO=False)
        return direction

    def trigger_retrace(self):
        ''' trigger retrace sweep if live readout and initialize data dict'''
        self.retrace = {}
        direction = -1
        if 'retrace' in self._trigger['pulse']:
            self.adwin.send_trigger()
        if 'retrace' in self._pulse.get('traces', []):
            time.sleep(self._pulse['delay_time'])
            # pulse vd before trace measurement
            pulse = self._pulse['name']
            temp = self.wp_stop.outs[pulse]
            self.wp_stop.set(**{pulse: self._pulse['amp']+temp})
            self._pulse['duration'] = self._pulse['amp'] / self._pulse['rate']
            self.adwin.sweep(self.wp_stop.outs, duration=self._pulse['duration'], wait=True, clearFIFO=True)
            time.sleep(self._pulse['wait_time'])
            self.wp_stop.set(**{pulse: temp})
            self.adwin.sweep(self.wp_stop.outs, duration=self._pulse['duration'], wait=True, clearFIFO=True)
        if 'retrace' in self._trigger['sweep']:
            self.adwin.send_trigger()

        if self._sweep_readout_freq == 0:
            pass
        else:
            self.adwin.sweep(self.wp_start.outs, duration=self._sweep['duration'], wait=False, clearFIFO=False)
        return direction
    
    def trigger_difference(self):
        ''' trigger difference calculation, only needed for live readout, to match triggers with measurements/calculations'''
        self.difference = {}
        direction = 1
        return direction

    # ----------------------- Measurement functions -----------------------

    def measure_trace(self):
        ''' measure trace and generate data dict'''
        
        # sleep for wait_time if set up
        if self._sweep['wait_time']:
            time.sleep(self._sweep['wait_time'])

        samples = len(self._sweep['values'])
        if self._sweep_readout_freq == 0:
            if self._sweep['name'] == 'time':
                trace = self.adwin.measure(duration=self._sweep['duration'])
            else:
                trace = self.adwin.sweep_measure(self.wp_stop.outs,
                                             duration=self._sweep['duration'])
            trace = {key: self.correct_len(val, samples) for key, val in trace.items() if val is not None}
        else:
            trace = self.adwin._fetch_data_from_fifos()
        return self.calc_trace_saves(trace,'trace')

    def measure_retrace(self):
        ''' measure retrace and generate data dict'''
        
        # sleep for wait_time if set up
        if self._sweep['wait_time']:
            time.sleep(self._sweep['wait_time'])

        if self._sweep_readout_freq == 0:
            if self._sweep['name'] == 'time':
                retrace = self.adwin.measure(duration=self._sweep['duration'])
            else:
                retrace = self.adwin.sweep_measure(self.wp_start.outs,
                                             duration=self._sweep['duration'])
            samples = len(self._sweep['values'])
            retrace = {key: self.correct_len(val, samples) for key, val in retrace.items() if val is not None}
        else:
            retrace = self.adwin._fetch_data_from_fifos()
        return self.calc_trace_saves(retrace,'retrace')

    def calc_trace_saves(self, data, trace):
        ''' calculate and return saves with measured data of given trace or retrace'''
        # temp contains inputs required to calcluate all save variables
        temp = {}
        # first handle all the direct inputs
        for meas, traces in self._temp.items():
            if meas in self.valids['inputs']:
                if isinstance(data[meas], np.ndarray):
                    temp[f'{meas}_{trace}'] = data[meas]
        # then handle all input to be calculated from the direct inputs
        for meas, traces in self._temp.items():
            if meas in self.valids['calc']:
                func = self.valids['calc_func'][meas]
                args = self.valids['calc'][meas]
                if temp.get(f'{args[0]}_{trace}', None) is not None and temp.get(f'{args[1]}_{trace}', None) is not None:
                    calcs = func(temp.get(f'{args[0]}_{trace}'),
                          temp.get(f'{args[1]}_{trace}'))
                    if isinstance(calcs, np.ndarray):
                        temp[f'{meas}_{trace}'] = calcs
        # save temp saves for difference calculations
        match trace:
            case 'trace':
                if self._sweep_readout_freq == 0:
                    self.trace = temp
                else:
                    for key, val in temp.items():
                        self.trace[key] = np.append(self.trace.get(key, np.empty((0,))),val)
            case 'retrace':
                if self._sweep_readout_freq == 0:
                    self.retrace = temp
                else:
                    for key, val in temp.items():
                        self.retrace[key] = np.append(self.retrace.get(key, np.empty((0,))),val)

        # Put the data to be saved in the save to return
        save = {}
        for meas, traces in self._save.items():
            if trace in traces:
                if temp.get(f'{meas}_{trace}', None) is not None and not None in temp[f'{meas}_{trace}']:
                    save[f'{meas}_{trace}'] = temp[f'{meas}_{trace}']
        return save
    

    def calc_difference(self):
        ''' calculate difference of last trace and retrace'''
        # Put the data to be saved in the save to return
        save = {}
        for meas, traces in self._save.items():
            if "difference" in traces:
                if len(self.trace[f'{meas}_trace']) == len(self.retrace[f'{meas}_retrace']):
                    save[f'{meas}_difference'] = np.flip(self.retrace[f'{meas}_retrace']) - self.trace[f'{meas}_trace']
                elif len(self.trace[f'{meas}_trace']) < len(self.retrace[f'{meas}_retrace']):
                    n = len(self.trace[f'{meas}_trace'])
                    save[f'{meas}_difference'] = np.flip(self.retrace[f'{meas}_retrace'])[:n] - self.trace[f'{meas}_trace']
                elif len(self.trace[f'{meas}_trace']) > len(self.retrace[f'{meas}_retrace']):
                    n = len(self.retrace[f'{meas}_retrace'])
                    save[f'{meas}_difference'] = np.flip(self.retrace[f'{meas}_retrace']) - self.trace[f'{meas}_trace'][:n]
        return save


    def correct_len(self, trace, samples):
        ''' If the length of a trace is not exactly what is expected, either
            the redundant samples are removed (, or the last sample is copied
            until the trace is full !Not possible right now!).
            The discrepancy is usally +-2 samples and therefore negligable '''
        if self._sweep_readout_freq == 0:
            n = len(trace)
            if n != samples:
                log.warning(f'Correcting length from {n} to {samples} samples!')
        else:
            assert Exception("correct_len only works for non-live readout!")

        if n > samples:
            return trace[:samples]
        if n == samples:
            return trace
        if n < samples:
            diff = samples - n
            return np.append(trace, [trace[-1]] * diff)

    # ----------------------- ADwin & lock‑in -----------------------

    def update_lockin(self):
        ''' updates the sample rate and lockin frequency data in the script
        with real data readout from adwin -> no new lockin signal'''
        self.set_lockin(**{'freq': self.adwin.get_lockin_frequency(),
                           'sample_rate':self.adwin.get_sample_rate()})

    def start_lockin(self):
        ''' start lockin signal'''
        self.adwin.init_measurement(
            sample_rate=self._lockin['sample_rate'],
            bias=self.get_bias(),
            inputs=self._inputs['inputs'],
            frequency=self._lockin['freq'],
            amplitude=self._lockin['amp'],
            phase=self._lockin['phase'],
            tao=self._lockin['tao'],
            maf=self._lockin['maf']
            )
        if self._lockin['init_time']:
            time.sleep(self._lockin['init_time'])

    # ----------------------- Sweep & steps -----------------------

    def sweep_to_startpoint(self):
        ''' start sweep from adwin outputs to the first wp of the measurement'''
        outs_start = self.adwin.read_outputs(out_format='qty', select='connected')
        # Find the sweep time to the first wp of the measurement by
        # comparing the necessary sweep times for each output
        sweep_time = 0.01
        for key, val in self.wp_start.outs.items():
            duration = abs(val - outs_start[key]) / self.valids['maxrate'][key]
            sweep_time = max(sweep_time, duration)
        log.info(f"Sweeping to start point in {sweep_time:.1f}s!")
        self.adwin.sweep(self.wp_start.outs, duration=sweep_time)

# ------------------- Input creation & registration via tune -------------------

    def set_parameter(self):
        ''' prepare x parameter for measurement'''
        self.tune.set_x_parameters(self._sweep['values'], self._sweep['name'], None, self._sweep['unit'])
        self._x_parameter = self.tune._x_parameter

    def create_inputs(self):
        ''' create dictionary for measurement inputs with unit'''
        self.inputs_dict = {}
        for key, val in self._save.items():
            for key1 in val:
                self.inputs_dict[f'{key}_{key1}'] = self.valids['unit'][key]

    def set_node_bounds(self):
        ''' set bounds for data input dict'''
        for key in self.inputs_dict:
            if 'retrace' in key:
                self.tune.set_node_bounds('measure_retrace', key, -10e9, 10e9)
            elif 'trace' in key:
                self.tune.set_node_bounds('measure_trace', key, -10e9, 10e9)
            elif "difference" in key:
                self.tune.set_node_bounds('calc_difference', key, -10e9, 10e9)

    def register_trigger(self):
        ''' register triggers'''
        self.tune.register_trigger('trigger_trace', self.trigger_trace)
        if self._inputs['retrace']:
            self.tune.register_trigger('trigger_retrace', self.trigger_retrace)
        if self._inputs["difference"]:
            self.tune.register_trigger('trigger_difference', self.trigger_difference)

    def register_measurement(self):
        ''' register measurement with needed data input dict'''
        self.tune.register_measurement('measure_trace', self.inputs_dict, self.measure_trace)
        if self._inputs['retrace']:
            self.tune.register_measurement('measure_retrace', self.inputs_dict, self.measure_retrace)
        if self._inputs["difference"]:
            self.tune.register_measurement('calc_difference', self.inputs_dict, self.calc_difference)

    def activate_trigger(self):
        ''' activate trigger'''
        self.tune.activate_trigger('trigger_trace')
        if self._inputs['retrace']:
            self.tune.activate_trigger('trigger_retrace')
        if self._inputs["difference"]:
            self.tune.activate_trigger('trigger_difference')

    def activate_measurement(self):
        ''' activate measurement'''
        self.tune.activate_measurement('measure_trace')
        if self._inputs['retrace']:
            self.tune.activate_measurement('measure_retrace')
        if self._inputs["difference"]:
            self.tune.activate_measurement('calc_difference')

    def prepare_measurement_datafile(self):
        ''' prepare .hdf/h5 file for measurement'''
        self.tune._prepare_measurement_file(self.ds)

    def prepare_measurement_datasets(self):
        ''' prepare datasets for measurement'''
        self.ds = self.tune.multiplexer.prepare_measurement_datasets([self._x_parameter])

    def start_measurement(self):
        ''' save measurement config, create emergency stop button
            and start activated measurement'''
        # save config in .hdf5 file
        self.save_config()
        if self._sweep_readout_freq != 0:
            self.gui_window.title("Measurement running")

            # Add label and button
            label = tk.Label(self.gui_window, text="Measurement running...\nClick to stop")
            label.pack(padx=40, pady=20)
            stop_button = tk.Button(self.gui_window, text="Stop", command=self.stop_measurement, bg="red", fg="white")
            stop_button.pack(padx=40, pady=20)

            # start measurement in separate thread
            t = threading.Thread(target=self.tune.measure1D, kwargs={
                    'data_to_show': self._plot_dss,
                    'readout_dur': 1/self._sweep_readout_freq if self._sweep_readout_freq != 0 else 0,
                    'stop_event': self.stop_event})
            t.start()

            # start GUI
            self.gui_window.mainloop()
        else:
            print("Plot the following datasets: ", self._plot_dss)
            self.tune.measure1D(data_to_show=self._plot_dss, readout_dur=1/self._sweep_readout_freq if self._sweep_readout_freq != 0 else 0,
                                stop_event=self.stop_event)

    def stop_measurement(self):
        ''' stop measurement'''
        self.adwin.stop_sweep()
        self.stop_event.set()
        self.gui_window.destroy()

    def end_measurement(self):
        ''' end measurement'''
        self.adwin.stop_measurement()
        self.tune._qvk_process.terminate()

    # ----------------------- Working points -----------------------

    def init_wps(self):
        ''' Initialize start and stop working points for map '''
        # set start and stop wp with current bias and magnet
        self.wp_start.set(**self._wp_params)
        self.wp_stop.set(**self._wp_params)
        # set start and stop of sweep var
        self.wp_start.set(**{self._sweep['name'] : self._sweep['start']})
        self.wp_stop.set(**{self._sweep['name'] : self._sweep['stop']})

    def set_start_wp(self,**kwargs):
        ''' setter function for start working point of sweep'''
        self.wp_start.set(**kwargs)

    def set_stop_wp(self,**kwargs):
        ''' setter function for stop working point of sweep'''
        self.wp_stop.set(**kwargs)

    # ----------------------- Sweep value generation -----------------------

    def generate_sweep(self):
        ''' generate steps for sweep variable if possible'''
        # if there is not start AND stop values for the sweep given
        if None in [self._sweep['start'], self._sweep['stop']]:
            # check if the sweep variable is time
            if self._sweep['name'] == 'time':
                self._sweep['start'] = 0
                self._sweep['stop'] = self._sweep['duration']
            else:
                raise SettingsError
        # if rate is given, calculate duration and check maxrate
        if self._sweep['rate'] is not None:
            if self.valids['maxrate'][self._sweep['name']] < self._sweep['rate']:
                log.warning("Sweep rate exceeds maximum!")
                raise SettingsError
            duration = abs(self._sweep['stop'] - self._sweep['start']) / self._sweep['rate']
            self._sweep['duration'] = duration
            log.info(f"Set sweep duration to {duration}")
        # if duration is given check maxrate
        elif self._sweep['duration'] is not None:
            rate = abs(self._sweep['stop'] - self._sweep['start']) / self._sweep['duration']
            if self.valids['maxrate'][self._sweep['name']] < rate:
                log.warning("Sweep rate exceeds maximum!")
                raise SettingsError
        else:
            raise SettingsError
        # calculate sweep values array
        samples = round(self._sweep['duration'] * self._lockin['sample_rate'])
        sweep_values = np.linspace(self._sweep['start'], self._sweep['stop'], samples, dtype=np.float32)
        if len(sweep_values) >= 1:
            self._sweep['values'] = sweep_values
        else:
            raise SettingsError('No sweep values planned for this measurement!')
        log.info("Generated sweep values!")


    # ----------------------- Data save & input generation -----------------------

    def add_saves(self):
        ''' generate save and temp dicts from plot and save dict'''
        # first add all plot traces to save dict
        for meas, traces in self._plot.items():
            self._save[meas].update(traces)
        # then generate temp dict from save dict
        for meas, traces in self._save.items():
            if traces:
                # add meas to temp
                self._temp[meas] = traces
                # if calcuable, add dependencies to temp
                if meas in self.valids['calc']:
                    for dep in self.valids['calc'][meas]:
                        try:
                            self._temp[dep].update(self._save[meas])
                        except KeyError:
                            self._temp[dep] = self._save[meas]

    def add_inputs(self):
        ''' generate adwin inputs'''
        # add all direct inputs from temp to inputs dict
        for key, val in self._temp.items():
            if key in self.valids['inputs'] and val:
                if key not in self._inputs['inputs']:
                    self._inputs['inputs'].append(key)
        if any(s in str(self._temp) for s in ['retrace', 'difference']):
            self._inputs['retrace'] = True
        if any(s in str(self._temp) for s in ["difference"]):
            self._inputs['difference'] = True

    # ----------------------- Plots & view addition -----------------------
    
    def show_plots(self):
        ''' create list of datasets to plot'''
        plotted_data = []
        for meas, traces in self._plot.items():
            for trd in traces:
                match trd:
                    case 'trace':
                        plotted_data.append(f'measure_trace.{meas}_{trd}')
                    case 'retrace':
                        plotted_data.append(f'measure_retrace.{meas}_{trd}')
                    case 'difference':
                        plotted_data.append(f'calc_difference.{meas}_{trd}')
        self._plot_dss = plotted_data or None

    def add_view(self):
        ''' add 1D view trace and retrace in one plot'''
        for key in self.inputs_dict:
            if 'retrace' in key:
                view = self.tune._data_file.add_view(
                    name=key.replace("_retrace", ""),
                    x=self.tune._coordinates[self._x_parameter.name],
                    y=self.tune._datasets['measure_retrace.' + key]
                )
                view.add(
                    x=self.tune._coordinates[self._x_parameter.name],
                    y=self.tune._datasets['measure_trace.' + key.replace("retrace", "trace")]
                )
            if "difference" in key:
                self.tune._data_file.add_view(
                    name=key,
                    x=self.tune._coordinates[self._x_parameter.name],
                    y=self.tune._datasets['calc_difference.' + key]
                )

    # ----------------------- Getters/Setters & serialization -----------------------

    def get_wp_params(self):
        ''' getter for working point params'''
        return self._wp_params
    
    def get_bias(self):
        ''' getter for bias voltage'''
        return self._wp_params['vd']

    def get_step(self):
        raise NotImplementedError('Step getting not implemented in 1D measurement!')

    def get_sweep(self):
        ''' getter for sweep vars'''
        return {k: v for k, v in self._sweep.items() if k != 'values'}

    def get_lockin(self):
        ''' getter for lockin params'''
        return self._lockin
    
    def get_pulse(self):
        ''' getter for pulse params'''
        return self._pulse

    def get_trigger(self):
        ''' getter for save dict'''
        return {pos: list(traces) for pos, traces in self._trigger.items()}
    
    def get_inputs(self):
        ''' getter for inputs of adwin'''
        return self._inputs

    def get_plot(self):
        ''' getter for plot dict'''
        return {m: list(traces) for m, traces in self._plot.items()}

    def get_save(self):
        ''' getter for save dict'''
        return {m: list(traces) for m, traces in self._save.items()}

    def set(self, **kwargs):
        ''' general setter function for all vars'''
        for key, val in kwargs.items():
            if key in self.set_functions:
                self.set_functions[key](**val)
            else:
                log.error(f'{self} has no var called {key} of type {val}!')

    def set_sweep(self, **kwargs):
        ''' setter for sweep parameters '''
        for key, val in kwargs.items():
            if key in self._sweep:
                match key:
                    case 'unit':
                        if isinstance(val, str):
                            self._sweep[key] = val
                    case 'name':
                        if val in self.valids['sweep']:
                            self._sweep[key] = val
                        else:
                            assert Exception(f'{val} is no valid value for sweep_{key}!')
                    case 'start' | 'stop' | 'duration' | 'rate':
                        if isinstance(val, (int, float)):
                            self._sweep[key] = val
                        else:
                            assert Exception(f'Value of {key} must be float or integer!')
                    case 'wait_time':
                        self._sweep['wait_time'] = val
            else:
                raise SettingsError
            
    def set_step(self, **kwargs):
        raise NotImplementedError('Step setting not implemented in 1D measurement!')
    
    def set_pulse(self, **kwargs):
        ''' setter for pulse parameters '''
        for key, val in kwargs.items():
            if key in self._pulse:
                match key:
                    case 'name':
                        log.error('Pulse name can not be changed! Only "vd" is supported!')
                    case 'unit':
                        log.error('Pulse unit can not be changed! Unit of "vd" is always "V"!')
                    case 'amp' | 'rate' | 'wait_time' | 'delay_time':
                        if isinstance(val, (int, float)):
                            self._pulse[key] = val
                        else:
                            assert Exception(f'Value of {key} must be float or integer!')
                    case 'traces':
                        if all(trd in self.valids['traces'] for trd in val):
                            self._pulse[key] = val
            else:
                raise SettingsError(f'Pulse has no var called {key}!')

    def set_wp_params(self, **kwargs):
        ''' setter for wp params'''
        for key, val in kwargs.items():
            if key == "mode":
                if val in self.valids["mode"]:
                    self._wp_params[key] = val
                else:
                    assert Exception(f'Mode for working point magnet must be in {self.valids["mode"]}')
            elif key in self._wp_params:
                if isinstance(val,(int,float)):
                    self._wp_params[key] = val
                else:
                    assert Exception(f'Value of {key} must be float or integer!')

    def set_trigger(self, **kwargs):
        ''' setter for trigger dict'''
        for pos, traces in kwargs.items():
            if pos in self.valids['trigger']:
                if all(trd in self.valids['traces'] for trd in traces):
                    self._save[pos] = traces
                else:
                    log.error(f'Not all "traces" in {traces} are allowed.')
            else:
                log.error(f'Position variable {pos} is not available for trigger.')

    def set_lockin(self, **kwargs):
        ''' setter for lockin params'''
        for key, val in kwargs.items():
            if key in self._lockin:
                if isinstance(val, (int, float)):
                    self._lockin[key] = val
                elif val is None and key in ['tao', 'maf']:
                    self._lockin[key] = val
                else:
                    log.error(f'Value of {key} must be float or integer!')

    def set_plot(self, **kwargs):
        ''' setter for plot dict'''
        for meas, traces in kwargs.items():
            if meas in self.valids['calc'] or meas in self.valids['inputs']:
                if all(trd in self.valids['traces'] for trd in traces):
                    self._plot[meas] = traces
                else:
                    log.error(f'Not all "traces" in {traces} are allowed.')
            else:
                log.error(f'Measurement variable {meas} is not available.')

    def set_save(self, **kwargs):
        ''' setter for save dict'''
        for meas, traces in kwargs.items():
            if meas in self.valids['calc'] or meas in self.valids['inputs']:
                if all(trd in self.valids['traces'] for trd in traces):
                    self._save[meas] = traces
                else:
                    log.error(f'Not all "traces" in {traces} are allowed.')
            else:
                log.error(f'Measurement variable {meas} is not available.')

    # ----------------------- Config I/O -----------------------

    def save_config(self):
        ''' save measurement config to .h/hdf5 file'''
        self.save = self.tune._data_file.add_config()
        self.save.add('ds_type', 'config')
        self.save.add('wp_params', self.get_wp_params())
        self.save.add('sweep', self.get_sweep())
        # self.save.add('step', self.get_step())
        self.save.add('lockin', self.get_lockin())
        self.save.add('pulse', self.get_pulse())
        self.save.add('inputs', self.get_inputs())
        self.save.add('plot', self.get_plot())
        self.save.add('save', self.get_save())
        self.save.add('config', self.adwin.aio.get_config())


    def load_config(self, h5_path):
        ''' load measurement config from .h/hdf5 file'''
        try:
            hf = h5py.File(h5_path)
            config_ds = hf["entry/data0/measurement.config"]
            config = {}
            for key, val in config_ds.attrs.items():
                try:
                    config[key] = json.loads(val)
                except Exception:
                    pass
            log.info('Load measurement config from .h/hdf5 file...')
            if 'hard_config' not in config:
                log.error('Could not load hard_config for adwin!')
            if 'soft_config' not in config:
                log.error('Could not load soft_config for adwin!')
            self.set(**config)
            log.info('Config from .h/hdf5 file loaded.')
        except ImportError:
            log.error('Load config from .h/hdf5 file failed!')


# ----------------------------- 2D subclass ------------------------------------

class Measure2D(Measure1D):
    """2D map measurement (step + sweep)."""

    def __init__(self, adwin: adwin_spin_transistor, readout_freq = 0, h5_path: str | None = None, **kwargs):
        self._step = {'name': None, 'start': None, 'stop': None, 'unit': None,
                      'step_size': None, 'values': None, 'init_time': None,
                      'wait_time': None}
        super().__init__(adwin, readout_freq, h5_path, **kwargs)
        self.generate_steps()

    def generate_steps(self):
        ''' generate steps for step variable if possible'''
        start = self._step['start']
        stop = self._step['stop']
        step = None if self._step['step_size'] is None else abs(self._step['step_size'])
        if None in [start, stop, step]:
            log.info("Couldn't generate step value list, inputs missing! Falling back to 1D behavior.")
            self._step['values'] = None
            return
        if start <= stop:
            steps = np.arange(start, stop + step, step, dtype=np.float32)
            if steps[-1] > stop:
                steps = steps[:-1]
        else:
            steps = np.arange(start, stop - step, -step, dtype=np.float32)
            if steps[-1] < stop:
                steps = steps[:-1]
        self._step['values'] = steps
        log.info("Generated step values!")

    def prepare_measurement_datasets(self):
        ''' prepare datasets for measurement'''
        self.ds = self.tune.multiplexer.prepare_measurement_datasets([self._x_parameter, self._y_parameter])

    def set_step(self, **kwargs):
        ''' setter for step parameters'''
        print("Setting step parameters...")
        for key, val in kwargs.items():
            if key in self._step:
                match key:
                    case 'unit':
                        if isinstance(val, str):
                            self._step[key] = val
                    case 'name':
                        if val in self.valids['step']:
                            self._step[key] = val
                        else:
                            log.error(f'{val} is no valid value for step_{key}!')
                    case 'start' | 'stop' | 'step_size' | 'init_time' | 'wait_time':
                        if isinstance(val, (int, float)):
                            self._step[key] = val
                        else:
                            log.info(f'Skip setting step param {key} with value {val}!')
                            log.error(f'Value of {key} must be float or integer!')

    def get_step(self):
        ''' getter for step vars'''
        return {k: v for k, v in self._step.items() if k != 'values'}
                        
    def wp_setter(self, x=None):
        ''' set new step val of step var for wp'''
        if self._inputs['retrace']:
            temp_wp_outs = self.wp_start.outs
        else:
            temp_wp_outs = self.wp_stop.outs
        self.set_start_wp(**{self._step['name']: x})
        self.set_stop_wp(**{self._step['name']: x})
        # calculate duration to go to next wp
        dur = 0.01 # min duration values: if zero the sweep might not happen -> fix in driver?!
        for key, val in self.wp_start.outs.items():
            dur_by_rate = abs(val - temp_wp_outs[key]) / self.valids['maxrate'][key]
            dur = max(dur, dur_by_rate)
        self.adwin.sweep(self.wp_start.outs, duration=dur)
        # implement wait time
        if self._step['wait_time']:
            time.sleep(self._step['wait_time'])

    def set_parameter(self):
        ''' prepare x/y parameter for measurement'''
        # x: step dimension (uses wp_setter), y: fast sweep dimension
        self.tune.set_x_parameters(self._step['values'], self._step['name'], self.wp_setter, self._step['unit'])
        self.tune.set_y_parameters(self._sweep['values'], self._sweep['name'], None, self._sweep['unit'])
        self._x_parameter = self.tune._x_parameter
        self._y_parameter = self.tune._y_parameter

    def add_view(self):
        ''' add 1D and 2D views'''
        for key in self.inputs_dict:
            if 'retrace' in key:
                view = self.tune._data_file.add_view(
                    name=key.replace("_retrace", ""),
                    x=self.tune._coordinates[self._y_parameter.name],
                    y=self.tune._datasets['measure_retrace.' + key]
                )
                view.add(
                    x=self.tune._coordinates[self._y_parameter.name],
                    y=self.tune._datasets['measure_trace.' + key.replace("retrace", "trace")]
                )
            if "difference" in key:
                self.tune._data_file.add_view(
                    name=key,
                    x=self.tune._coordinates[self._y_parameter.name],
                    y=self.tune._datasets['calc_difference.' + key]
                )
        if 'amp_difference' in self.inputs_dict:
            if 'deg' in self._step.get('unit', '') or '°' in self._step.get('unit', ''):
                self.tune._data_file.add_polarview(
                    name='polar_colormap',
                    x=self.tune._coordinates[self._x_parameter.name],
                    y=self.tune._coordinates[self._y_parameter.name],
                    z=self.tune._datasets['calc_difference.amp_difference']
                )

    def save_config(self):
        super().save_config()
        self.save.add('step', self.get_step())

    def start_measurement(self):
        ''' start activated measurement'''
        self.save_config()
        self.tune.measure2D(self._plot_dss, readout_dur=1/self._sweep_readout_freq if self._sweep_readout_freq != 0 else 0,
                            stop_event=self.stop_event)
