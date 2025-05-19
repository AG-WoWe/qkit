''' This module is supposed to extract data from h5 files saved with qkit using
    the measurement script '''

from ast import literal_eval
import h5py
import json
import numpy as np
from qkit.storage.hdf_file import H5_file

HDF_DATA_DIR = 'entry/data0'

class MapSTExtractor:
    ''' Extract sweep, step and data from hdf file containg map from ST '''
    def __init__(self, fpath, mfunc='sweep_measure'):
        self._h5data0 = h5py.File(fpath, mode='r')[HDF_DATA_DIR]
        self._mfunc = mfunc

    def list_mvars(self):
        ''' Returns and prints list of mvars in h5 file '''
        datasets = self._h5data0.keys()
        res = set()
        for ds in datasets:
            if self._mfunc in ds:
                res.add(ds.split('.')[1].split('_')[0])
        res = sorted(list(res))
        print(f'Found measurement variables: {res}')
        return res

    def list_dirns(self):
        ''' Returns and prints list of trace-directions in h5 file '''
        datasets = self._h5data0.keys()
        res = set()
        for ds in datasets:
            if self._mfunc in ds:
                res.add(ds.split('.')[1].split('_')[1])
        res = sorted(list(res))
        print(f'Found trace directions: {res}')
        return res

    def get_step(self):
        ''' Get step array and metadata of the measurement '''
        # get step dataset
        dataset = self._get_dataset('x')
        # get metadata
        metadata = self._get_metadata(dataset)
        return np.array(dataset, dtype=dataset.attrs.get('dtype')), metadata

    def get_sweep(self):
        ''' Get sweep array and metadata of the measurement '''
        # get sweep dataset
        dataset = self._get_dataset('y')
        # get metadata
        metadata = self._get_metadata(dataset)
        return np.array(dataset, dtype=dataset.attrs.get('dtype')), metadata

    def get_data(self, mvar, dirn):
        ''' Get sweep array and metadata of the measurement '''
        # get dataset of the measurment of mvar_dirn
        dataset = self._h5data0.get(self._get_ds_url(mvar, dirn))
        # get metadata
        metadata = self._get_metadata(dataset)
        return np.array(dataset, dtype=dataset.attrs.get('dtype')), metadata

    def get_data_dict(self, mvars:list=None, dirns:list=None):
        ''' Get data dictionary in format "data[mvar][dirn]" for all specified
            mvars and dirns. If None specified for all mvars, dirns found in
            file. '''
        if mvars is None:
            mvars = self.list_mvars()
        if dirns is None:
            dirns = self.list_dirns()
        data_dict = {mvar: {} for mvar in mvars}
        metadata_dict = {mvar: {} for mvar in mvars}
        for mvar in data_dict:
            for dirn in dirns:
                data, metadata = self.get_data(mvar, dirn)
                data_dict[mvar][dirn] = data
                metadata_dict[mvar][dirn] = metadata
        return data_dict, metadata_dict

    def get_measurement_config(self):
        ''' Return measurement settings '''
        # get the metadata from measurment.config dataset
        settings_ds = self._h5data0['measurement.config']
        metadata = self._get_metadata(settings_ds)
        # repair the nested dictionary entries which are strings now
        for key, val in metadata.items():
            if key not in ['name']:
                # repair null entries which should be None
                val = val.replace('null', 'None')
                val = val.replace('true', 'True')
                val = val.replace('false', 'False')
                # change string dict to python dict
                val = literal_eval(val)
            metadata[key] = val
        return metadata

    def get_sample_rate(self):
        ''' Return sample_rate of measurement '''
        return self.get_measurement_config()['lockin']['sample_rate']

    def _get_ds_url(self, mvar, dirn):
        return f'{self._mfunc}.{mvar}_{dirn}'

    def _get_metadata(self, dataset:h5py.Dataset):
        return dict(dataset.attrs.items())

    def _get_dataset(self, coordinate:str):
        ''' Get dataset of x, or y coordinate '''
        cord_dict = {'x': 0, 'y': 1}
        # read coordinate from measurement dataset
        meas_info = json.loads(list(self._h5data0['measurement'])[0])
        # get dataset
        idx = cord_dict[coordinate]
        dataset = self._h5data0[meas_info['coordinates'][idx].lower()]
        return dataset


class MapSTSaveFile(H5_file):
    ''' Create h5 data in qkit style with datasets loaded from an qkit '''
    def __init__(self, output_file):
        super().__init__(output_file, mode='a')

    def __del__(self):
        print('File closed')
        self.close_file()

    def write_dataset(self, data, metadata:dict):
        ''' write data and metadata of a dataset to a new h5 file '''
        dataset = self.dgrp.create_dataset(metadata['name'],
                                           shape=data.shape,
                                           dtype=data.dtype,
                                           data=data,
                                           )
        self._add_metadata_to_ds(dataset, metadata)

    def write_metadata_ds(self, name, metadata:dict):
        ''' create a dataset holding metadata '''
        metadata['name'] = name
        metadata['ds_dtype'] = 'config'
        self.write_dataset(np.array([]), metadata)

    def _add_metadata_to_ds(self, dataset, metadata:dict):
        ''' add metadata into existing dataset '''
        for key, val in metadata.items():
            if isinstance(val, dict):
                val = str(val)
            else:
                dataset.attrs.create(key, val)
