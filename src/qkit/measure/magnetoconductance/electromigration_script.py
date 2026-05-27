''' The electromigration script is a class to describe and run
    electromigration with live readout.

    *Required keywords:
        -adwin:         *adwin instrument
        -volts:         *source-drain voltage (v_report, v_stop, v_rate, r_limit)
        -sample_rate:   *sample rate

    *Optional keywords:
        -h5_path:       *path of .h/hdf5 file to extract and load electromigration config
                        from previous electromigration
        -update_dur:    *duration between data request from pc to adwin
        -gatesweep:     *bool, set true to activate parallel gate sweep with half
                        voltage of source-drain
        -gate_dur:      *duration for gate to sweep back to zero if active

'''
#imports
import tkinter as tk
import threading
import time
import logging as log
import numpy as np
import qkit
from qkit.measure.magnetoconductance.spin_tune_EM import Tuning_EM
from qkit.drivers.adwin_electromigration import adwin_electromigration

MCU_frequency = 300e6

class ElectromigrationScript:
    '''Generate and run electromigration routines with live readout.'''

    def __init__(self, adwin: adwin_electromigration, update_dur=1, **kwargs):
        self.adwin = adwin
        self._state = 'init_script'

        self._define_validations()
        self._initialize_defaults()
        self.set_update_duration(update_dur)
        self.set_em_params(**kwargs)
        self.update_script()

    def _define_validations(self):
        '''Define valid measurement inputs and parameter limits.'''
        self.valid_inputs = ['current', 'resistance', 'conductance']
        self.max_voltrate = 0.2     # rate in V/s
        self.max_volts = 10         # max voltage for electromigration
        self.max_sample_rate = 500e3
        self.unit = {'current': 'A', 'resistance': 'ohm', 'conductance': 'S'}
        self.valids = {
            'inputs': self.valid_inputs,
            'v_report': self.max_volts,
            'v_stop': self.max_volts,
            'v_rate': self.max_voltrate,
            'sample_rate': self.max_sample_rate,
        }

    def _initialize_defaults(self):
        '''Initialize default script parameters and sweep configuration.'''
        self.readout_dur = 1
        self._em_params = {
            'v_report': 0,
            'v_stop': 10,
            'v_rate': None,
            'r_limit': 0,
            'sample_rate': 5000,
            'gatesweep': False,
            'gate_dur': 20,
        }
        self._sweep = {
            'name': 'vd',
            'start': None,
            'stop': None,
            'unit': 'V',
            'rate': None,
            'values': np.array([], dtype=float),
        }
        self.inputs_dict = {}

    def update_script(self):
        '''Build measurement setup and generate sweep values.'''
        self.generate_sweep()       # generate sweep values
        self.create_tuning()        # create Tuning_EM instance
        self.create_inputs()        # create a dict of the input nodes
        self.register_measurement() # register measure function
        self.set_node_bounds()      # create bounds for input variables
        self.activate_measurement() # activate measurement
        self.set_parameter()        # set x/y coordinate parameter
        self.prepare_measurement_datasets()
        self.prepare_measurement_datafile()
        self._state = 'script_updated'

    def stop_measurement(self):
        '''Stop measurement.'''
        self.adwin.stop_electromigration()
        time.sleep(0.5)
        self.tune.watchdog.stop = True
        self.tune._qvk_process.terminate()

    def prepare_measurement_datasets(self):
        '''Prepare datasets for the measurement.'''
        self.ds = self.tune.multiplexer.prepare_measurement_datasets([self._x_parameter])

    def prepare_measurement_datafile(self):
        '''Prepare the HDF/H5 output file for measurement.'''
        self.tune._prepare_measurement_file(self.ds)
        self.coordinates = self.tune._coordinates
        self.datasets = self.tune._datasets
        self.datafile = self.tune._data_file

    def create_tuning(self):
        '''Instantiate the electromigration tuning helper.'''
        self.tune = Tuning_EM()
        self.tune.qviewkit_singleInstance = True

    def init_electromigration(self):
        '''Configure electromigration parameters on the ADwin instrument.'''
        self._state = 'init_em'
        self.adwin.init_electromigration(
            sample_rate=self._em_params['sample_rate'],
            sweep_rate=self._em_params['v_rate'],
            report_voltage=self._em_params['v_report'],
            max_voltage=self._em_params['v_stop'],
            r_limit=self._em_params['r_limit'],
            gatesweep=self._em_params['gatesweep'],
            gate_dur=self._em_params['gate_dur'],
        )
        self._state = 'em_ready'

    def start_measurement(self):
        '''Start measurement and show an emergency stop button.'''
        if self._state != 'em_ready':
            log.error(f'Electromigration is not initialized! ({self._state})')
            return

        gui_window = tk.Tk()
        gui_window.title('Measurement running')

        label = tk.Label(gui_window, text='Measurement running...\nClick to stop')
        label.pack(padx=20, pady=10)

        stop_button = tk.Button(
            gui_window,
            text='Stop',
            command=self.stop_measurement,
            bg='red',
            fg='white',
        )
        stop_button.pack(padx=20, pady=10)

        self.adwin.start_electromigration()
        threading.Thread(target=self.tune.measure1D).start()
        gui_window.mainloop()

    def set_parameter(self):
        '''Set the x/y coordinate parameter for the measurement.'''
        self.tune.set_x_parameters(
            self._sweep['values'],
            self._sweep['name'],
            None,
            self._sweep['unit'],
            self.readout_dur,
        )
        self._x_parameter = self.tune._x_parameter

    def em_readout(self):
        '''Read ADwin FIFOs and build the measurement result dict.'''
        res = {}
        readout_em = self.adwin.do_get_fifo_data()

        for key, val in readout_em.items():
            if key in self.valid_inputs:
                if val is not None:
                    res[key] = val
            else:
                log.critical(f'{key} is no valid input var!')

        if res:
            step = self.tune.pb.progr
            steps = len(res['current'])
            x_values = self._sweep['values'][step:step + steps]
            self._add_derived_inputs(res, x_values)

        return res

    def _add_derived_inputs(self, res, x_values):
        for key in self.valid_inputs:
            if key not in res:
                match key:
                    case 'resistance':
                        res['resistance'] = x_values / res['current']
                    case 'conductance':
                        res['conductance'] = res['current'] / x_values

    def create_inputs(self):
        '''Create the input dictionary with units for measurement registration.'''
        for key in self.valid_inputs:
            self.inputs_dict[key] = self.unit[key]

    def register_measurement(self):
        '''Register the measurement callback with the tuning helper.'''
        print('Input dict: ', self.inputs_dict)
        self.tune.register_measurement('electromigration', self.inputs_dict, self.em_readout)

    def set_node_bounds(self):
        '''Set bounds for each measurement input variable.'''
        for key in self.inputs_dict:
            self.tune.set_node_bounds('electromigration', key, 0, 1e16)

    def activate_measurement(self):
        '''Activate the measurement within the tuning helper.'''
        self.tune.activate_measurement('electromigration')

    def generate_sweep(self):
        '''Generate the sweep values from the configured electromigration parameters.'''
        self._sweep['start'] = self._em_params['v_report']
        self._sweep['stop'] = self._em_params['v_stop']
        self._sweep['rate'] = self._em_params['v_rate']

        bits = self.adwin.aio.get_bits('vd')
        vrange = self.adwin.aio.get_scale('vd')
        sweep_rate = self._sweep['rate'] * 2**(bits - 1) / vrange
        process_delay = np.round(MCU_frequency / sweep_rate)
        val = MCU_frequency / process_delay
        real_sweep_rate = val * vrange / 2**(bits - 1)
        virt_sweep_steps = real_sweep_rate / self._em_params['sample_rate']

        self._sweep['values'] = np.arange(
            self._em_params['v_report'],
            self._em_params['v_stop'] + virt_sweep_steps,
            virt_sweep_steps,
        )
        self._sweep['unit'] = 'V'
        self._sweep['name'] = 'vd'

    def get_volts(self):
        '''Return the current electromigration parameter dictionary.'''
        return self._em_params

    def set_em_params(self, **kwargs):
        '''Set multiple electromigration parameters at once.'''
        log.info('Setting electromigration parameters...')
        for key, val in kwargs.items():
            if key not in self._em_params:
                log.error(f'Electromigration params have no key called {key}!')
                continue

            log.info(f'Setting {key} to {val}...')
            if key in {'v_report', 'v_stop', 'v_rate'}:
                self._set_voltage_param(key, val)
            else:
                self._em_params[key] = val

    def _set_voltage_param(self, key, value):
        if isinstance(value, (int, float)):
            if 0 <= value <= self.valids[key]:
                self._em_params[key] = value
            else:
                log.warning(f'{key} is not in range(0,{self.valids[key]})!')
        else:
            log.error(f'Type {type(value)} is not valid for {key}!')

    def set_update_duration(self, duration):
        '''Set the duration between ADwin FIFO readouts.'''
        self.readout_dur = duration
