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
    
    @property
    def no_active_nodes(self):
        no_nodes = 0
        for measurement in self.registered_measurements.values():
            if measurement["active"]:
                no_nodes += len(measurement["nodes"])
        return no_nodes
    
    def register_measurement(self, name, nodes, get_tracedata_func, *args, **kwargs):
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
        # print('register_measurement -> trace_data_function: ', get_tracedata_func)
        # print('register_measurement -> type: ', type(get_tracedata_func))
        # print('register_measurements -> name: ', name)
        # print('register_measurement -> nodes: ', nodes)
        # print(f"[register] args: {args}, kwargs: {kwargs}")
        # print(f"[register] calling test: {get_tracedata_func(*args, **kwargs)}")    

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
        
    def prepare_measurement_datasets(self, coords):
        """
        Creates qkit.measure.measurement_base.MeasureBase.Data objects along the coords for each active measurement.

        Parameters
        ----------
        coords : list(qkit.measure.measurement_base.MeasureBase.Coordinate)
            The measurement coordinates along which Data objects will be created.

        Returns
        -------
        datasets : list(qkit.measure.measurement_base.MeasureBase.Data)
        """
        datasets = []
        for name, measurement in self.registered_measurements.items():
            # print('name: ', name, 'measurement: ', measurement)
            if measurement["active"]:
                # print('measurement is active')
                for node, unit in measurement["nodes"].items():
                    datasets.append(mb.MeasureBase.Data(name = f"{name}.{node}",
                                              coords = coords,
                                              unit = unit,
                                              save_timestamp = False))
        assert datasets, f"{__name__}: Tried to initialize an empty measurement dataset. Register and/or activate measurements."
        # print('dataset in multiplexer: ', datasets[0])
        # print('dataset name: ', datasets[0].name)
        # print('dataset coords name : ', datasets[0].coordinates[0].name)
        # print('dataset coords unit: ', datasets[0].coordinates[0].unit)
        # print('dataset coords values: ', datasets[0].coordinates[0].values)
        # print('dataset coords length values: ', len(datasets[0].coordinates[0].values))
        # print('dataset dim: ', datasets[0].dim)
        # print('dataset unit: ', datasets[0].unit)
        # print('dataset kwargs: ', datasets[0].kwargs)
        # print('dataset data set: ', datasets[0].hdf_dataset)
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
            # print('measure function name: ', name)
            # print('measure function measurement: ', measurement)
            if measurement["active"]:
                # print('measure function: active')
                # print(f"[measure] about to call get_tracedata_func: {measurement['get_tracedata_func']}")
                temp = measurement["get_tracedata_func"]()
                # print('measure function temp: ', temp)
                for node, value in temp.items():
                    # print('measure function node: ', node)
                    # print('measure function value: ', value)
                    latest_data[f"{name}.{node}"] = value
        # print('measure function latest data: ', latest_data)
        return latest_data