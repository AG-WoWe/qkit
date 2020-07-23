# Quantum machines coherence library
# started by M. Spiecker, 06.2020


import time
import threading

import qkit
from qkit.storage import store as hdf
from qkit.measure.measurement_class import Measurement
import qkit.measure.write_additional_files as waf
from qkit.gui.plot import plot as qviewkit


class QmQkitWrapper:

    def __init__(self):

        self.dirname = ""
        self.comment = ""
        self.sample = None
        self.exp_name = None

        self._measurement_object = Measurement()
        self._measurement_object.measurement_type = 'TimeDomain'
        self._measurement_object.sample = self.sample

        # qkit
        self.coords = {}
        self.values = {}
        self.sourcecode = ""

    # Decorator to start qkit
    def measure(func):
        def wrapper(self, *args, **kwargs):

            save = False
            if 'save' in kwargs:
                save = kwargs['save']
                kwargs.pop('save', None)

            if save:
                qkit.flow.start()

            output = func(self, *args, **kwargs)

            if save:
                if self.dirname:
                    self._file_name = 'QM_experiment_' + self.exp_name + '_' + self.dirname
                else:
                    self._file_name = 'QM_experiment_' + self.exp_name
                self._file_name = self._file_name.replace(' ', '').replace(',', '_')

                self.comment = "hallo" + "\n\n\n" + "vier Lienien weiter"

                self._prepare_measurement_file()
                self.store_data()

                print('Measurement complete: {:s}'.format(self._data_file.get_filepath()))

            else:
                print('Measurement complete')

            return output
        return wrapper

    def _prepare_measurement_file(self):
        '''
        creates the output .h5-file with distinct dataset structures for each measurement type.
        at this point all measurement parameters are known and put in the output file
        '''

        self._data_file = hdf.Data(name=self._file_name, mode='a')
        self._measurement_object.uuid = self._data_file._uuid
        self._measurement_object.hdf_relpath = self._data_file._relpath
        self._measurement_object.instruments = qkit.instruments.get_instrument_names()

        self._measurement_object.save()
        self._mo = self._data_file.add_textlist('measurement')
        self._mo.append(self._measurement_object.get_JSON())

        # instrument settings and logfile
        self._settings = self._data_file.add_textlist('settings')
        settings = waf.get_instrument_settings(self._data_file.get_filepath())
        self._settings.append(settings)

        self._log_file = waf.open_log_file(self._data_file.get_filepath())

    def store_data(self):
        """

        """
        coord_dic = {}

        for key in self.coords:
            coord_vec = self.coords[key][0]
            unit = self.coords[key][1]

            coords_file = self._data_file.add_coordinate(key, unit=unit)
            coords_file.add(coord_vec)
            coord_dic[key] = coords_file

        for key in self.values:
            values = self.values[key][0]
            coord_key_list = self.values[key][1]
            unit = self.values[key][2]

            if len(coord_key_list) == 1:
                value_file = self._data_file.add_value_vector(key, x=coord_dic[coord_key_list[0]], unit=unit)
                value_file.append(values)
            elif len(coord_key_list) == 2:
                value_file = self._data_file.add_value_matrix(key, x=coord_dic[coord_key_list[0]],
                                                              y=coord_dic[coord_key_list[1]], unit=unit)
                # file initialization - workaround
                value_file.append(values[0, :])
            elif len(coord_key_list) == 3:
                value_file = self._data_file.add_value_box(key, x=coord_dic[coord_key_list[0]],
                                                           y=coord_dic[coord_key_list[1]],
                                                           z=coord_dic[coord_key_list[2]], unit=unit)
                # file initialization - workaround
                value_file.append(values[0, 0, :])

            value_file.ds.resize(values.shape)
            value_file.ds[:] = values

        if self.comment:
            self._data_file.add_comment(self.comment)

        qkit.flow.end()

        # save plots and close files
        # t = threading.Thread(target=qviewkit.save_plots, args=[self._data_file.get_filepath()])
        # t.start()

        self._data_file.flush()
        self._data_file.close_file()
        waf.close_log_file(self._log_file)

        # TODO open qkit
        # if self.qviewkit_singleInstance and self.open_qviewkit and self._qvk_process:
        #    self._qvk_process.terminate()  # terminate an old qviewkit instance
