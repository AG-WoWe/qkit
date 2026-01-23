''' adjusted spin_tune class for trace-retrace measurement for CNTs'''

import qkit
from qkit.gui.notebook.Progress_Bar import Progress_Bar
from qkit.measure.spin_suite.spin_tune import Tuning
from warnings import warn

class Tuning_CNTs(Tuning):
    """
    A class containing measurement routines for non-realtime synchronous data acquisition.
    
    Parents
    -------
    Spin_tune
    Measurement_base

    Attributes
    ----------       
    modes : list of str
        Parameter list which defines how the measurement is done: None (default), "trace", "retrace" or "difference"
    
    Methods
    -------
    register_measurement(name, unit, nodes, get_tracedata_func, *args, modes, **kwargs):
        Registers a measurement.
    
    measure1D(modes) :
        Starts a 1D measurement with the corresponding mode list
    
    measure2D(modes) :
        Starts a 2D measurement with the corresponding mode list
        
    measure3D(modes) :
        Starts a 3D measurement with the corresponding mode list
    """
    
    def register_measurement(self, name,  nodes, get_tracedata_func, *args, modes=None, **kwargs):
        """
        Registers a measurement.

        Parameters
        ----------
        name : string
            Name of the measurement the measurement which is to be registered.
        nodes : dict(string:string)
            The data nodes (keys) of the measurement and units (values) of the respective data node.
        modes : list of strings
            None (default) or must contain "trace", "retrace" or "difference", defines the type of measurement to be launched
        get_tracedata_func : callable
            Callable object which produces the data for the measurement which is to be registered.
        *args, **kwargs:
            Additional arguments which are passed to the get_tracedata_func during registration.

        Returns
        -------
        None
        """
        self.multiplexer.register_measurement(name, nodes, get_tracedata_func,  *args, modes=modes, **kwargs)
        for node in nodes.keys():
            self.watchdog.register_node(f"{name}.{node}", -10, 10)



    def _prepare_empty_container(self, mode=None):
        sweepy = {}
        for name, measurement in self.multiplexer.registered_measurements.items():
            if measurement["active"]:
                for node in measurement["nodes"]:
                    if mode is None:
                        sweepy[f"{name}.{node}"] = []
                    elif isinstance(mode, str):
                        sweepy[f"{name}.{node}.{mode}"] = []
                    else:
                        raise TypeError("The modes should be defined as None or as a str list!")
        return sweepy

    
    def _append_value(self, latest_data, container, modes=None):
        for name, values in latest_data.items():   
            self.watchdog.limits_check(name, values)
            if modes is None:
                key = name
            else:
                key = f"{name}.{modes}"
            container[key].append(float(values))


    

    def measure1D(self, data_to_show = None):
        """
        Starts a 1D - measurement, along the x coordinate with the respecting mode
        
        Parameters
        ----------
        data_to_show : List of strings, optional
            Name of Datasets, which qviewkit opens at measurement start.
        """
        assert self._x_parameter, f"{__name__}: Cannot start measure1D. x_parameters required."
        self._measurement_object.measurement_func = "%s: measure1D" % __name__

        mode_list = self.multiplexer.modes_right_order
        if mode_list is None or len(mode_list) <= 1 :
            pb = Progress_Bar(len(self._x_parameter.values) * self.multiplexer.no_active_nodes)
        else:
            pb = Progress_Bar(2*len(self._x_parameter.values) * self.multiplexer.no_active_nodes)
        
        dsets = self.multiplexer.prepare_measurement_datasets([self._x_parameter], mode_list)
        self._prepare_measurement_file(dsets)
        self._open_qviewkit(datasets = data_to_show)

        try:
            x_vals = self._x_parameter.values
            sweepy = []
            difference = False
            
            if mode_list is None:
                sweepy.append(self._prepare_empty_container())
            elif isinstance(mode_list, list):
                if "difference" in mode_list:
                    difference = True
                    mode_list.remove("difference")
                for i, val in enumerate(mode_list):
                    sweepy.append(self._prepare_empty_container(val))
            
            # if modes in (None, "trace"):
            #     sweep_trace = self._prepare_empty_container()
            # elif modes in ("retrace", "difference"):
            #     sweep_trace = self._prepare_empty_container("trace")
            
            if mode_list is None:
                for x in x_vals:
                    self._x_parameter.set_function(x)
                    qkit.flow.sleep(self._x_parameter.wait_time)
                    latest = self.multiplexer.measure()
                    self._append_value(latest, sweepy[0])
                    pb.iterate(addend=len(latest))
    
                    if self.watchdog.stop:
                        warn(f"{__name__}: {self.watchdog.message}")
                        break
                self._append_vector(sweepy[0], self._datasets, direction=1)

            elif isinstance(mode_list, list):
                for i, val in enumerate(mode_list):
                    match val:
                        case "trace":
                            direction = 1
                        case "retrace":
                            direction = -1
                    for x in x_vals[::direction]:
                        self._x_parameter.set_function(x)
                        qkit.flow.sleep(self._x_parameter.wait_time)
                        latest = self.multiplexer.measure()
                        self._append_value(latest, sweepy[i], modes = val)
                        pb.iterate(addend=len(latest))
        
                        if self.watchdog.stop:
                            warn(f"{__name__}: {self.watchdog.message}")
                            break
        
                    self._append_vector(sweepy[i], self._datasets, direction=direction)
                
                for name, measurement in self.multiplexer.registered_measurements.items():
                    if measurement["active"]:
                        for node in measurement["nodes"]:
                            if len(mode_list) > 1:
                        # if modes in ("retrace", "difference") and not self.watchdog.stop:
                                a = self._data_file.add_view(
                                    f"Trace_retrace_{node}",
                                    x=self._coordinates[self._x_parameter.name],
                                    y=self._datasets[f"{name}.{node}.trace"],
                                )
                                a.add(
                                    x=self._coordinates[self._x_parameter.name],
                                    y=self._datasets[f"{name}.{node}.retrace"]
                                )
                            
                        if difference:
                            sweep_diff = self._prepare_empty_container("difference")
                            trace_container = sweepy[0]
                            retrace_container = sweepy[1]

                            for trace_key, trace_vals in trace_container.items():
                                base = trace_key.replace(".trace", "")
                                retrace_key = f"{base}.retrace"
                                diff_key = f"{base}.difference"

                                retrace_vals = retrace_container[retrace_key]
                                retrace_vals = retrace_vals[::-1]
                                
                                diff_vals = [t - r for t, r in zip(trace_vals, retrace_vals)]

                                sweep_diff[diff_key] = diff_vals
                            
                            self._append_vector(sweep_diff, self._datasets, direction = 1)
                       
            else:
                assert TypeError(type(mode_list))

    

            # if mode == 'retrace':
            #     self._append_vector(sweepy, self._datasets, direction=-1)
    
            # if modes in ("retrace", "difference") and not self.watchdog.stop:
            #     sweep_retrace = self._prepare_empty_container("retrace")
    
                # for x in x_vals[::-1]:
                #     self._x_parameter.set_function(x)
                #     qkit.flow.sleep(self._x_parameter.wait_time)
                #     latest = self.multiplexer.measure()
                #     self._append_value(latest, sweep_retrace)
                #     pb.iterate(addend=len(latest))
    
                #     if self.watchdog.stop:
                #         warn(f"{__name__}: {self.watchdog.message}")
                #         break
    
                # self._append_vector(sweep_retrace, self._datasets, direction=-1)
    

            # if modes == "difference" and not self.watchdog.stop:
            #     for node in self.multiplexer.registered_measurements[self.name_meas]["nodes"]:
            #         t = self._datasets[f"{self.name_meas}.{node}.trace"]
            #         r = self._datasets[f"{self.name_meas}.{node}.retrace"]
            #         d = self._datasets[f"{self.name_meas}.{node}.difference"]
    
            #         for i in range(len(t)):
            #             d.append(t[i] - r[i])
                    
            
        finally:
            self.watchdog.reset()
            self._end_measurement()
       
            
       
    def measure2D(self, data_to_show = None):
        """
        Starts a 2D - measurement, with y being the inner and x the outer loop coordinate.
        
        Parameters
        ----------
        data_to_show : List of strings, optional
            Name of Datasets, which qviewkit opens at measurement start.
        """
        assert self._x_parameter, f"{__name__}: Cannot start measure2D. x_parameters required."
        assert self._y_parameter, f"{__name__}: Cannot start measure2D. y_parameters required."
        self._measurement_object.measurement_func = "%s: measure2D" % __name__   


        mode_list = self.multiplexer.modes_right_order
        if mode_list is None or len(mode_list) <= 1 :
            pb = Progress_Bar(len(self._x_parameter.values) * len(self._y_parameter.values)* self.multiplexer.no_active_nodes)
        else:
            pb = Progress_Bar(2*len(self._x_parameter.values) * len(self._y_parameter.values)* self.multiplexer.no_active_nodes)
        
        dsets = self.multiplexer.prepare_measurement_datasets([self._x_parameter, self._y_parameter], mode_list)        
        self._prepare_measurement_file(dsets)
        self._open_qviewkit(datasets = data_to_show)
        
        try:
            
            x_vals = self._x_parameter.values
            y_vals = self._y_parameter.values            
            difference = False
            if mode_list is not None and "difference" in mode_list:
                    difference = True
                    mode_list.remove("difference")
            
            for x in x_vals:                           
                
                sweepy = []
                self._x_parameter.set_function(x)
                self._acquire_log_functions()
                qkit.flow.sleep(self._x_parameter.wait_time)
                
                if mode_list is None:
                    sweepy.append(self._prepare_empty_container())
                elif isinstance(mode_list, list):           
                    for i, val in enumerate(mode_list):
                        sweepy.append(self._prepare_empty_container(val))
                
                if mode_list is None:
                    for y in y_vals:
                        self._y_parameter.set_function(y)
                        qkit.flow.sleep(self._y_parameter.wait_time)
                        latest = self.multiplexer.measure()
                        self._append_value(latest, sweepy[0])
                        if self.watchdog.stop:
                            warn(f"{__name__}: {self.watchdog.message}")
                            break
                        pb.iterate(addend=len(latest))
                    
                    self._append_vector(sweepy[0], self._datasets, direction=1)
                        
        
                        
                
                elif isinstance(mode_list, list):
                    for i, val in enumerate(mode_list):
                        match val:
                            case "trace":
                                direction = 1
                            case "retrace":
                                direction = -1
                        for y in y_vals[::direction]:
                            self._y_parameter.set_function(y)
                            qkit.flow.sleep(self._y_parameter.wait_time)
                            latest = self.multiplexer.measure()
                            self._append_value(latest, sweepy[i], modes = val)
                            if self.watchdog.stop:
                                warn(f"{__name__}: {self.watchdog.message}")
                                break   
                            pb.iterate(addend=len(latest))
            
                               
                        self._append_vector(sweepy[i], self._datasets, direction=direction)
                    
                    for name, measurement in self.multiplexer.registered_measurements.items():
                        if measurement["active"]:
                            for node in measurement["nodes"]:
                                if len(mode_list) > 1:
                                    a = self._data_file.add_view(
                                        f"Trace_retrace_{node}",
                                        x=self._coordinates[self._x_parameter.name],
                                        y=self._datasets[f"{name}.{node}.trace"],
                                    )
                                    a.add(
                                        x=self._coordinates[self._x_parameter.name],
                                        y=self._datasets[f"{name}.{node}.retrace"]
                                    )


                            if difference:
                                sweep_diff = self._prepare_empty_container("difference")
                                trace_container = sweepy[0]
                                retrace_container = sweepy[1]

                                for trace_key, trace_vals in trace_container.items():
                                    base = trace_key.replace(".trace", "")
                                    retrace_key = f"{base}.retrace"
                                    diff_key = f"{base}.difference"

                                    retrace_vals = retrace_container[retrace_key]
                                    retrace_vals = retrace_vals[::-1]
                                    
                                    diff_vals = [t - r for t, r in zip(trace_vals, retrace_vals)]

                                    sweep_diff[diff_key] = diff_vals


                                self._append_vector(sweep_diff, self._datasets, direction=1)

                                #if difference and not self.watchdog.stop:
                        
                                #    t = self._datasets[f"{name}.{node}.trace"]
                                #    r = self._datasets[f"{name}.{node}.retrace"]
                                #    d = self._datasets[f"{name}.{node}.difference"]

                                #   for i in range(len(t)):
                                #         d.append(t[i] - r[i])
                
                # for y in y_vals:                    
                #     self._y_parameter.set_function(y)
                #     qkit.flow.sleep(self._y_parameter.wait_time)
                #     if modes in (None, "trace"):
                #         latest_data = self.multiplexer.measure()
                #     elif modes in ("retrace", "difference"):
                #         latest_data = self.multiplexer.measure('trace')
                #     self._append_value(latest_data, sweep_trace)

                #     pb.iterate(addend = len(latest_data))

                #     if self.watchdog.stop:
                #         warn(f"{__name__}: {self.watchdog.message}")
                #         break
                # self._append_vector(sweep_trace, self._datasets, direction=1)
                
                
                # if modes in ("retrace", "difference") and not self.watchdog.stop:
                #     sweep_retrace = self._prepare_empty_container("retrace")
                #     for y in y_vals[::-1]:                    
                #         self._y_parameter.set_function(y)
                #         qkit.flow.sleep(self._y_parameter.wait_time)
                #         latest_data = self.multiplexer.measure('retrace')
                #         self._append_value(latest_data, sweep_retrace)
    
                #         pb.iterate(addend = len(latest_data))
    
                #         if self.watchdog.stop:
                #             warn(f"{__name__}: {self.watchdog.message}")
                #             break
                #     self._append_vector(sweep_retrace, self._datasets, direction = -1)
                    
                    
                # if modes == "difference" and not self.watchdog.stop:
                #     for node in self.multiplexer.registered_measurements[self.name_meas]["nodes"]:
                #         t = self._datasets[f"{self.name_meas}.{node}.trace"]
                #         r = self._datasets[f"{self.name_meas}.{node}.retrace"]
                #         d = self._datasets[f"{self.name_meas}.{node}.difference"]
        
                #         for i in range(len(t)):
                #             d.append(t[i] - r[i])
    
                # if modes in ("retrace", "difference") and not self.watchdog.stop:
                #     for node in self.multiplexer.registered_measurements[self.name_meas]["nodes"]:
                #         a = self._data_file.add_view(
                #             f"Trace_retrace_{node}",
                #             x=self._coordinates[self._x_parameter.name],
                #             y=self._datasets[f"{self.name_meas}.{node}.trace"],
                #         )
                #         a.add(
                #             x=self._coordinates[self._x_parameter.name],
                #             y=self._datasets[f"{self.name_meas}.{node}.retrace"]
                #         )
                
                # if self.watchdog.stop: break 

        finally:
            self.watchdog.reset()
            self._end_measurement()    

    def measure3D(self, data_to_show = None):
        """
        Starts a 3D - measurement, with z being the innermost, y the inner and x the outer loop coordinate.

        Parameters
        ----------
        data_to_show : List of strings, optional
            Name of Datasets, which qviewkit opens at measurement start.
        """
        assert self._x_parameter, f"{__name__}: Cannot start measure3D. x_parameters required."
        assert self._y_parameter, f"{__name__}: Cannot start measure3D. y_parameters required."
        assert self._z_parameter, f"{__name__}: Cannot start measure3D. z_parameters required."
        self._measurement_object.measurement_func = "%s: measure3D" % __name__        
        
        mode_list = self.multiplexer.modes_right_order
        if mode_list is None or len(mode_list) <= 1 :
            pb = Progress_Bar(len(self._x_parameter.values)*len(self._y_parameter.values)*len(self._z_parameter.values) * self.multiplexer.no_active_nodes)
        else:
            pb = Progress_Bar(2*len(self._x_parameter.values) *len(self._y_parameter.values)*len(self._z_parameter.values) * self.multiplexer.no_active_nodes)
        
        dsets = self.multiplexer.prepare_measurement_datasets([self._x_parameter, self._y_parameter, self._z_parameter], mode_list)
        self._prepare_measurement_file(dsets)
        self._open_qviewkit(datasets = data_to_show)

        try:
            x_vals = self._x_parameter.values
            y_vals = self._y_parameter.values
            z_vals = self._z_parameter.values
            difference = False        
            if mode_list is not None and "difference" in mode_list:
                    difference = True
                    mode_list.remove("difference")
                    
            for x in x_vals:
                self._x_parameter.set_function(x)
                self._acquire_log_functions()
                qkit.flow.sleep(self._x_parameter.wait_time)

                for y in y_vals:
                    sweepy = []
                    self._y_parameter.set_function(y)
                    qkit.flow.sleep(self._y_parameter.wait_time)
                    if mode_list is None:
                        sweepy.append(self._prepare_empty_container())
                    elif isinstance(mode_list, list):           
                        for i, val in enumerate(mode_list):
                            sweepy.append(self._prepare_empty_container(val))                 
                    
                    if mode_list is None:
                        for z in z_vals:
                            self._z_parameter.set_function(z)
                            qkit.flow.sleep(self._z_parameter.wait_time)
                            latest = self.multiplexer.measure()
                            self._append_value(latest, sweepy[0])
                            pb.iterate(addend=len(latest))
            
                            if self.watchdog.stop:
                                warn(f"{__name__}: {self.watchdog.message}")
                                break
                        self._append_vector(sweepy[0], self._datasets, direction=1)
                    
                    elif isinstance(mode_list, list):
                        for i, val in enumerate(mode_list):
                            match val:
                                case "trace":
                                    direction = 1
                                case "retrace":
                                    direction = -1
                            for z in z_vals[::direction]:
                                self._z_parameter.set_function(z)
                                qkit.flow.sleep(self._z_parameter.wait_time)
                                latest = self.multiplexer.measure()
                                self._append_value(latest, sweepy[i], modes = val)
                                pb.iterate(addend=len(latest))
                
                                if self.watchdog.stop:
                                    warn(f"{__name__}: {self.watchdog.message}")
                                    break      
                        self._append_vector(sweepy[i], self._datasets, direction=direction)
                        
                       # if difference:
                        #     sweep_diff = self._prepare_empty_container("difference")
                         #    t_vals = sweepy[0]
                          #   r_vals = sweepy[1][::-1]
                           #  name, value = sweepy[0].keys()
                            # 
                             #sweep_diff[name.replace("trace", "difference")] = t_vals['name'] - r_vals[name.replace("trace", "retrace")]
                             
                    
                             #self._append_vector(sweep_diff, self._datasets, direction=1)
                        
                        for name, measurement in self.multiplexer.registered_measurements.items():
                            if measurement["active"]:
                     #           for node in measurement["nodes"]:
                     #               if len(mode_list) > 1:
                     #                   a = self._data_file.add_view(
                     #                       f"Trace_retrace_{node}",
                     #                       x=self._coordinates[self._z_parameter.name],
                     #                       y=self._datasets[f"{name}.{node}.trace"],
                     #                   )
                     #                   a.add(
                     #                       x=self._coordinates[self._z_parameter.name],
                     #                       y=self._datasets[f"{name}.{node}.retrace"]
                     #                   )
                                    
                                if difference:
                                    sweep_diff = self._prepare_empty_container("difference")
                                    trace_container = sweepy[0]
                                    retrace_container = sweepy[1]

                                    for trace_key, trace_vals in trace_container.items():
                                        base = trace_key.replace(".trace", "")
                                        retrace_key = f"{base}.retrace"
                                        diff_key = f"{base}.difference"

                                        retrace_vals = retrace_container[retrace_key]
                                        retrace_vals = retrace_vals[::-1]
                                        
                                        diff_vals = [t - r for t, r in zip(trace_vals, retrace_vals)]

                                        sweep_diff[diff_key] = diff_vals


                                    self._append_vector(sweep_diff, self._datasets, direction=1)
                    
                    # if modes == "difference" and not self.watchdog.stop:
                    #     sweep_diff = self._prepare_empty_container("difference")
                    
                    #     for name in sweep_trace:
                    #         t_vals = sweep_trace[name]
                    #         r_vals = sweep_retrace[name][::-1]
                            
                    #         sweep_diff[name.replace("trace", "difference")] = [
                    #             t_vals[i] - r_vals[i] for i in range(len(t_vals))
                    #         ]
                    
                    #     self._append_vector(sweep_diff, self._datasets, direction=1)

        
        
                    # if modes in ("retrace", "difference") and not self.watchdog.stop:
                    #     for node in self.multiplexer.registered_measurements[self.name_meas]["nodes"]:
                    #         a = self._data_file.add_view(
                    #         f"Trace_retrace_{node}",
                    #         x=self._coordinates[self._x_parameter.name],
                    #         y=self._coordinates[self._y_parameter.name],
                    #         z=self._datasets[f"{self.name_meas}.{node}.trace"],
                    #         )
                    #         a.add(
                    #             x=self._coordinates[self._x_parameter.name],
                    #             y=self._coordinates[self._y_parameter.name],
                    #             z=self._datasets[f"{self.name_meas}.{node}.retrace"]
                    #         )

                    
                    # if self.watchdog.stop: break 
                
                
                
                for dset in self._datasets.values():
                    dset.next_matrix()
                if self.watchdog.stop: break
            
            
        finally:
            self.watchdog.reset()
            self._end_measurement()
            
# if __name__ == "__main__":
#     tuning = Tuning()
#     print(tuning.measurement_limit)
#     print(tuning.report_static_voltages)
