import string
import qkit.measure.measurement_base as mb

class Sequential_multiplexer:
    """
    A sequential multiplexer.
    
    Attributes
    ----------
    no_active_nodes: int
        The total number of data_nodes which belong to currently active measurements
    
    Methods
    -------
    register_measurement(name, unit, nodes, get_tracedata_func, *args, **kwargs):
        Registers a measurement.

    activate_measurement(measurement):
        Activates the given measurement.

    deactivate_measurement(measurement):
        Deactivates the given measurement.

    prepare_measurement_datasets(coords):
        Creates qkit.measure.measurement_base.MeasureBase.Data objects along the coords for each active measurement.

    measure(): 
        Calls all active measurements sequentially.
    """
    def __init__(self):
        self.registered_measurements = {}
        self.no_measurements = 0
        self.registered_trigger = {}
        self.no_triggers = 0
    
    @property
    def no_active_nodes(self):
        no_nodes = 0
        for measurement in self.registered_measurements.values():
            if measurement["active"]:
                no_nodes += len(measurement["nodes"])
        return no_nodes
    
    def register_measurement(self, name, nodes,  get_tracedata_func, *args, modes = None, **kwargs):
        """
        Registers a measurement.

        Parameters
        ----------
        name : string
            Name of the measurement which is to be registered.
        nodes : dict(string:string)
            The data nodes (keys) of the measurement and units (values) of the respective data node.
        get_tracedata_func : callable
            Callable object which produces the data for the measurement which is to be registered.
        *args, **kwargs:
            Additional arguments which are passed to the get_tracedata_func during registration.

        Returns
        -------
        None
        """
        if type(name) != str:
            raise TypeError(f"{__name__}: {name} is not a valid experiment name. The experiment name must be a string.")        
        if type(nodes) != dict:
            raise TypeError(f"{__name__}: {nodes} are not valid data nodes. The data nodes must be a dictionary.")
        else:
            for node, unit in nodes.items():
                if type(node) != str:
                    raise TypeError(f"{__name__}: {node} is not a valid data node. A data node must be a string.")
                if type(unit) != str:
                    raise TypeError(f"{__name__}: {unit} is not a valid unit. The unit must be a string.")
        if not callable(get_tracedata_func):
            raise TypeError("%s: Cannot set %s as get_value_func. Callable object needed." % (__name__, get_tracedata_func))
        
        ALLOWED_ORDER = ["trace", "retrace", "difference"]
        ALLOWED_SET = set(ALLOWED_ORDER)
        if modes is None:
            pass
        else:
            if not isinstance(modes, (list, tuple)):
                raise TypeError("modes must be a list of strings or None")
        
            # Check types
            for m in modes:
                if not isinstance(m, str):
                    raise TypeError(f"Invalid mode type: {m!r} (must be str)")
        
            # Check allowed values
            invalid = [m for m in modes if m not in ALLOWED_SET]
            if invalid:
                raise ValueError(f"Invalid mode(s): {invalid}. Allowed: {ALLOWED_ORDER}")
        
            # Remove duplicates while preserving first occurrence (optional but usually wise)
            seen = set()
            unique = []
            for m in modes:
                if m not in seen:
                    seen.add(m)
                    unique.append(m)
        
            # Reorder according to required order
            reordered = [m for m in ALLOWED_ORDER if m in unique]
        
            # Check that the reordered list matches a valid prefix
            # i.e. no gaps like ["trace", "difference"] without "retrace"
            expected_prefix = ALLOWED_ORDER[:len(reordered)]
            if reordered != expected_prefix:
                raise ValueError(
                    f"Invalid mode combination/order: {modes}. "
                    f"Valid options are prefixes of {ALLOWED_ORDER}"
                )
        
            modes = reordered

        self.registered_measurements[name] = {"nodes" : nodes, "get_tracedata_func" : lambda: get_tracedata_func(*args, **kwargs), "active" : False}
        self.no_measurements = len(self.registered_measurements)
    
    def activate_measurement(self, name):
        """
        Activates the given measurement.

        Parameters
        ----------
        measurement : string
            Name of the measurement the measurement which is to be activated.

        Returns
        -------
        None
        
        Raises
        ------
        KeyError
            If the given measurement doesn't exist.
        """
        if name not in self.registered_measurements.keys():
            raise KeyError(f"{__name__}: {name} is not a registered measurement. Cannot activate.")
        self.registered_measurements[name]["active"] = True
    
    def deactivate_measurement(self, name):
        """
        Deactivates the given measurement.

        Parameters
        ----------
        measurement : string
            Name of the measurement the measurement which is to be deactivated.

        Returns
        -------
        None
        
        Raises
        ------
        KeyError
            If the given measurement doesn't exist.
        """
        if name not in self.registered_measurements.keys():
            raise KeyError(f"{__name__}: {name} is not a registered measurement. Cannot deactivate.")
        self.registered_measurements[name]["active"] = False
        
    def prepare_measurement_datasets(self, coords, modes = None):
        """
        Creates qkit.measure.measurement_base.MeasureBase.Data objects along the coords for each active measurement.

        Parameters
        ----------
        coords : list(qkit.measure.measurement_base.MeasureBase.Coordinate)
            The measurement coordinates along which Data objects will be created.
        modes: str: trace, retrace (includes trace) or difference (includes trace and retrace) of the y-parameter

        Returns
        -------
        datasets : list(qkit.measure.measurement_base.MeasureBase.Data)
        """
        datasets = []
        for name, measurement in self.registered_measurements.items():
            if measurement["active"]:
                for node, unit in measurement["nodes"].items():
                    if modes is None:
                        datasets.append(mb.MeasureBase.Data(name = f"{name}.{node}",
                                              coords = coords,
                                              unit = unit,
                                              save_timestamp = False))
                    elif isinstance(modes, list):
                        for val in modes:
                            datasets.append(mb.MeasureBase.Data(name = f"{name}.{node}.{val}",
                                                  coords = coords,
                                                  unit = unit,
                                                  save_timestamp = False))
                    else:
                        raise TypeError(type(modes))
                            
                        
                    # if modes in (None, 'trace'):
                    #     datasets.append(mb.MeasureBase.Data(name = f"{name}.{node}",
                    #                           coords = coords,
                    #                           unit = unit,
                    #                           save_timestamp = False))
                    # if modes in ("retrace", "difference") :
                    #     datasets.append(mb.MeasureBase.Data(name = f"{name}.{node}.trace",
                    #                           coords = coords,
                    #                           unit = unit,
                    #                           save_timestamp = False))
                    #     datasets.append(mb.MeasureBase.Data(name = f"{name}.{node}.retrace",
                    #                           coords = coords,
                    #                           unit = unit,
                    #                           save_timestamp = False))
                    # if modes in ("difference"):
                    #     datasets.append(mb.MeasureBase.Data(name = f"{name}.{node}.difference",
                    #                               coords = coords,
                    #                               unit = unit,
                    #                               save_timestamp = False))
                    # if modes not in ("trace", "retrace", "difference"):
                    #     raise KeyError(f"{__name__}: {modes} is not a valid modes. Allowed modes are trace, retrace and difference.")
        
        assert datasets, f"{__name__}: Tried to initialize an empty measurement dataset. Register and/or activate measurements."
        return datasets
    
    def measure(self):
        """
        Sequentially calls the measurement functions of each active measurement.

        Returns
        -------
        latest_data : dict()
        """
        latest_data = {}
        for name, measurement in self.registered_measurements.items():
            if measurement["active"]:
                temp = measurement["get_tracedata_func"]()
                for node, value in temp.items():
                    latest_data[f"{name}.{node}"] = value
        return latest_data
    
    def register_trigger(self, name, get_tracedata_func, *args, **kwargs):
        """
        Registers a trigger.

        Parameters
        ----------
        name : string
            Name of the trigger which is to be registered.
        get_tracedata_func : callable
            Callable object which produces the data for the measurement which is to be registered.
        *args, **kwargs:
            Additional arguments which are passed to the get_tracedata_func during registration.
        -------
        """
        if type(name) != str:
            raise TypeError(f"{__name__}: {name} is not a valid experiment name. The experiment name must be a string.")
        if not callable(get_tracedata_func):
            raise TypeError("%s: Cannot set %s as get_value_func. Callable object needed." % (__name__, get_tracedata_func))
        
        self.registered_trigger[name] = {"get_tracedata_func" : lambda: get_tracedata_func(*args, **kwargs), "active" : False}
        self.no_triggers = len(self.registered_trigger)

    def activate_trigger(self, name):
        """
        Activates the given trigger.

        Parameters
        ----------
        name : string
            Name of the trigger which is to be activated.
        -------
        Raises
        ------
        KeyError
            If the given trigger doesn't exist.
        """
        if name not in self.registered_trigger.keys():
            raise KeyError(f"{__name__}: {name} is not a registered trigger. Cannot activate.")
        self.registered_trigger[name]["active"] = True

    def deactivate_trigger(self, name):
        """
        Deactivates the given trigger.

        Parameters
        ----------
        name : string
            Name of the trigger which is to be deactivated.
        -------
        Raises
        ------
        KeyError
            If the given trigger doesn't exist.
        """
        if name not in self.registered_trigger.keys():
            raise KeyError(f"{__name__}: {name} is not a registered trigger. Cannot deactivate.")
        self.registered_trigger[name]["active"] = False

    def trigger(self):
        """
        Sequentially calls the trigger functions of each active trigger.

        Returns
        -------
        latest_data : dict()
        """
        latest_data = {}
        for name, trigger in self.registered_trigger.items():
            if trigger["active"]:
                trigger["get_tracedata_func"]()
        return latest_data

    def get_active_triggers(self):
        """
        Gibt eine Liste aller aktiven Trigger-Namen zurück.
        """
        return [name for name, trig in self.registered_trigger.items() if trig["active"]]

    def get_active_measurements(self):
        """
        Gibt eine Liste aller aktiven Messungen zurück.
        """
        return [name for name, meas in self.registered_measurements.items() if meas["active"]]

    def trigger_with_index(self, index):
        """
        Calls the trigger function with index of active triggers.

        Parameters
        ----------
        index : int
            Index of the trigger which is to be called.

        Returns
        -------
        direction : int
        """
        direction = 0
        active_triggers = self.get_active_triggers()
        if index < len(active_triggers):
            name = active_triggers[index]
            trigger = self.registered_trigger[name]
            direction = trigger["get_tracedata_func"]()
        return direction

    def measure_with_index(self, index):
        """
        Calls the measurement function with index of active measurements.

        Parameters
        ----------
        index : int
            Index of the measurement which is to be called.

        Returns
        -------
        latest_data : dict()
        """
        latest_data = {}
        active_measurements = self.get_active_measurements()
        if index < len(active_measurements):
            name = active_measurements[index]
            measurement = self.registered_measurements[name]
            temp = measurement["get_tracedata_func"]()
            for node, value in temp.items():
                latest_data[f"{name}.{node}"] = value
        return latest_data
