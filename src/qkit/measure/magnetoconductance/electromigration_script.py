''' The electromigration script is a class to describe and run
    electromigration with live readout.

    *Required keywords:
        -anna:          *adwin instrument
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

class ElectromigrationScript():
    ''' The Electromigration Script generates a 
    electromigration routine with given params'''

    def __init__(self, adwin:adwin_electromigration, update_dur=1,**kwargs):
        self._state = 'init_script'
        self.def_valids()   # define valid inputs for params
        self.setup_params() # setup needed params for em
        # set duration for pc data receive, can't be changed after measurement started
        self.set_update_duration(update_dur)    
        self.set_em_params(**kwargs)     # set imported param values
        self.anna = adwin       # connect ADwin instrument
        self.update_script()    # generate measurement routine

    def def_valids(self):
        ''' define validations'''
        self.valid_inputs = ['current','resistance','conductance']
        self.max_voltrate = 0.1 # rate in V per sec
        self.max_volts = 10     # max voltage in V
        self.max_sample_rate = 500e3
        self.unit = {'current':'A','resistance':'ohm','conductance':'S'}
        self.valids = {'inputs':self.valid_inputs,'v_report':self.max_volts,
                        'v_stop':self.max_volts,'v_rate':self.max_voltrate,
                        'sample_rate':self.max_sample_rate}

    def setup_params(self):
        ''' setup params for the measurement'''
        self.readout_dur = 1
        self._em_params = {'v_report':0, 'v_stop':10, 'v_rate':None, 'r_limit':0,
                        'sample_rate': 5000, 'gatesweep': False, 'gate_dur': 20}
        self._sweep = {'name': 'vd', 'start': None, 'stop': None,
                        'unit': 'V', 'rate': None, 'values':None}
        self.inputs_dict = {}

    def update_script(self):
        ''' genererate measurement setup'''
        self.generate_sweep()       # generate sweep values

        self.create_tuning()        # create Tuning_ST instance
        self.create_inputs()        # create a dict of the input nodes
        self.register_measurement() # register measure function
        self.set_node_bounds()      # create bounds for input variables
        self.activate_measurement() # activate measurement
        self.set_parameter()        # set x/y coordinate parameter
        self.prepare_measurement_datasets()
        self.prepare_measurement_datafile()
        self._state = 'script_updated'

    def stop_measurement(self):
        ''' end measurement'''
        self.anna.stop_electromigration()
        time.sleep(0.5)
        self.tune.watchdog.stop = True
        self.tune._qvk_process.terminate()

    def prepare_measurement_datasets(self):
        ''' prepare datasets for measurement'''
        self.ds = self.tune.multiplexer.prepare_measurement_datasets([self._x_parameter])

    def prepare_measurement_datafile(self):
        ''' prepare .hdf/h5 file for measurement'''
        self.tune._prepare_measurement_file(self.ds)
        self.coordinates = self.tune._coordinates
        self.datasets = self.tune._datasets
        self.datafile = self.tune._data_file

    def create_tuning(self):
        ''' creates instance of class Tuning_ST(Tuning)'''
        self.tune = Tuning_EM()
        self.tune.qviewkit_singleInstance = True

    def init_electormigration(self):
        ''' set electromigration parameter for adwin'''
        self._state = 'init_em'
        self.anna.init_electromigration(sample_rate = self._em_params['sample_rate'],
                                    sweep_rate = self._em_params['v_rate'],
                                    report_voltage = self._em_params['v_report'],
                                    max_voltage = self._em_params['v_stop'],
                                    r_limit = self._em_params['r_limit'],
                                    gatesweep = self._em_params['gatesweep'],
                                    gate_dur = self._em_params['gate_dur'])
        self._state = 'em_ready'

    def start_measurement(self):
        ''' create emergency stop button and start activated measurement'''
        if self._state == 'em_ready':
            # create GUI-Window
            gui_window = tk.Tk()
            gui_window.title("Measurement running")

            # Add label and button
            label = tk.Label(gui_window, text="Measurement running...\nClick to stop")
            label.pack(padx=20, pady=10)

            stop_button = tk.Button(gui_window, text="Stop", command=self.stop_measurement, bg="red", fg="white")
            stop_button.pack(padx=20, pady=10)

            self.anna.start_electromigration()
            t = threading.Thread(target=self.tune.measure1D)
            t.start()

            # start GUI
            gui_window.mainloop()
        else:
            log.error(f'Electromigration is not initialized! ({self._state})')

    def set_parameter(self):
        ''' setter for x/y parameter of measurement'''
        self.tune.set_x_parameters(self._sweep['values'], self._sweep['name'], None,
                                    self._sweep['unit'], self.readout_dur)
        self._x_parameter = self.tune._x_parameter

    def em_readout(self):
        ''' measure sweep and generate data dict'''
        res = {}
        #read adwin fifos
        readout_em = self.anna.readout_fifos()
        for key, val in readout_em.items():
            if key in self.valid_inputs:
                if val is not None:
                    res[key] = val
            else:
                log.critical(f'{key} is no valid input var!')
        #calculate additional input vars
        if res:
            step = self.tune.pb.progr
            steps = len(res['current'])
            x_values = self._sweep['values'][step:step+steps]
            for key in self.valid_inputs:
                if not key in res.items():
                    match key:
                        case 'resistance':
                            res['resistance'] = x_values/res['current']
                        case 'conductance':
                            res['conductance'] = res['current']/x_values
        return res

    def create_inputs(self):
        ''' create dictionary for measurement inputs with unit'''
        for key in self.valid_inputs:
            self.inputs_dict[key] = self.unit[key]


    def register_measurement(self):
        ''' register measurement with needed data input dict'''
        print("Input dict: ",self.inputs_dict)
        self.tune.register_measurement('electromigration', self.inputs_dict, self.em_readout)

    def set_node_bounds(self):
        ''' set bounds for data input dict'''
        for key,val in self.inputs_dict.items():
            self.tune.set_node_bounds('electromigration', key, 0, 1e16)

    def activate_measurement(self):
        ''' activate measurement'''
        self.tune.activate_measurement('electromigration')

    def generate_sweep(self):
        ''' generate steps for sweep variable if possible'''
        self._sweep['start'] = self._em_params['v_report']
        self._sweep['stop'] = self._em_params['v_stop']
        self._sweep['rate'] = self._em_params['v_rate']

        #calculate real sample rate and size of virtual voltage steps for data acquisition
        bits = self.anna.aio.get_bits('vd')
        vrange = self.anna.aio.get_scale('vd')
        sweep_rate = self._sweep['rate'] * 2**(bits-1) / vrange
        process_delay = np.round(MCU_frequency/sweep_rate)
        val = MCU_frequency/process_delay
        real_sweep_rate = val * vrange / 2**(bits-1)
        virt_sweep_steps = real_sweep_rate/self._em_params['sample_rate']

        #generate sweep values
        self._sweep['values'] = np.arange(self._em_params['v_report'],
                                        self._em_params['v_stop']+virt_sweep_steps,
                                        virt_sweep_steps)
        self._sweep['unit'] = 'V'
        self._sweep['name'] = 'vd'

    def get_volts(self):
        ''' getter func for electromic params'''
        return self._em_params

    def set_em_params(self,**kwargs):
        ''' setter for multiple electromic params'''
        for key, val in kwargs.items():
            if key in self._em_params.keys():
                match val:
                    case 'v_report' | 'v_stop' | 'v_rate':
                        if isinstance(val, int):
                            if (val <= self.valids[key]) and (val >= 0):
                                self._em_params[key] = val
                            else:
                                log.warning(f'{key} is not in range(0,{self.valids[key]})!')
                        else:
                            log.error(f'Type {type(val)} is not valid for {key}!')
                    case _:
                        self._em_params[key] = val
            else:
                log.error(f'Electromigration params have no key called {key}!')

    def set_update_duration(self, duration):
        ''' setter fuction for the duration between readout of adwin fifos.
        can not be changed during a measurement yet'''
        self.readout_dur = duration
