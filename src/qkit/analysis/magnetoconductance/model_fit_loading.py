import pickle
import numpy as np
from pathlib import Path

def load_model_fit(fpath):
    with open(fpath, 'rb') as f:
        loaded_dict = restructure(pickle.load(f))
        print(f'Found keys: {list(loaded_dict.keys())}')
    return loaded_dict

def restructure(dictionary):
    ''' in laoded_dict the is an entry for sweep and step and then for each
        analyzed step index
        -> here we want to restructure into categories where there is an entry
        for every step '''
    # first copy the string keys
    res = {k: v for k, v in dictionary.items() if isinstance(k, str)}
    # find integer keys (which are the step indices)
    stp_idc = sorted([k for k in dictionary.keys() if isinstance(k, int)])
    res['step_indices'] = np.array(stp_idc)
    # use first step as example
    exmpl =  dictionary[stp_idc[0]]
    # find second layer keys
    second_layer_keys = exmpl.keys()
    # check third layer keys
    third_layer_keys = {k: v.keys() for k, v in exmpl.items() if isinstance(v, dict)}
    # second layer keys become the new main keys
    for slk in second_layer_keys:
        # if no third layer key just create dictionary with idx and value
        if slk not in third_layer_keys.keys():
            res[slk] = {i: dictionary[i][slk] for i in stp_idc}
        else:
            res[slk] = {}
            for tlk in third_layer_keys[slk]:
                res[slk][tlk] = {i: dictionary[i][slk][tlk] for i in stp_idc}
    return res

def get_params(loaded_dict, step_idx):
    params = {}
    for k, v in loaded_dict['params'].items():
        if isinstance(v, dict):
            params[k] = v[step_idx]
        else:
            params[k] = v
    return params