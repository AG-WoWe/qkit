''' The measurement script is a class to describe and run
    a 1D or 2D measurement, therefore several vars must be set.
    These variables describe the working points (wp) to sweep between
    during the measurement. Additional needed parameter is the mode
    (normal/sweep) of the wp, more about this in the wp class.
    The measurement can run with and without lockin signal,
    if there should no lockin signal be applied, set no amplitude
    or set amplitude to zero.

    *Required keywords:
        -adwin:  *adwin instrument

    (all below listed variables are saved as dictionaries,
    some vars vaulues are restricted to certain values,
    these are defined in the init of the class as valid values)

        -sph:       *spherical coordinates and values for wp
                    *phi, theta, psi, bp, bt
                    *if a sph coordinate is used as step or sweep var
                    it is not needed, because the value will be overwritten

        -magnet:    *normal: direction determines the transverse field
                             axis, and psi the sweep axis
                    *sweep: direction determindes the sweep axis and psi
                            the direction of the transverse field
                    , sweep

        -volts:     *source-drain and gate voltage
                    *vd, vg

        -sweep:     *vars to generate virtual sweep values array
                    *name, start, stop, unit
                    *optional: rate, duration
                    *if no rate or duration is set, valids['maxrate'] of sweep var will be used

        -step:      *vars to generate step values array (only needed for 2D measurement)
                    *name, start, stop, stepsize, unit
                    *stop value is incuded in step values array

        -inputs:    *inputs to measure and return from adwin instrument
                    *raw, inph, quad (for "inph" and "quad" is a lockin signal required)
                    *optional: retrace (default=False, describes if retrace is measured)
                    *if "save" is set in data, needed outputs will be generated automatically

        -data:      *vars that should be saved and plotted from the measurement
                    *save: (traces, inputs); plot: (traces, inputs)
                    *traces and inputs in "plot" will automatically be added to save,
                    cause its required to save the data to plot it with qviewkit.
                    *additional inputs: amp, phase (inph, quad needed for calculation)

    *Optional keywords:
        -h5_path:   *path of .h/hdf5 file to extract and load measurement config
                     from previous measurement

                     
    *ToDo:  -static measurement:        *measurement without sweep or step
            -interactive measurement:   *measurement with adwin communication while sweep
            !!! B to zero, all to zero !!!

'''

import json
import time
import logging as log
import numpy as np
import h5py
from qkit.measure.magnetoconductance.spin_tune_ST import Tuning_ST
from qkit.measure.magnetoconductance.working_point import WorkingPoint
from qkit.drivers.adwin_spin_transistor import adwin_spin_transistor


class SettingsError(Exception):
    ''' Raise Error if settings for Measurement script are invalid '''

def calc_r(x, y):
    ''' calc func for amplitude from lockin'''
    return np.sqrt(np.square(x) + np.square(y))

def calc_theta(x, y):
    ''' calc func for phase shift from lockin'''
    return np.arctan2(y, x)

def correct_lockin_by_amplitude(x, lockin_amplitude):
    ''' just divide by amp or ist there a factor? check in adbasic script '''
    pass

class MeasurementScript():
    ''' The Measurement Script generates a 
    measurement routine with given params'''

    def __init__(self, adwin:adwin_spin_transistor, h5_path=None,
                 **kwargs):

        self.valids = {
            'step': {'vg', 'vd', 'N', 'bt', 'bp', 'phi', 'psi', 'theta'},
            'sweep': {'vg', 'vd', 'bt', 'bp', 'phi', 'psi', 'theta', 'time'},
            'magnet': {'normal', 'sweep'},
            'traces': {'trace', 'retrace', 'difference'},
            'inputs': {'raw', 'inph', 'quad'},
            'calc': {'amp': ['inph', 'quad'], 'phase': ['inph', 'quad']},
            'calc_func': {'amp': calc_r, 'phase': calc_theta},
            'maxrate': {'bx': 0.3, 'by': 0.3, 'bz': 0.3, 'bp': 0.3,
                        'bt': 0.1, 'vg': 0.05, 'vd': 0.01, 'time': 1e6},
            'unit': {'inph': 'S', 'quad': 'S', 'raw': 'I', 'amp': 'S',
                     'phase': 'rad'}}

        self.setup_params() # setup needed measurement params
        self.def_setter()   # define params setter funcs

        # load measurement params from h5file
        if h5_path is not None:
            self.load_config(h5_path)

        self.set_(**kwargs) # set imported param values

        self.adwin = adwin    # connect ADwin instrument

        self.tune = Tuning_ST()
        self.tune.qviewkit_singleInstance = True

        # Create working_points for the start and stop of the sweep
        # using all connected adwin outputs. They will get updated
        # for each sweep of a map
        adwin_outputs = adwin.list_connected_outputs()
        self.wp_start = WorkingPoint(adwin_outputs, magnet='vector3d')
        self.wp_stop = WorkingPoint(adwin_outputs, magnet='vector3d')

        self.update_script()    # generate measurement routine


    def setup_params(self):
        ''' setup params for the measurement'''
        self._sph = {'theta': 0, 'phi': 0, 'psi': 0, 'bp': 0, 'bt': 0}
        self._sweep = {'name': None, 'start': None, 'stop': None,
                       'unit': None, 'rate': None, 'duration': None,
                       'values':None, 'wait_time': None}
        self._step = {'name':None,'start':None,'stop':None,'unit':None,
                        'step_size':None,'values':None, 'init_time': None}
        self._magnet = None
        self._volts = {'vd':None,'vg':None}
        self._lockin = {'freq': None, 'amp': None, 'tao': None,
                        'init_time': None, 'sample_rate': 500e3,
                        'phase': None, 'maf': None}
        self._inputs = {'retrace': False, 'inputs': []}
        self._plot = {'inph': set(), 'quad': set(), 'raw': set(), 'amp': set(), 'phase': set()}
        self._save = {'inph': set(), 'quad': set(), 'raw':set(), 'amp': set(), 'phase': set()}
        self._temp = {}


    def def_setter(self):
        ''' define setter functions of params'''
        self.set_functions = {
            'sph': self.set_sph, 'sweep': self.set_sweep,
            'step': self.set_step, 'magnet': self.set_magnet, 
            'volts': self.set_volts, 'lockin': self.set_lockin,
            'plot': self.set_plot, 'save': self.set_save}

    def update_script(self):
        ''' genererate measurement setup'''
        self.add_saves()            # generate data save and temp dicts
        self.add_inputs()           # generate ADwin inputs

        self.start_lockin()         # start lockin signal
        self.update_lockin()        # get real lockin data from adwin

        self.generate_sweep()       # generate sweep values
        self.generate_steps()       # generate step values

        self.init_wps()             # init start and stop wp of first sweep
        self.sweep_to_startpoint()  # start sweep to the first wp

        self.create_inputs()        # create a dict of the input nodes
        self.register_measurement() # register measure function
        self.set_node_bounds()      # create bounds for input variables
        self.activate_measurement() # activate measurement
        self.set_parameter()        # set x/y coordinate parameter
        self.prepare_measurement_datasets()
        self.prepare_measurement_datafile()

        self.show_plots()           # determine names from datasets to plot
        self.add_view()             # add view datasets

    def end_measurement(self):
        ''' end measurement'''
        self.adwin.stop_measurement()
        self.tune._qvk_process.terminate()

    def prepare_measurement_datasets(self):
        ''' prepare datasets for measurement'''
        if self.dim == 2:
            self.ds = self.tune.multiplexer.prepare_measurement_datasets([self._x_parameter, self._y_parameter])
        elif self.dim == 1:
            self.ds = self.tune.multiplexer.prepare_measurement_datasets([self._x_parameter])

    def prepare_measurement_datafile(self):
        ''' prepare .hdf/h5 file for measurement'''
        self.tune._prepare_measurement_file(self.ds)

    def show_plots(self):
        ''' create list of datasets to plot'''
        plotted_data = []
        for meas, traces in self._plot.items():
            for trd in traces:
                    plotted_data.append(f'sweep_measure.{meas}_{trd}')
        if plotted_data:
            self.plots = plotted_data
        else:
            self.plots = None

    def start_measurement(self):
        ''' start activated measurement'''
        self.save_config()
        if self.dim == 1:
            self.tune.measure1D(self.plots)
        elif self.dim == 2:
            self.tune.measure2D(self.plots, wait_time=None)
        else:
            assert ModuleNotFoundError

    def add_view(self):
        ''' adds 1D views'''
        for key in self.inputs_dict:
            if 'retrace' in key:
                if self.dim == 2:
                    view = self.tune._data_file.add_view(
                        name=key.replace("_retrace",""),
                        x=self.tune._coordinates[self._y_parameter.name],
                        y=self.tune._datasets['sweep_measure.'+key])
                    view.add(
                        x=self.tune._coordinates[self._y_parameter.name],
                        y=self.tune._datasets['sweep_measure.'+key.replace("retrace","trace")])
                else:
                    view = self.tune._data_file.add_view(
                        name=key.replace("_retrace",""),
                        x=self.tune._coordinates[self._x_parameter.name],
                        y=self.tune._datasets['sweep_measure.'+key])
                    view.add(
                        x=self.tune._coordinates[self._x_parameter.name],
                        y=self.tune._datasets['sweep_measure.'+key.replace("retrace","trace")])
            if 'difference' in key:
                if self.dim == 2:
                    view = self.tune._data_file.add_view(
                        name=key,
                        x=self.tune._coordinates[self._y_parameter.name],
                        y=self.tune._datasets['sweep_measure.'+key])
                else:
                    view = self.tune._data_file.add_view(
                        name=key,
                        x=self.tune._coordinates[self._x_parameter.name],
                        y=self.tune._datasets['sweep_measure.'+key])
        if 'amp_difference' in self.inputs_dict:
            if 'deg' in self._step.get('unit') or '°' in self._step.get('unit'):
                view = self.tune._data_file.add_polarview(
                    name='polar_colormap',
                    x=self.tune._coordinates[self._x_parameter.name],
                    y=self.tune._coordinates[self._y_parameter.name],
                    z=self.tune._datasets['sweep_measure.amp_difference'])

    def set_parameter(self):
        ''' setter for x/y parameter of measurement'''
        if self.dim == 1:
            self.tune.set_x_parameters(
                self._sweep['values'], self._sweep['name'],
                None, self._sweep['unit'])
            self._x_parameter = self.tune._x_parameter
        elif self.dim == 2:
            self.tune.set_x_parameters(
                self._step['values'], self._step['name'],
                self.wp_setter, self._step['unit'])
            self.tune.set_y_parameters(
                self._sweep['values'], self._sweep['name'],
                None, self._sweep['unit'])
            self._x_parameter = self.tune._x_parameter
            self._y_parameter = self.tune._y_parameter

    def update_lockin(self):
        ''' updates the sample rate and lockin frequency data in the script
        with real data readout from adwin -> no new lockin signal'''
        self.set_lockin(**{'freq': self.adwin.get_lockin_frequency(),
                           'sample_rate':self.adwin.get_sample_rate()})

    def sweep_to_startpoint(self):
        ''' start sweep from adwin outputs to the first wp of the measurement'''
        outs_start = self.adwin.read_outputs(out_format='qty', select='connected')
        # Find the sweep time to the first wp of the measurement by
        # comparing the necessary sweep times for each output
        sweep_time = 0
        for key, val in self.wp_start.outs.items():
            duration = abs(val - outs_start[key]) / self.valids['maxrate'][key]
            sweep_time = max(sweep_time, duration)
        log.info(f"Sweeping to start point in {sweep_time:.1f}s!")
        print(self.wp_start.outs)
        self.adwin.sweep(self.wp_start.outs, duration=sweep_time)
        if self._step['init_time']:
            time.sleep(self._step['init_time'])

    def start_lockin(self):
        ''' start lockin signal'''
        self.adwin.init_measurement(
            sample_rate=self._lockin['sample_rate'],
            bias=self._volts['vd'],
            inputs=self._inputs['inputs'],
            frequency=self._lockin['freq'],
            amplitude=self._lockin['amp'],
            phase=self._lockin['phase'],
            tao=self._lockin['tao'],
            maf=self._lockin['maf']
            )
        if self._lockin['init_time']:
            time.sleep(self._lockin['init_time'])

    def correct_len(self, trace, samples):
        ''' If the length of a trace is not exactly what is expected, either
            the redundant samples are removed, or the last sample is copied
            until the trace is full. The discrepancy is usally +-2 samples and
            therefore negligable '''
        N = len(trace)
        if N > samples:
            return trace[:samples]
        if N == samples:
            return trace
        if N < samples:
            diff = samples - N
            return np.append(trace, [trace[-1]] * diff)

    def sweep_measure(self):
        ''' measure sweep and generate data dict'''
        trace, retrace = None, None
        # sleep for wait_time if set up
        if self._sweep['wait_time']:
            time.sleep(self._sweep['wait_time'])
        # get sweep duration
        sweep_duration = self._sweep['duration']
        # measure trace
        if self._sweep['name'] == 'time':
            trace = self.adwin.measure(duration=sweep_duration)
        else:
            trace = self.adwin.sweep_measure(self.wp_stop.outs,
                                             duration=sweep_duration)
        # measure retrace if set up
        if self._inputs['retrace']:
            # sleep for wait_time if set up
            if self._sweep['wait_time']:
                time.sleep(self._sweep['wait_time'])
            # if sweep is over time call measure function
            if self._sweep['name'] == 'time':
                trace = self.adwin.measure(duration=sweep_duration)
            # if sweep is variable call sweep_measure function
            else:
                retrace = self.adwin.sweep_measure(self.wp_start.outs,
                                                   duration=sweep_duration
        )
        samples = len(self._sweep['values'])
        # temp contains inputs required to calcluate all save variables
        temp = {}
        # first handle all the direct inputs
        for meas, traces in self._temp.items():
            if meas in self.valids['inputs']:
                tr = self.correct_len(trace[meas], samples)
                rt = None
                diff = None
                if retrace:
                    rt = np.flip(self.correct_len(retrace[meas], samples))
                if 'difference' in traces:
                    if all(isinstance(i, np.ndarray) for i in [tr, rt]):
                        diff = rt - tr
                    else:
                        assert ValueError
                if isinstance(tr, np.ndarray):
                    temp[f'{meas}_trace'] = tr
                if isinstance(rt, np.ndarray):
                    temp[f'{meas}_retrace'] = rt
                if isinstance(diff, np.ndarray):
                    temp[f'{meas}_difference'] = diff
        # then handle all input to be calculated from the direct inputs
        for meas, traces in self._temp.items():
            if meas in self.valids['calc']:
                func = self.valids['calc_func'][meas]
                args = self.valids['calc'][meas]
                tr = func(temp.get(f'{args[0]}_trace'),
                          temp.get(f'{args[1]}_trace'))
                rt = None
                diff = None
                if retrace:
                    rt = func(temp.get(f'{args[0]}_retrace'),
                              temp.get(f'{args[1]}_retrace'))
                if 'difference' in traces:
                    if all(isinstance(i, np.ndarray) for i in [tr, rt]):
                        diff = tr - rt
                    else:
                        assert ValueError
                if isinstance(tr, np.ndarray):
                    temp[f'{meas}_trace'] = tr
                if isinstance(rt, np.ndarray):
                    temp[f'{meas}_retrace'] = rt
                if isinstance(diff, np.ndarray):
                    temp[f'{meas}_difference'] = diff
        # Put the data to be saved in the save to return
        save = {}
        for meas, traces in self._save.items():
            for trd in traces:
                save[f'{meas}_{trd}'] = temp[f'{meas}_{trd}']
        return save

    def create_inputs(self):
        ''' create dictionary for measurement inputs with unit'''
        self.inputs_dict = {}
        for key, val in self._save.items():
            for key1 in val:
                self.inputs_dict[f'{key}_{key1}'] = self.valids['unit'][key]

    def register_measurement(self):
        ''' register measurement with needed data input dict'''
        self.tune.register_measurement('sweep_measure',
                                       self.inputs_dict,
                                       self.sweep_measure)

    def set_node_bounds(self):
        ''' set bounds for data input dict'''
        for key in self.inputs_dict:
            self.tune.set_node_bounds('sweep_measure', key, -10e9, 10e9)

    def activate_measurement(self):
        ''' activate measurement'''
        self.tune.activate_measurement('sweep_measure')

    def init_wps(self):
        ''' Initialize start and stop working points for map '''
        self.wp_start.set_sph(**self._sph)
        self.wp_start.set_wp(**self._volts)
        self.wp_start.set_mode(self._magnet)
        self.wp_stop.set_sph(**self._sph)
        self.wp_stop.set_wp(**self._volts)
        self.wp_stop.set_mode(self._magnet)
        if self._sweep['name'] in self.wp_start.get_sph():
            self.wp_start.set_sph(**{self._sweep['name'] : self._sweep['start']})
            self.wp_stop.set_sph(**{self._sweep['name'] : self._sweep['stop']})
        elif self._sweep['name'] in self.wp_start.outs:
            self.wp_start.set_wp(**{self._sweep['name'] : self._sweep['start']})
            self.wp_stop.set_wp(**{self._sweep['name'] : self._sweep['stop']})
        if self.dim == 2:
            self.set_start_wp()
            self.set_stop_wp()

    def set_start_wp(self,**kwargs):
        ''' setter function for start working point of sweep'''
        if self._step['name'] in self.wp_start.get_sph():
            self.wp_start.set_sph(**kwargs)
        elif self._step['name'] in self.wp_start.outs:
            self.wp_start.set_wp(**kwargs)

    def set_stop_wp(self,**kwargs):
        ''' setter function for stop working point of sweep'''
        if self._step['name'] in self.wp_stop.get_sph():
            self.wp_stop.set_sph(**kwargs)
        elif self._step['name'] in self.wp_stop.outs:
            self.wp_stop.set_wp(**kwargs)

    def wp_setter(self, x=None, dt=None):
        ''' set new step val of step var for wp'''
        if self._inputs['retrace']:
            temp_wp_outs=self.wp_start.outs
        else:
            temp_wp_outs=self.wp_stop.outs
        self.set_start_wp(**{self._step['name']:x})
        self.set_stop_wp(**{self._step['name']:x})
        min_duration=0
        for key,val in self.wp_start.outs.items():
            duration = abs(val - temp_wp_outs[key])/self.valids['maxrate'][key]
            if min_duration < duration:
                min_duration = duration
        if dt is None:
            dt = min_duration
        elif dt<min_duration:
            log.warning(f'Fixed ramp duration {dt}s is not safe, duration was set to minimal possible duration {min_duration}s!')
            dt = min_duration
        self.adwin.sweep(self.wp_start.outs, duration=dt)

    def generate_steps(self):
        ''' generate steps for step variable if possible'''
        if None not in [self._step['start'],
                        self._step['stop'],
                        self._step['step_size']]:
            steps = np.arange(self._step['start'],
                self._step['stop'] + self._step['step_size'],
                self._step['step_size'], dtype=np.float32)
            if steps[-1] > self._step['stop']:
                steps = steps[:-1]
            self._step['values'] = np.arange(self._step['start'],
                self._step['stop'] + self._step['step_size'],
                self._step['step_size'], dtype=np.float32)
            self.dim = 2
        else:
            log.info("Couldn't generate step value list, inputs missing!")
            self.dim = 1

    def generate_sweep(self):
        ''' generate steps for sweep variable if possible'''
        # check if start and stop values are given
        if None in [self._sweep['start'], self._sweep['stop']]:
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
        self._sweep['values'] = np.linspace(self._sweep['start'],
                                            self._sweep['stop'],
                                            samples,
                                            dtype=np.float32)
        log.info("Generated sweep values!")


    def get_sph(self):
        ''' getter func for sph vars'''
        return {**self._sph}

    def get_step(self):
        ''' getter func for step vars'''
        return {k: v for k, v in self._step.items() if k != 'values'}

    def get_sweep(self):
        ''' getter func for sweep vars'''
        return {k: v for k, v in self._sweep.items() if k != 'values'}

    def get_step_val(self):
        ''' getter func for step values'''
        if self._step['values'] is None:
            self.generate_steps()
        return self._step['values']

    def get_sweep_val(self):
        ''' getter func for sweep values'''
        if self._sweep['values'] is None:
            self.generate_sweep()
        return self._sweep['values']

    def get_magnet(self):
        ''' getter func for magnet configuration'''
        return self._magnet

    def get_volts(self):
        ''' getter func for volts'''
        return {**self._volts}

    def get_lockin(self):
        ''' getter func for lockin signal pars'''
        return {**self._lockin}

    def get_inputs(self):
        ''' getter func for inputs of adwin'''
        return {**self._inputs}

    def get_plot(self):
        ''' getter func for plot dictionary '''
        return {m: list(traces) for m, traces in self._plot.items()}

    def get_save(self):
        'getter func for save dictionary '''
        return {m: list(traces) for m, traces in self._save.items()}

    def add_saves(self):
        ''' getter func for data measurement, saving, live plotting'''
        # Automatically add all plots to saves
        for meas, traces in self._plot.items():
            self._save[meas].update(traces)
        # Add all needed measurements to temp
        for meas, traces in self._save.items():
            if traces:
                # add meas to temp
                self._temp[meas] = traces
                # if calculatable variable, add all dependencies
                if meas in self.valids['calc']:
                    for dep in self.valids['calc'][meas]:
                        try:
                            self._temp[dep].update(self._save[meas])
                        except KeyError:
                            self._temp[dep] = self._save[meas]

    def add_inputs(self):
        ''' generate adwin inputs'''
        for key, val in self._temp.items():
            if key in self.valids['inputs'] and val:
                if key not in self._inputs['inputs']:
                    self._inputs['inputs'].append(key)
        if any(s in str(self._temp) for s in ['retrace', 'difference']):
            self._inputs['retrace'] = True

    def set_(self,**kwargs):
        ''' setter for multiple vars'''
        for key,val in kwargs.items():
            if key in self.set_functions and isinstance(val, dict):
                self.set_functions[key](**val)
            elif key in self.set_functions:
                self.set_functions[key](val)
            else:
                log.error(f'{self} have no var called {key} of type {val}!')

    def set_sweep(self, **kwargs):
        ''' setter func for sweep'''
        for key, val in kwargs.items():
            if key in self._sweep:
                match key:
                    case 'unit':
                        if isinstance(val,str):
                            self._sweep[key] = val
                    case 'name':
                        if val in self.valids['sweep']:
                            self._sweep[key] = val
                        else:
                            log.error(f'{val} is no valid value for sweep_{key}!')
                    case 'start' | 'stop' | 'duration' | 'rate':
                        if isinstance(val,(int,float)):
                            self._sweep[key] = val
                        else:
                            log.error(f'Value of {key} must be float or integer!')
                    case 'wait_time':
                        self._sweep['wait_time'] = val
            else:
                raise SettingsError


    def set_step(self, **kwargs):
        ''' setter func for step'''
        for key, val in kwargs.items():
            if key in self._step:
                match key:
                    case 'unit':
                        if isinstance(val,str):
                            self._step[key] = val
                    case 'name':
                        if val in self.valids['step']:
                            self._step[key] = val
                        else:
                            log.error(f'{val} is no valid value for step_{key}!')
                    case 'start' | 'stop' | 'step_size' | 'init_time' | 'wait_time':
                        if isinstance(val,(int,float)):
                            self._step[key] = val
                        else:
                            log.error(f'Value of {key} must be float or integer!')

    def set_magnet(self, val):
        ''' setter func for magnet'''
        if val in self.valids['magnet']:
            self._magnet = val
        else:
            log.error(f'{val} is no valid mode for magnet!')

    def set_volts(self, **kwargs):
        ''' setter func for volts'''
        for key, val in kwargs.items():
            if key in self._volts:
                if isinstance(val,(int,float)):
                    self._volts[key] = val
                else:
                    log.error(f'Value of {key} must be float or integer!')

    def set_lockin(self, **kwargs):
        ''' setter func for lockin signal'''
        for key, val in kwargs.items():
            if key in self._lockin:
                if isinstance(val, (int, float)):
                    self._lockin[key] = val
                elif val is None and val in ['tao', 'maf']:
                    self._lockin[key] = val
                else:
                    log.error(f'Value of {key} must be float or integer!')

    def set_plot(self, **kwargs):
        ''' Setter function for data plotting '''
        for meas, traces in kwargs.items():
            # check that meas is valid
            if meas in self.valids['calc'] or meas in self.valids['inputs']:
                #check that all traces are valid
                if all(trd in self.valids['traces'] for trd in traces):
                    self._plot[meas] = traces
                else:
                    log.error(f'Not all "traces" in {traces} are allowed.')
            else:log.error(f'Measurement variable {meas} if not available.')

    def set_save(self, **kwargs):
        ''' Setter function for data saving '''
        for meas, traces in kwargs.items():
            # check that meas is valid
            if meas in self.valids['calc'] or meas in self.valids['inputs']:
                #check that all traces are valid
                if all(trd in self.valids['traces'] for trd in traces):
                    self._save[meas] = traces
                else:
                    log.error(f'Not all "traces" in {traces} are allowed.')
            else:log.error(f'Measurement variable {meas} if not available.')
        pass

    def set_sph(self, **kwargs):
        ''' update all given spherical b parameters '''
        for key,val in kwargs.items():
            if key in self._sph:
                if isinstance(val,(int,float)):
                    self._sph[key] = val
                else:
                    log.error(f'Value of {key} must be float or integer!')

    def save_config(self):
        ''' save measurement config in dataset of .h/hdf5 file'''
        save = self.tune._data_file.add_config()
        save.add('ds_type', 'config')
        save.add('sph', self.get_sph())
        save.add('sweep', self.get_sweep())
        save.add('step', self.get_step())
        save.add('magnet', self.get_magnet())
        save.add('volts', self.get_volts())
        save.add('lockin', self.get_lockin())
        save.add('inputs', self.get_inputs())
        save.add('plot', self.get_plot())
        save.add('save', self.get_save())
        save.add('config', self.adwin.aio.get_config())

    def load_config(self, h5_path):
        ''' load measurement config from .h/hdf5 file'''
        try:
            hf = h5py.File(h5_path)
            config_ds = hf["entry/data0/measurement.config"]
            config = {}
            for key ,val in config_ds.attrs.items():
                try:
                    config[key] = json.loads(val)
                except:
                    pass
            log.info('Load measurement config from .h/hdf5 file...')
            if 'hard_config' not in config:
                log.error('Could not load hard_config for adwin!')
            if 'soft_config' not in config:
                log.error('Could not load soft_config for adwin!')
            self.set_(**config)
            log.info('Config from .h/hdf5 file loaded.')
        except ImportError:
            log.error('Load config from .h/hdf5 file failed!')
