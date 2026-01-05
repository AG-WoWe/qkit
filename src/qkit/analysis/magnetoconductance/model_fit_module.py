############## LOAD DATA ######################################################
###############################################################################

import pickle 
import numpy as np
from pathlib import Path
import matplotlib.pyplot as plt
from qkit.analysis.magnetoconductance.data_extraction import MapSTExtractor, qkit_path
from qkit.analysis.magnetoconductance.noise_reduction import remove_sharp_noise_peaks, gaussian_filter
from qkit.analysis.magnetoconductance.estimate_states import remove_linear_slope, fit_two_states
from qkit.analysis.magnetoconductance.state_model_analysis import fit_two_state_fixed_slope, dwell_times_from_states
from qkit.analysis.magnetoconductance.state_model_analysis import total_dwell_time_from_states, extract_jumps_from_states

_JUMPS_DTYPE = [('jpos', 'f4'), ('jamp', 'f4'), ('step', 'f8'), ('sweep_dirn', 'U2')]

RUN_ID = 'HC_2025-12-15'
SUBFOLDER = 'OptimizingSignal'
name = 'T7Z5GI_2D_N_bp'
mvar = 'amp'
dirns = ['trace', 'retrace']

DEFAULT_PARAMS = {
    'fs': None,                           # sample rate of data
    'maf_freq': None,       # Pole frequency of maf filter used during aquisition
    'sigma': None,      # pre filtering strength 
    'fp_distance': 0.2, # Minimum seperation of conductance levels
    'bins': 100,        # bins of conductance histogram
    'penalty': 50,      # penalty for jumps in model fit
    'manual_fixes': {'no_jumps': [],
                    'wp_shift': [],
                    'cond_override': {}
                    }
}

basepath = qkit_path() / 'data'
subpath = Path(f'{RUN_ID}/{SUBFOLDER}/{name}')
lpath = basepath / subpath

def evalue_jumps_by_model(
    lpath, mvar, dirns, params=DEFAULT_PARAMS, idc='all', plot:int=False,
    save=False):
    ''' If ifc is 'all', evaluate all available steps. If it is a list or int,
        the corresponding ones will be caluclated. If you want to plot
        intermediate results, provide the step number as int and only this will
        be evaluated '''

    map = MapSTExtractor((lpath / lpath.name).with_suffix(".h5"), mfunc='measure_')
    step, step_md = map.get_step()
    sweep, sweep_md = map.get_sweep()
    data_raw, data_md = map.get_data_dict(mvars=[mvar], dirns=dirns)
    lockin_conf = map.get_measurement_config()['lockin']

    # Get some parameters from lockin config if not provided
    if params['fs'] is None:
        params['fs'] = lockin_conf['sample_rate']
    if params['maf_freq'] is None:
        params['maf_freq'] = lockin_conf['freq'] / lockin_conf['maf']

    # determine idc array
    if isinstance(idc, (int, np.int64)):
        idc_list = [idc]
    elif idc == 'all':
        if isinstance(plot, int):
            idc_list = [plot]
        else:
            idc_list = range(len(step))

    # create list to hold save paths to return
    savepaths = []

    # loop over requested directions
    for direction in dirns:
        # create results dictionary which holds all results and can be saved later
        results = {'step': step, 'sweep': sweep}

        # Test plotter for debugging
        if isinstance(plot, int):
            fig, axes = plt.subplots(4, figsize=(8,12))
        else:
            axes = [None, None, None, None]


        #loop over requested indices
        for idx in idc_list:

            # HANDLE EXCEPTIONS Seperately
            if idx in params['manual_fixes']['no_jumps'] or idx in params['manual_fixes']['wp_shift']:
                continue

            # LOAD DATA
            print('Bp =', step[idx], 'idx =', idx)
            x = sweep
            all_traces = data_raw[mvar][direction]
            y = all_traces[idx, :]

            # STEP 1: REMOVE NOISE
            if params['sigma'] is not None:
                y = gaussian_filter(y, params['sigma'])
            # REMOVE SHARP NOISE PEAKS HAS A LOT OF DEFUALT ARGUMENTS WHICH USUALLY DONT NEED TO BE PROVIDED
            y = remove_sharp_noise_peaks(y, params['fs'], ax_results=axes[0])

            # STEP 1.5 : REMOVE LINEAR BACKGROUND 
            y, m, b_center, gap = remove_linear_slope(
                x, y, idx, all_traces, include_neighbors=10, istart=None,
                istop=None, ax=axes[1]
            )

            # Step 2: FIT MODEL
            man_cond_ovrd = params['manual_fixes']['cond_override']
            if 'all' in man_cond_ovrd:
                cond_lvls = {}
            else:
                cond_lvls = fit_two_states(y, params['bins'], fp_distance=params['fp_distance'], ax=axes[2])
                #print(f" std1 = {cond_lvls['std1']}, std2 = {cond_lvls['std2']}")
            if idx in man_cond_ovrd:
                if 'high' in man_cond_ovrd[idx]:
                    cond_lvls['mu2'] = man_cond_ovrd[idx]['high']
                    cond_lvls['std2'] = man_cond_ovrd['std']
                if 'low' in man_cond_ovrd[idx]:
                    cond_lvls['mu1'] = man_cond_ovrd[idx]['low']
                    cond_lvls['std1'] = man_cond_ovrd['std']
            if 'all' in man_cond_ovrd:
                if 'high' in man_cond_ovrd['all']:
                    cond_lvls['mu2'] = man_cond_ovrd['all']['high']
                    cond_lvls['std2'] = man_cond_ovrd['std']
                if 'low' in man_cond_ovrd['all']:
                    cond_lvls['mu1'] = man_cond_ovrd['all']['low']
                    cond_lvls['std1'] = man_cond_ovrd['std']
            mean_std = np.mean([cond_lvls['std1'], cond_lvls['std2']])

            # calculate two state with linear slope solution
            _, states = fit_two_state_fixed_slope(
                x, y, cond_lvls['mu1'], cond_lvls['mu2'], mean_std,
                int(round(params['fs']/params['maf_freq'])), params['penalty'],
                ax=axes[3], xlabel='x', ylabel='conductance (S)')

            # Step 3: EXTRACT JUMPS
            jump_idc = extract_jumps_from_states(x, states, return_indices=True)
            nb_jumps = len(jump_idc['up']) + len(jump_idc['down'])
            dwell = dwell_times_from_states(x, states)
            total_dwell = total_dwell_time_from_states(x, states, return_fraction=True)

            # Step 3: SAVE USE SETTING 
            results[idx] = {'nb_jumps': nb_jumps,
                            'jump_idc': jump_idc,
                            'dwell_times': dwell,
                            'total_dwell': total_dwell,
                            'conductance_levels': cond_lvls,
                            'params': params}

        
        savepath = lpath.parent / f"{lpath.name.split('_')[0]}_model_fit_pen{params['penalty']}_dirn_{direction}.pkl"
        with open(savepath, 'wb') as f:
            pickle.dump(results, f)
            savepaths.append(savepath)
    return savepaths