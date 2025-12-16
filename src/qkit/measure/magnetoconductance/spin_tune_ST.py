''' adjusted spin_tune class for trace measurement at ST'''
from numpy import nan
import qkit
from qkit.gui.notebook.Progress_Bar import Progress_Bar
from qkit.measure.spin_suite.spin_tune import Tuning
from time import sleep

class Tuning_ST(Tuning):

    def measure1D(self, data_to_show = None, readout_dur = 0, stop_event = False):
        """
        Starts a 1D - measurement, along the x coordinate.

        Parameters
        ----------
        data_to_show : List of strings, optional
            Name of Datasets, which qviewkit opens at measurement start.
        readout_dur : float, optional
            time duration between readouts for "live"-plotting
            (default: 0 -> readout after sweep finished)
        stop_event : threading.Event
            Event to signal stopping the measurement.
        """
        assert self._x_parameter, f"{__name__}: Cannot start measure1D. x_parameters required."
        self._measurement_object.measurement_func = "%s: measure1D" % __name__
        if readout_dur == 0:
            self.pb = Progress_Bar(len(self._x_parameter.values)*len(self.multiplexer.get_active_measurements()))

        self._open_qviewkit(datasets = data_to_show)
        try:
            # check if number of triggers matches number of measurements or is zero instead
            no_trigger = len(self.multiplexer.get_active_triggers())
            no_meas = len(self.multiplexer.get_active_measurements())
            if no_trigger != no_meas and no_trigger != 0:
                raise Exception(f"Number of active triggers ({no_trigger}) does not match number of active measurements ({no_meas}). Please check your configuration.")
            
            # cycle all triggers/measurements
            for i in range(no_meas):
                # check for stop event
                if stop_event.is_set():
                    break
                # Trigger measurement
                if no_trigger == 0:
                    direction = 1
                else:
                    direction = self.multiplexer.trigger_with_index(i)
                sweep_samples = 0       # init sample counter
                # perform readouts during sweep until all samples are acquired
                while sweep_samples < len(self._x_parameter.values):
                    # wait (readout_dur) seconds until readout
                    sleep(readout_dur)
                    # Get latest data from measurement
                    latest_data = self.multiplexer.measure_with_index(i)
                    if latest_data:
                        len_latest_data = len(list(latest_data.values())[0])
                        # Check if data is missing and fill with nans if readout stopped returning data
                        if len_latest_data > 0:
                            if len_latest_data + sweep_samples > len(self._x_parameter.values):
                                # calculate how many samples are missing
                                len_latest_data = len(self._x_parameter.values) - sweep_samples
                                # truncate received data to missing length
                                for key in latest_data:
                                    latest_data[key] = latest_data[key][:len_latest_data]
                            # append data to datasets (pointwise = False for 1D)
                            self._append_vector(latest_data, self._datasets, direction = 1)
                        elif len_latest_data == 0 and sweep_samples != 0:
                            # fill missing data with nans
                            for key in latest_data:
                                self._append_vector({key: [nan]*(len(self._x_parameter.values)-sweep_samples)}, self._datasets, direction = 1)
                            len_latest_data = len(self._x_parameter.values)-sweep_samples
                    else:
                        len_latest_data = 0

                    # Update sweep_samples and progress bar
                    sweep_samples += len_latest_data
                    if readout_dur == 0:
                        self.pb.iterate(addend = len_latest_data)

                    # Check for watchdog stop
                    if self.watchdog.stop:
                        break
                    # Check for emergency stop/ stop event
                    if stop_event.is_set():
                        print("Measurement stopped by emergency stop.")
                        for key in latest_data:
                            self._append_vector({key: [nan]*(len(self._x_parameter.values)-sweep_samples)}, self._datasets, direction = 1)
                        break
                    
        finally:
            self.watchdog.reset()
            self._end_measurement()


    def measure2D(self, data_to_show = None, readout_dur = 0, stop_event = False):
        """
        Starts a 2D - measurement, with y being the inner and x the outer loop coordinate.
        
        Parameters
        ----------
        data_to_show : List of strings, optionals
            Name of Datasets, which qviewkit opens at measurement start.
        readout_dur : float, optional
            time duration between readouts for "live"-plotting
            (default: 0 -> readout after sweep finished)
        stop_event : threading.Event
            Event to signal stopping the measurement.
        """
        assert self._x_parameter, f"{__name__}: Cannot start measure2D. x_parameters required."
        assert self._y_parameter, f"{__name__}: Cannot start measure2D. y_parameters required."
        self._measurement_object.measurement_func = f"{__name__}: measure2D"
        self.pb = Progress_Bar(len(self._x_parameter.values)*len(self._y_parameter.values)*len(self.multiplexer.get_active_measurements()))

        self._open_qviewkit(datasets = data_to_show)

        try:
            # check if number of triggers matches number of measurements or is zero instead
            no_trigger = len(self.multiplexer.get_active_triggers())
            no_meas = len(self.multiplexer.get_active_measurements())
            if no_trigger != no_meas and no_trigger != 0:
                raise Exception(f"Number of active triggers ({no_trigger}) does not match number of active measurements ({no_meas}). Please check your configuration.")
            
            sweep_samples = 0       # init sample counter
            # perform sweeps with different x values
            for x_val in self._x_parameter.values:
                # set x parameter
                self._x_parameter.set_function(x_val)
                # advance to next row in 2D datasets for new x value
                if sweep_samples:
                    for dset in self._datasets.values():
                        dset.next_matrix()
                self._acquire_log_functions()
                qkit.flow.sleep(self._x_parameter.wait_time)

                # cycle all triggers/measurements for current x value
                for i in range(no_meas):
                    # reset sample counter for new sweep
                    sweep_samples = 0
                    # check for stop event
                    if stop_event.is_set():
                        break

                    # Trigger measurement
                    if no_trigger == 0:
                        direction = 1
                    else:
                        direction = self.multiplexer.trigger_with_index(i)
                    
                    # perform readouts during sweep until all samples are acquired
                    while sweep_samples < len(self._y_parameter.values):
                            sleep(readout_dur)      # wait between readouts
                            # Get latest data from measurement
                            latest_data = self.multiplexer.measure_with_index(i)
                            if latest_data:
                                len_latest_data = len(list(latest_data.values())[0])
                                # Check if data is missing and fill with nans if readout stopped returning data
                                if len_latest_data > 0:
                                    if len_latest_data + sweep_samples > len(self._y_parameter.values):
                                        # print(f"Warning: More samples received ({len_latest_data+sweep_samples}) than expected ({len(self._y_parameter.values)}). Truncating to fit.")
                                        len_latest_data = len(self._y_parameter.values) - sweep_samples
                                        for key in latest_data:
                                            latest_data[key] = latest_data[key][:len_latest_data]
                                    self._append_vector(latest_data, self._datasets, direction = 1, pointwise=True)
                                elif len_latest_data == 0 and sweep_samples != 0:
                                    # fill missing data with nans
                                    for key in latest_data:
                                        self._append_vector({key: [nan]*(len(self._y_parameter.values)-sweep_samples)}, self._datasets, direction = 1, pointwise=True)
                                    len_latest_data = len(self._y_parameter.values)-sweep_samples
                            else:
                                len_latest_data = 0

                            # Update sweep_samples and progress bar
                            sweep_samples += len_latest_data
                            self.pb.iterate(addend = len_latest_data)

                            # Check for watchdog stop
                            if self.watchdog.stop:
                                break
                            if stop_event.is_set():
                                print("Measurement stopped by emergency stop.")
                                for key in latest_data:
                                    self._append_vector({key: [nan]*(len(self._x_parameter.values)-sweep_samples)}, self._datasets, direction = 1, pointwise=True)
                                break

        finally:
            self.watchdog.reset()
            self._end_measurement()

    def _append_vector(self, latest_data, container, direction, pointwise=False):
        """
        Appends data to the datasets in the container.
        
        Parameters
        ----------
        latest_data : dict
            Dictionary containing the latest data to be appended.
        container : dict
            Dictionary containing the datasets to which the data will be appended.
        direction : int
            Direction of appending (1 for normal, -1 for reverse).
        pointwise : bool, optional
            If True, data is appended to the innermost dimension."""
        for name, values in latest_data.items():
            container[f"{name}"].append(values[::direction], pointwise=pointwise)

    def register_trigger(self, name, get_tracedata_func, *args, **kwargs):
        """
        Registers a trigger.

        Parameters
        ----------
        name : string
            Name of the trigger which is to be registered.
        get_tracedata_func : callable
            Callable object which produces the data for the trigger which is to be registered.
        *args, **kwargs:
            Additional arguments which are passed to the get_tracedata_func during registration.

        Returns
        -------
        None
        """
        self.multiplexer.register_trigger(name, get_tracedata_func, *args, **kwargs)

    def activate_trigger(self, trigger):
        """
        Activates the given trigger.

        Parameters
        ----------
        trigger : string
            Name of the trigger which is to be activated.

        Returns
        -------
        None
        
        Raises
        ------
        KeyError
            If the given trigger doesn't exist.
        """
        self.multiplexer.activate_trigger(trigger)

    def deactivate_trigger(self, trigger):
        """
        Deactivates the given trigger.

        Parameters
        ----------
        trigger : string
            Name of the trigger which is to be deactivated.

        Returns
        -------
        None
        
        Raises
        ------
        KeyError
            If the given trigger doesn't exist.
        """
        self.multiplexer.deactivate_trigger(trigger)