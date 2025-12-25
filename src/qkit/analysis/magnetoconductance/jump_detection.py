from typing import Literal
import numpy as np
import matplotlib.pyplot as plt
from scipy.ndimage import gaussian_filter1d, uniform_filter1d
from scipy.signal import find_peaks, peak_widths
from scipy.optimize import curve_fit
from copy import deepcopy


_JDIRN = Literal["up", "down"]
_JDIRNS_DICT = {'up': 1, 'down': -1}
_DETECT = Literal['highest', 'all']
_FILTER_FUNC = Literal['gauss', 'uni']
_JUMPS_DTYPE = [('jpos', 'f4'), ('jamp', 'f4'), ('step', 'f8'), ('sweep_dirn', 'U2')]

def double_gaussian(x, A1, mu1, sigma1, A2, mu2, sigma2):
    ''' Convolution of two gaussian peaks without y offset'''
    gauss1 = A1 * np.exp(-(x - mu1)**2 / (2 * sigma1**2))
    gauss2 = A2 * np.exp(-(x - mu2)**2 / (2 * sigma2**2))
    return gauss1 + gauss2

def slice_arrays_by_x_values(x, y, xlim:tuple=(None, None)):
    ''' Return a sublist of y, cut off at idicees where x < min and x > max '''
    if len(x) == len(y) and None not in xlim:
        xmin = xlim[0]
        xmax = xlim[1]
        idc = sorted((np.abs(x - xmin).argmin(), np.abs(x - xmax).argmin()))
        return x[idc[0]: idc[1]], y[idc[0]: idc[1]]
    return x, y

def derivate(y):
    ''' Calculate sample vise derivative of array '''
    return np.diff(y, n=1, append=2*y[-1]-y[-2])

def remove_duplicates(seq):
    ''' Remove duplicates from sequence without loosing order '''
    seen = set()
    seen_add = seen.add
    return [x for x in seq if not (x in seen or seen_add(x))]

def detect_jumps_by_slope(x, y, detect:_DETECT, xlim:tuple=(None, None),
                          min_slope:(int, float)=None):
    ''' Detect jump (x value and "amplitude") in direction jdirn by looking for
        the heighest slope in range xlim[0] < x xlim[1] with amplitude above
        min_slope '''
    # Calculate derivative
    d = derivate(y)
    # Slice array to only look in a specific range
    x_subset, d_subset = slice_arrays_by_x_values(x, d, xlim)
    # if min_slope is automatic, calulate min_slope from variation in d
    if min_slope == 'auto':
        # wmean = np.sum(x * d) / np.sum(d)
        # print(np.sum(d), np.sum(x * np.square(d - wmean) / np.sum(d)))
        # wmu = np.sqrt(np.sum(x * np.square(d - wmean) / np.absolute(np.sum(d))))
        # min_slope = 2 * wmu
        mu = np.sqrt(np.sum(np.square(d) / len(d)))
        min_slope = 2.5 * mu
        print(min_slope)
    jumps = []
    # loop over both jump directions
    for jdir in [1, -1]:
        # Peakfinder: change sign of derivative depending on jump direction
        peak_indices, _ = find_peaks(d_subset * jdir, height=min_slope)
        if len(peak_indices) > 0:
            if detect == 'highest':
                peak_idx = peak_indices[np.argmax(d_subset[peak_indices] * jdir)]
                jumps.append((peak_idx, d_subset[peak_idx]))
            elif detect == 'all':
                for peak_idx in peak_indices:
                    jumps.append((peak_idx, d_subset[peak_idx]))
            else:
                raise NotImplementedError
    # Sort jumps by index and translate position into x value
    jumps = [(x_subset[j[0]], j[1]) for j in sorted(jumps)]
    return jumps

def create_bin_edges(x, average=None):
    ''' create bin edges from x values, so that every x value is in the middle
        of the bin edge. average is the amount of x values which will be
        combined into one bin, so that the bin edges are around this amount of
        values. '''
    # determine mean distance between samples
    if average is None:
        bin_mids = x
    else:
        raise NotImplementedError
    diff = np.mean(np.diff(bin_mids))
    first_edge = bin_mids[0] - diff / 2
    last_edge = bin_mids[-1] + diff / 2
    edge_num = len(bin_mids) + 1
    bin_edges = np.linspace(first_edge, last_edge, edge_num, endpoint=True)
    return bin_edges, bin_mids

def fit_double_gaussian(x, y, init_guess='peakfinder', plot=False, **kwargs):
    ''' Fit double gaussian function on x,y data. For the initial guess of the
        fit parameter two automatic methods are available: peakfinder and
        statistics '''
    # create plot
    if plot:
        _, ax = plt.subplots()
        ax.plot(x, y, label='data')

    if init_guess == 'peakfinder':
        ### FIND INITIAL PARAMETERS BY GAUSSIAN SMOOTHING AND PEAK_FINDER
        # calculate sigma if not given
        sigma = kwargs['sigma'] if 'sigma' in kwargs else len(x) / 25
        # apply gaussian filter
        hist_f = gaussian_filter1d(y, sigma)
        if plot:
            ax.plot(x, hist_f, label='smoothed data')
        # find initial parameters for peak_finder
        wmean_pos = np.sum(x * y) / np.sum(y)
        wmu = np.sqrt(np.sum(y * np.square(x - wmean_pos) / np.sum(y)))
        min_peak_distance_samples = wmu / (x[1] - x[0])
        peak_indices, _ = find_peaks(hist_f, distance=min_peak_distance_samples)
        # find only the two highest peaks
        peak_idcs = peak_indices[np.argsort(hist_f[peak_indices])[-2:]]
        # get peak width in samples
        peak_width, _, _, _ = peak_widths(hist_f, peak_idcs, rel_height=0.5)
        # convert to peak width in x value
        peak_width = [(x[1]-x[0]) * width / 2 for width in peak_width]
        # get peak heights in y value
        peak_heights = hist_f[peak_idcs]
        # get peak_positions in x value
        peak_positions = x[peak_idcs]
        # init parameters
        p0 = [peak_heights[0], peak_positions[0], peak_width[0],
              peak_heights[1], peak_positions[1], peak_width[1]]

    elif init_guess == 'statistics':
        ### FIND INITIAL PARAMETERS BY SIMPLE CALCULATIONS
        wmean_pos = np.sum(x * y) / np.sum(y)
        wmu = np.sqrt(np.sum(y * np.square(x - wmean_pos) / np.sum(y)))
        p0 = [np.max(y), wmean_pos-wmu, wmu/2, np.max(y), wmean_pos+wmu, wmu/2]
    else:
        raise NotImplementedError

    bounds = ((0, x[0], x[1] - x[0]) * 2,            #lower bounds
              (np.max(y), x[-1], x[-1] - x[0]) * 2)  #upper bounds

    # plot estimated peaks and sigma
    if plot:
        ax.errorbar([p0[1], p0[4]], [p0[0], p0[3]], xerr=[p0[2], p0[5]],
                    marker='X', linestyle='', label='estimated peaks')

    # fit double gaussian
    popt, _ = curve_fit(double_gaussian, x, y, p0=p0, bounds=bounds)
    # plot gaussian fit
    if plot:
        ax.plot(x, double_gaussian(x, *popt), label='fit')
        # plot found peaks and sigma
        ax.errorbar([popt[1], popt[4]], [popt[0], popt[3]], xerr=[popt[2], popt[5]],
                    marker='X', linestyle='', label='fittet peaks')
        ax.legend()
    return popt[1], popt[2], popt[4], popt[5]

def detect_jumps_by_states(x, y, top_thrs, bottom_thrs, plot=False):
    ''' Detect all jumps which happen between the top_thrs and bottom_thrs.
        As position of the jump the moment the y values leave the cross the 
        threshold counts '''
    # transform conductance values into states by top and bottom threshold
    states = np.empty(len(y))
    for i, val in enumerate(y):
        if val >= top_thrs:
            states[i] = 1
        elif val <= bottom_thrs:
            states[i] = 0
        else:
            states[i] = np.nan
    # if nan is at the end of the states: replace with previos non nan state
    if np.isnan(states[-1]):
        states[-1] = states[np.where(~np.isnan(states))[0][-1]]
    # from the back of the array, fill al nans with the previos value
    # -> from the beginning the state transistion happens as soon as the well
    # defined state is left into the nan or other states regime.
    nans = np.isnan(states)
    for i, val in reversed(list(enumerate(nans))):
        if val:
            states[i] = states[i+1]
    # now that we always contribute a state to each datapoint, we just look for 
    # state transitions: +1 -> jump up, -1 -> jump down
    transitions = np.diff(states)
    # transition with +1 are up jumps and -1 are down jumps
    ju = [(idx, 1) for idx in np.where(transitions == +1)[0]]
    jd = [(idx, -1) for idx in np.where(transitions == -1)[0]]
    # sort jumps by idx (to sort always in direction the data is given)
    jumps = sorted(ju + jd)
    # tanslate jump idx in x value
    jumps = [(x[jump[0]], jump[1]) for jump in jumps]
    if plot is True:
        _, ax = plt.subplots()
        tr_line = ax.plot(x, y)
        col = tr_line[0].get_color()
        ax.axhspan(top_thrs, np.max(y), color=col, alpha=0.2)
        ax.axhspan(np.min(y), bottom_thrs, color=col, alpha=0.2)
        for j in jumps:
            pos = j[0]
            jdir = j[1]
            if jdir == 1:
                ax.annotate("", xytext=(pos, bottom_thrs), xy=(pos, top_thrs),
                            arrowprops=dict(arrowstyle="->", color='red'))
            elif jdir == -1:
                ax.annotate("", xytext=(pos, top_thrs), xy=(pos, bottom_thrs),
                            arrowprops=dict(arrowstyle="->", color='red'))
    return jumps


class DataTreatment():
    ''' Class handles filtering and subsampling of a single measurement
        variable (data) together with its x (step), and y(sweep) values '''
    def __init__(self, sweep:np.array, data:np.ndarray):
        self._sweep = sweep
        self._data_raw = data
        self.data_filtered = None

    def test_filter(self, step_idx, filter_func, filter_val, subsampling=None):
        ''' Test filtering and subsampling on sweep number 'step_idx' '''
        x = self._sweep
        y = self._data_raw[step_idx, :]
        yf = self.filter_single_trace(y, filter_func, filter_val)
        _, ax = plt.subplots()
        ax.plot(x, y)
        ax.plot(x, yf)
        if subsampling:
            ax.plot(x[::subsampling], yf[::subsampling], linestyle='', marker='.')
        plt.tight_layout()

    def apply_filter(self, filter_func:_FILTER_FUNC, filter_val):
        ''' Apply filter on data array for each measurement'''
        match filter_func:
            case 'uni':
                self.data_filtered = uniform_filter1d(self._data_raw,
                                                      filter_val,
                                                      axis=1)
            case 'gauss':
                self.data_filtered = gaussian_filter1d(self._data_raw,
                                                       order=0,
                                                       sigma=filter_val,
                                                       axis = 1)
            case None:
                self.data_filtered = self._data_raw
            case _:
                raise NotImplementedError(f"Filter {filter_func} not implemented!")

    def filter_single_trace(self, trace, filter_func, filter_val):
        ''' Return single trace with filter applied '''
        match filter_func:
            case 'uni':
                return uniform_filter1d(trace, filter_val)
            case 'gauss':
                return gaussian_filter1d(trace, order=0, sigma=filter_val)
            case _:
                raise NotImplementedError(f"Filter {filter_func} not implemented!")

    def get_subsampled(self, subsampling):
        ''' Get sweep and data subsampled '''
        sweep = self._sweep[::subsampling]
        if self.data_filtered is not None:
            data = self.data_filtered[:, ::subsampling]
        else:
            data = self._data_raw[:, ::subsampling]
        return sweep, data

    def get_measurement(self):
        ''' Get sweep and data '''
        return self.get_subsampled(subsampling=1)

    def get_filtered_measurement(self, filter_func, filter_val, subsampling=1):
        ''' Get filtered sweep and data (sweep is necessary if subsampling is
            applied)'''
        self.apply_filter(filter_func, filter_val)
        print(self.data_filtered.shape)
        return self._sweep[::subsampling], self.data_filtered[:, ::subsampling]


class JumpDetective:
    ''' The module takes an object of the HDFData class to extract measurement data
    from a .h/hdf5 file and detect jumps in the sweeps. The HDFData object
    can also be used to save the detected jumps in the .h/hdf5 file analysis0 group.'''
    # TO DO: USE DATATREATMENT CLASS INSTEAD OF EXTERNAL FUNCTIONS TO AVOID
    # APPLYING CHANGES ONLY TO ONE PART IN THE FUTURE??
    def __init__(self, step, sweep, data, **params):
        self._step = step
        self._sweep_raw = sweep
        self._sweep = sweep
        self._data_raw = data
        self._data = {**self._data_raw}

        self._jumps = None
        self._filter_applied = (None, None, None)

        self._params = {# filtering
                        'filter_func': None,
                        'filter_val': None,
                        'subsampling': 1,
                        # analyze what
                        'dirns': ['trace', 'retrace'],
                        'jdirs': {'trace': -1, 'retrace': 1},
                        'sel_steps': range(len(self._step)),
                        # jump detection
                        #'method': (
                        #    'slope', 
                        #    {'detect': 'highest',
                        #     'min_slope': {'trace': 0, 'retrace': 0}}), 
                        'method': ('states', {'guess': 'peakfinder', 'simga': 2, 's_range': 5}),
                                            'min_slope': {'trace': 0, 'retrace': 0},
                        # jump selection
                        'detect': 'highest',  # 'highest, 'all'
                        'select': 'first',    # 'first', 'last', 'all'
                        'xlim': {
                            'trace': (None, None),
                            'retrace': (None, None)},
                        # plot details
                        'jdirn_label': {
                            'trace': {'down': 'down', 'up': 'up'},
                            'retrace': {'down': 'down', 'up': 'up'}},
                        }
        self.update_params(**params)

    def plot_sweep(self, step, dirn, step_unit='index'):
        ''' Plot single sweep '''
        if 'val' in step_unit:
            idx = np.abs(self._step - step).argmin()
        elif step_unit == 'index':
            idx = step
        fig, ax = plt.subplots()
        ax.plot(self._sweep, self._data[dirn][idx])

    def test_filter(self, step_idx, **params):
        ''' Apply filter on single sweep and plot result '''
        backup_params = deepcopy(self._params)
        self.update_params(**params)
        ffunc = self._params['filter_func']
        fval = self._params['filter_val']
        subs = self._params['subsampling']
        _, ax = plt.subplots()
        yf_dict = {}
        for dirn in self._params['dirns']:
            x = self._sweep_raw
            y = self._data_raw[dirn][step_idx, :]
            dt = DataTreatment(x, np.array([y]))
            xf, yf_arr = dt.get_filtered_measurement(ffunc, fval, subs)
            yf_dict[dirn] = yf_arr[0]
            ax.plot(x, y, alpha = 0.7, label=dirn)
            ax.plot(xf, yf_dict[dirn], color=ax.get_lines()[-1].get_color())
        ax.legend()
        plt.tight_layout()
        self.update_params(**backup_params)
        return xf, yf_dict

    def test_jump_detection(self, step_val=None, step_idx=None, apply_filter=True, **params):
        ''' To test jump detection plot raw_data and filtered data, deviation
                and detected peaks '''

        # check that excactly one of  step_val or step_idx are given
        if not (step_val is None) ^ (step_idx is None):
            raise Exception('Either specify step_val or step_idx')
        # then either use step_idx or calculate idx from step_val
        if isinstance(step_val, (float, int)):
            idx = np.abs(self._step - step_val).argmin()
        elif isinstance(step_idx, int):
            idx = step_idx
        # save parameters and override with temporarily given ones
        backup_params = deepcopy(self._params)
        self.update_params(**params)
        dirns = self._params['dirns']
        method = self._params['method'][0]
        options = self._params['method'][1]
        if apply_filter:
            x, y_dict = self.test_filter(idx)
        else:
            x = self._sweep
            y_dict = {dirn: self._data_raw[dirn][idx, :] for dirn in dirns}
        if method == 'slope':
            _, ax = plt.subplots()
            for dirn in dirns:
                if dirn == 'retrace':
                    x = np.flip(x)
                    y = np.flip(y_dict[dirn])
                else:
                    y = y_dict[dirn]
                # get jumps as detected by function
                jmps = detect_jumps_by_slope(x, y, options['detect'],
                                            self._params['xlim'][dirn],
                                            options['min_slope'][dirn])
                # calcutate derivative as the detection function does
                d = derivate(y)
                ax.plot(x, d, label=dirn)
                for j in jmps:
                    ax.plot(j[0], j[1], linestyle='', marker='X', color='red')
                # plot histogram of derivative values
                _, ax = plt.subplots()
                ax.hist(d, bins=50)
            ax.legend()
        elif method == 'states':
            guess = options['guess']
            sigma_lvl = options['sigma_lvl']
            s_range = options['s_range']
            for dirn in dirns:
                if dirn == 'retrace':
                    x = np.flip(x)
                    y = np.flip(y_dict[dirn])
                else:
                    y = y_dict[dirn]
                tthres, bthres = self.determine_state_thresholds(idx, s_range, guess, sigma_lvl)
                jmps = detect_jumps_by_states(x, y, tthres, bthres, plot=True)
        else:
            raise Exception('fuck you')
        print(jmps)
        self.update_params(**backup_params)

    def apply_filter(self, **params):
        ''' Apply filter (and subsampling if wanted) on measured data'''
        self.update_params(**params)
        ffunc = self._params['filter_func']
        fval = self._params['filter_val']
        subs = self._params['subsampling']
        # check if this filter has been apllied already
        if self._filter_applied == (ffunc, fval, subs):
            print('Same filter already applied')
            return
        # apply filter on data
        for dirn in self._data:
            dt = DataTreatment(self._sweep_raw, self._data_raw[dirn])
            self._sweep, self._data[dirn] = dt.get_filtered_measurement(ffunc,
                                                                        fval,
                                                                        subs)
        # set flags which filters have been applied already
        self._filter_applied = (ffunc, fval, subs)

    def determine_state_thresholds(self, step_idx, s_range=5, guess='peakfinder',
                                   sigma_lvl=2, bins=50,  **params):
        ''' Take the y values of the step_idx and s_range sweeps to left and
            right to determine the two y value states between the system is
            jumping. There are to methods (peakfinder and statistics) to guess
            the initial parameters. Sigma_lvl determines how far the threshold
            is away from the center of the states. '''
        if step_idx < s_range:
            sw_win = (0, 2 * s_range + 1)
        elif (len(self._step) - step_idx) < s_range:
            sw_win = (-(2*(s_range + 1)), -1)
        else:
            sw_win = (step_idx - s_range, step_idx + s_range + 1)
        # get all data in range and put in a long array
        data = np.concatenate(
            (self._data['trace'][sw_win[0]:sw_win[1], :].flatten(),
            self._data['retrace'][sw_win[0]:sw_win[1], :].flatten())
        )
        bin_edges = np.linspace(np.min(data), np.max(data), num=bins+1, endpoint=True)
        bin_mids = np.array([(bin_edges[i] + bin_edges[i+1]) / 2 for i in range(len(bin_edges)-1)])
        counts, _ = np.histogram(data, bins=bin_edges)
        # fit two gaussian peaks on the histogram to get the top and bottom
        # threshold for defining the conductance states
        lp, ls, rp, rs = fit_double_gaussian(bin_mids, counts, init_guess=guess)
        thrs = sorted(zip([lp, rp], [ls, rs]))
        top_thrs = thrs[1][0] - sigma_lvl * thrs[1][1]
        bottom_thrs = thrs[0][0] + sigma_lvl * thrs[0][1]
        # if thresholds overlap -> method not sufficient without further smoothing
        if bottom_thrs > top_thrs:
            print('WARNING: PEAK SEPERATION NOT SUFFICIENT')
            mid_thrs = (top_thrs + bottom_thrs) / 2
            top_thrs = mid_thrs
            bottom_thrs = mid_thrs
        return top_thrs, bottom_thrs

    def analyze_single_sweep(self, step_idx, dirn, **params):
        ''' Detect jumps in sweep with step_idx and direction. If filter_single
            is active, the sweep data will be filtered fresh from the raw data.
            Otherwise the data is been taking as it was treated before '''
        self.update_params(**params)
        method = self._params['method'][0]
        options = self._params['method'][1]
        if dirn == 'trace':
            x = self._sweep
            y = self._data[dirn][step_idx, :]
        elif dirn == 'retrace':
            x = np.flip(self._sweep)
            y = np.flip(self._data[dirn][step_idx, :])
        else:
            raise NotImplementedError
        if method == 'slope':
            jmps = detect_jumps_by_slope(x, y, options['detect'],
                                         self._params['xlim'][dirn],
                                         options['min_slope'][dirn])
        elif method == 'states':
            guess = options['guess']
            sigma_lvl = options['sigma_lvl']
            s_range = options['s_range']
            tthres, bthres = self.determine_state_thresholds(step_idx, s_range, guess, sigma_lvl)
            jmps = detect_jumps_by_states(x, y, tthres, bthres)
        else:
            raise NotImplementedError
        return jmps

    def analyze_all_steps(self, **params):
        ''' Analyze all measurements for jumps specified by params '''
        self.update_params(**params)
        dirns = self._params['dirns']
        sel_steps = self._params['sel_steps']
        jumps = []
        for i in sel_steps:
            for d in dirns:
                jmps = self.analyze_single_sweep(i, d)
                # if at leat one jump was detected, append all jumps
                if len(jmps):
                    for j in jmps:
                        jumps.append((j[0], j[1], self._step[i], d[:2]))
                # append nan if jump was not detected
                else:
                    jumps.append((np.nan, np.nan, self._step[i], d[:2]))
        self._jumps = np.array(jumps, dtype=_JUMPS_DTYPE)
        return self._jumps

    def get_sweep(self, dirn, i):
        ''' return x, y of i-th sweep with mvar and trace '''
        return self._sweep, self._data[dirn][i, :]

    def update_params(self, **kwargs):
        ''' update filter and peak select param'''
        for key, value in kwargs.items():
            if key in self._params:
                self._params[key] = value
            else:
                print('WARNING: unsupported argument given!')

    def get_params(self):
        ''' Get params dictionary '''
        return self._params

    def get_conductance_histogram(self, step, step_unit='index', bin_edges=False, bins=100, density=False, plot=False):
        ''' Calculate (and plot if wanted) histrogramm of conductance values
            for sweep '''
        # use some standard values depending on given data
        dirns = list(self._data.keys())
        # handle different step inputs (index vs value)
        if 'val' in step_unit:
            idx = np.abs(self._step - step).argmin()
        elif step_unit == 'index':
            idx = step
        else:
            raise NotImplementedError
        # conductance histogram
        if 'trace' in dirns:
            yt = self._data['trace'][idx, :]
        else:
            yt = []
        if 'retrace' in dirns:
            yr = self._data['retrace'][idx, :]
        else:
            yr = []
        y = np.concatenate([yt, yr])
        if bin_edges is False:
            bin_edges = np.linspace(np.min(y), np.max(y), num=bins+1, endpoint=True)
        bin_mids = [bin_edges[i] + shift for i, shift in enumerate(np.diff(bin_edges))]
        counts, _ = np.histogram(y, bins=bin_edges)
        if density is True:
            counts = counts / np.sum(counts)
        if plot:
            _, ax = plt.subplots()
            ax.plot(bin_mids, counts)
        return counts

    def check_conductance_stability(self, ax, bins=100, density=False, spath=False, **kwargs):
        ''' Plot a colormap where a histogram of the data per sweep is on the y
            axis and the steps on the x axis '''
        # use some standard values depending on given data
        dirns = list(self._data.keys())
        # Find max and min conductance values
        vmin = np.min([np.min(self._data[dirn]) for dirn in dirns])
        vmax = np.max([np.max(self._data[dirn]) for dirn in dirns])
        # Create bin_num bin_edges for histogram between min and max
        bin_edges = np.linspace(vmin, vmax, num=bins+1, endpoint=True)
        # Find the middle value of each bin
        bin_mids = np.empty(bins)
        for i in range(bins):
            bin_mids[i] = (bin_edges[i] + bin_edges[i+1]) / 2
        # Create the data array holding all the histogram data
        C = np.empty((bins, len(self._step)))
        # Calculate all histograms
        for idx, _ in enumerate(self._step):
            counts = self.get_conductance_histogram(idx, bins=bins, bin_edges=bin_edges, density=density)
            C[:, idx] = counts
        if 'xlab' in kwargs:
            ax.set_xlabel(kwargs['xlab'])
            del kwargs['xlab']
        else:
            ax.set_xlabel('step variable')
        if 'ylab' in kwargs:
            ax.set_ylabel(kwargs['ylab'])
            del kwargs['ylab']
        else:
            ax.set_ylabel('measurment variable')
        pcm = ax.pcolormesh(self._step, bin_mids, C, **kwargs)
        if density is True:
            ax.figure.colorbar(pcm, ax=ax, label='Percentage')
        else:
            ax.figure.colorbar(pcm, ax=ax, label='Count')
        if spath:
            plt.savefig(spath)


class JumpAnalyzer:
    ''' This Class takes a structured array of detected jump as should be
        produced by any JumpDetection method and handles selection and
        analysis of the jump events '''
    def __init__(self, step, sweep, jumps, hyst=0, offset=0):
        self._step = step
        self._sweep = sweep
        if hyst | offset:
            self.jumps = self.hyst_compensation(jumps, hyst, offset)
        else:
            self.jumps = jumps
        self.params = { 'jdir_sel': {'trace': None, 'retrace': None},
                        'mode': None}

    def update(self, **kwargs):
        ''' update Analyzer parameters '''
        for kw, setting in kwargs.items():
            if kw in self.params:
                self.params[kw] = setting
            else:
                print(f'Setting {kw} unsuported!')

    def hyst_compensation(self, jumps, hyst, offset=0):
        ''' Correct for hysteresis and offset of magnetic field '''
        tr_idc = self.select(jumps, 'trace', ret_mask=True)
        rt_idc = self.select(jumps, 'retrace', ret_mask=True)
        res = jumps.copy()
        res['jpos'][tr_idc] -= hyst / 2 - offset
        res['jpos'][rt_idc] += hyst / 2 - offset
        return jumps

    def select(self, arr, *selections, ret_mask=False, **conditions):
        ''' Returns list of indexes rows from structured_array for predefined
            selections or flexible conditions which can be applied by
            "col_name=lambda x: x < 0" '''
        # start with mask of all true
        mask = np.zeros(len(arr), dtype=bool)
        # loop over selection and add those to mask
        for sel in selections:
            match sel:
                case 'all':
                    mask = np.ones(len(arr), dtype=bool)
                case 'trace' | 'retrace':
                    mask |= arr['sweep_dirn'] == sel[:2]
                case 'up':
                    mask |= arr['jamp'] > 0
                case 'down':
                    mask |= arr['jamp'] < 0
                case _ if isinstance(sel, list):
                    # function in tuple work only on the tuple
                    col = sel[0]
                    func = sel[1]
                    if col not in arr.dtype.names:
                        raise ValueError(f"Column '{col}' not found in array.")
                    # Apply each condition
                    mask |= func(arr[col])
            # in case of tuples given, all condictions in tuple must be met
            if isinstance(sel, tuple):
                comb_mask = np.ones(len(arr), dtype=bool)
                for element in sel:
                    comb_mask &= self.select(arr, element, ret_mask=True)
                mask |= comb_mask
        # selection functions apply additional conditions on selections and therefore
        # only work if other selections are applied
        for col, func in conditions.items():
            if col not in arr.dtype.names:
                raise ValueError(f"Column '{col}' not found in array.")
            if not any(mask):
                raise ValueError("No selection specified")
            # Apply each condition
            mask &= func(arr[col])
        if ret_mask is True:
            return mask
        return arr[np.where(mask)[0]]

    def select_first_jump_per_sweep(self, arr):
        ''' Select the first jump per sweep '''
        # first translate jamp into direction only
        combo_view = np.stack((arr['step'],arr['sweep_dirn']), axis = 1)
        _, indices = np.unique(combo_view, axis=0, return_index=True)
        return arr[sorted(indices)]

    def get_jump_trajectory(self, jdir_sel:dict, mode:'str', ret_steps=False, fill_nans=False):
        ''' Return list of trace jumps and list of retrace. ret_steps=True
            returns also a list of the step values and fill_nans=True puts
            a nan value where no jump was detected '''
        sel = {
            'tr': self.select(self.jumps, ('trace', jdir_sel['trace'])),
            're': self.select(self.jumps, ('retrace', jdir_sel['retrace']))
        }
        steps = remove_duplicates(sel['tr']['step'])
        traj = {'tr': [], 're': []}
        for s in steps:
            for dirn, jmp in sel.items():
                # get all jump position indicees of sweep in direction
                idc = np.where(jmp['step'] == s)[0]
                # if a jump was detected
                if len(idc):
                    # if only the first jumps should be counted add those
                    if mode == 'first':
                        traj[dirn].append(list([jmp['jpos'][idc[0]]]))
                    elif mode == 'all':
                        traj[dirn].append(list(jmp['jpos'][idc]))
                    else:
                        raise NotImplementedError
                else:
                    # if no jump is detected either fill nans or empty list
                    if fill_nans:
                        traj[dirn].append([np.nan])
                    else:
                        traj[dirn].append([])
        if ret_steps:
            return traj, steps
        return traj

    def plot_transition_matrix(self, ax, subs=1, scale='lin', **kwargs):
        '''plot transition matrix wolfgang style'''
        jdir_sel = self.params['jdir_sel']
        mode = self.params['mode']
        # this transition matrix only works for one jump per sweep
        if mode not in ['first']:
            raise NotImplementedError
        # get jump trajectory
        traj = self.get_jump_trajectory(jdir_sel, mode, fill_nans=True)
        tr = np.array(traj['tr']).T[0]
        re = np.array(traj['re']).T[0]
        #tr -> rt
        hist_trrt, xedges, yedges = np.histogram2d( tr, re,
            bins=[self._sweep[::subs], self._sweep[::subs]]
        )
        #rt -> tr
        hist_rttr, xedges, yedges = np.histogram2d( tr[1:], re[:-1],
            bins=[self._sweep[::subs], self._sweep[::subs]]
        )
        # combine
        hist = np.add(hist_trrt, hist_rttr)

        # Plot the histogram as a colorplot
        if scale == 'lin':
            ax.pcolormesh(xedges, yedges, hist.T, cmap='viridis', **kwargs)
        elif scale == 'log':
            ax.pcolormesh(xedges, yedges, np.log(hist.T), cmap='viridis',  **kwargs)
        ax.set_xlabel(r'$\overrightarrow{B_\parallel (T)}$')
        ax.set_ylabel(r'$\overleftarrow{B_\parallel (T)}$')
        ax.set_box_aspect(1)


    def plot_histogram(self, dirns, plot='jpos'):
        ''' Plot histogram of jump positions for given directions '''
        # Get settings
        mode = self.params['mode']
        jdir_sel = self.params['jdir_sel']
        # create plot
        fig, ax = plt.subplots()
        # Create BinEdges for Histogram
        if plot == 'jpos':
            bin_edges, _ = create_bin_edges(self._sweep)
            ax.set_xlabel('Bp (T)')
        elif plot == 'jamp':
            jamps = self.jumps['jamp']
            bin_edges = np.linspace(min(jamps), max(jamps), num=100)
            ax.set_xlabel('Jump slope')
        else:
            raise NotImplementedError
        # loop over directions and plot
        for dirn in dirns:
            sel = self.select(self.jumps, (dirn, jdir_sel[dirn]))
            if mode == 'first':
                sel = self.select_first_jump_per_sweep(sel)
            selection = sel[plot]
            ax.hist(selection, bins=bin_edges, alpha=0.5, label=dirn)
        ax.set_ylabel('Count')
        ax.legend()
        fig.tight_layout()

    def plot_hist_jpos_for_each_jdir_seperate(self, dirn):
        ''' Plot histogram of both jump directions seperately for given
            direction '''
        _, ax = plt.subplots()
        mode = self.params['mode']
        bin_edges, _ = create_bin_edges(self._sweep)
        for jdir in ['up', 'down']:
            sel = self.select(self.jumps, (dirn, jdir))
            if mode == 'first':
                sel = self.select_first_jump_per_sweep(sel)
            jpos = sel['jpos']
            ax.hist(jpos, bins=bin_edges, alpha=0.5, label=jdir)
        ax.legend()
        plt.tight_layout()

    def plot_hist_jumps_per_sweep(self, dirn, jdir=None, **kwargs):
        ''' Plot a histogram of the number of detected jumps
            (in direction up|down|all) per sweep for a given sweep direction.
            dirn=trace|retrace, jdir=up|down|all '''
        # get jump direction from params
        if jdir is None:
            jdir = self.params['jdir_sel'][dirn]
        # get all steps
        steps = remove_duplicates(self.jumps['step'])
        # select seep direction and jump direction
        if jdir == 'all':
            selection = self.select(self.jumps, (dirn, 'up'), (dirn, 'down'))
        elif jdir in ['up', 'down']:
            selection = self.select(self.jumps, (dirn, jdir))
        else:
            raise NotImplementedError
        # count amount of jumps in direction per step
        nb_jumps = np.empty(len(steps))
        for i, s in enumerate(steps):
            nb_jumps[i] = len(self.select(selection, 'all', step=lambda x: x==s))
        _, ax = plt.subplots()
        bin_edges = np.arange(-0.5, max(nb_jumps) + 1, step=1)
        bin_mids = range(int(max(nb_jumps)))
        ax.hist(nb_jumps, bins=bin_edges, density=True, **kwargs)
        ax.set_xticks(bin_mids)
        ax.set_xlabel(f'Amount of "{jdir}" jumps for "{dirn}"')
        ax.set_ylabel('Probability')
        plt.tight_layout()

    def plot_trajectory(self, mode=None, conv_step_val=True, **kwargs):
        ''' Plot trajectory of detected jumps over sweeps '''
        jdir_sel = self.params['jdir_sel']
        if mode is None:
            mode = self.params['mode']
        traj, step_idc = self.get_jump_trajectory(jdir_sel, mode, ret_steps=True)
        _, ax = plt.subplots()
        if mode == 'first':
            total_sweeps = len(traj['tr'])
            x = range(total_sweeps)
            x2 = [val + 0.5 for val in x]
            ax.plot(x, traj['tr'], **kwargs)
            ax.plot(x2, traj['re'])
        elif mode == 'all':
            for dirn, jmps in traj.items():
                x = []
                y = []
                for i, jmps_in_sweep in enumerate(jmps):
                    for jmp in jmps_in_sweep:
                        if conv_step_val:
                            x.append(self._step[step_idc[i]])
                        else:
                            x.append(i)
                        y.append(jmp)
                if 're' in dirn:
                    offset = (x[1] - x[0]) / 2
                    x = [element + offset for element in x]
                ax.scatter(x, y, label=dirn, s=1)
        if conv_step_val:
            ax.set_xlabel('Step value (retrace shifted half step right)')
        else:
            ax.set_xlabel('Step index (retrace shifted half step right)')

        ax.set_ylabel('jump position (Bp)')
        plt.tight_layout()

    def plot_total_jump_count_per_step(self, spath=False, **kwargs):
        ''' For every step count the total amount of detected jumps and plot
            over step '''
        # get step values
        x = self.jumps['step']
        y = np.empty(len(x))
        # for every step count amount of jumps
        for i, stp in enumerate(x):
            y[i] = len(self.select(self.jumps, 'all', step=lambda x: x==stp))
        _, ax = plt.subplots()
        ax.plot(x, y, marker='X')
        ax.set_xlabel('Bp (T)')
        ax.set_ylabel('Number of jumps in ? s')
        # add customizations per kwargs
        for kw, val in kwargs.items():
            match kw:
                case 'time':
                    ax.set_ylabel(f'Number of jumps in {val}s')
                case 'title':
                    ax.set_title(val)
        # finalize
        plt.tight_layout()
        if spath:
            plt.savefig(spath)

    def plot_histogram_jumps_per_step(self, dirns=None, **kwargs):
        ''' Plot histogram of the total amount of jumps per trace '''
        mode = 'all'
        jdir_sel = self.params['jdir_sel']
        # get jump trajectory
        traj = self.get_jump_trajectory(jdir_sel, mode)
        # calculate how many jumps per step
        nb_jumps = np.zeros(len(traj[list(traj.keys())[0]]))
        for d in dirns:
            for i, t in enumerate(traj[d[:2]]):
                nb_jumps[i] += len(t)
        #
        _, ax = plt.subplots()
        bin_edges = np.arange(min(nb_jumps)-0.5, max(nb_jumps)+1.5, step=1)
        ax.hist(nb_jumps, bin_edges)
        ax.set_xlabel('jumps per (re)trace')
        ax.set_ylabel('counts')
        plt.tight_layout()

    def plot_nb_jumps_per_step(self, dirns=None, convert_step_val=True, **kwargs):
        ''' Plot the total amount of jumps per step in direction '''
        mode = 'all'
        jdir_sel = self.params['jdir_sel']
        # get jump trajectory
        traj, step_idc = self.get_jump_trajectory(jdir_sel, mode, ret_steps=True)
        # calculate how many jumps per step
        nb_jumps = np.zeros(len(traj[list(traj.keys())[0]]))
        for d in dirns:
            for i, t in enumerate(traj[d[:2]]):
                nb_jumps[i] += len(t)
        #
        _, ax = plt.subplots()
        if convert_step_val:
            ax.plot(self._step[step_idc], nb_jumps)
        else:
            ax.plot(step_idc, nb_jumps)
        plt.tight_layout()


"""

    def plot_hist_no_jumps_p_step(self, ax, dirn=None, jdirns=None, **kwargs):
        ''' Plot histogram of the total amount of jumps found in the trace for
            each step '''
        if self._params['method'][1] != 'all':
            print('Are you sure you dont want to detect all jumps???')
        if self._params['select'] != 'all':
            print('Are you sure you dont want to select all jumps???')
        buffer = self._params['jdirns'][dirn]
        jump_no = np.zeros(len(self._step))
        for jdirn in jdirns:
            self._params['jdirns'][dirn] = jdirn
            jpos, _ = self.detect_jumps(dirn, indices=None)
            for i, val in enumerate(jpos):
                jump_no[i] += len(val) - np.count_nonzero(np.isnan(val))
        self._params['jdirns'][dirn] = buffer
        ax.bar(self._step, jump_no, width=np.mean(np.diff(self._step)))
        #ax.hist(self._step, jump_no, **kwargs)
        return ax

    def dwell_time(self, ax, step_no, dirn=None, jdirns=None, **kwargs):
        ''' Plot histogram of dwell time (distance between jumps) for a single
            sweep at step_no '''
        # change necessary settings
        jdirns_buffer = self._params['jdirns'][dirn]
        detect_buffer = self._params['method'][1]
        select_buffer = self._params['select']
        self._params['method'][1] = 'all'
        self._params['select'] = 'all'
        # get all jumps
        jp = {}
        for jdirn in jdirns:
            self._params['jdirns'][dirn] = jdirn
            jpos, _ = self.detect_jumps(dirn, indices=None)
            jp[jdirn] = jpos
        jumps = [None] * len(self._step)
        for i, _ in enumerate(jumps):
            jumps[i] = []
            for jdirn in jdirns:
                jumps[i].extend(jp[jdirn][i])
            jumps[i] = sorted(jumps[i])
        #change cettings back
        self._params['jdirns'][dirn] = jdirns_buffer
        self._params['method'][1] = detect_buffer
        self._params['select'] = select_buffer
        diff = np.diff(jpos[step_no])
        ax.hist(diff, **kwargs)
        return ax


    def plot_scatter(self, ax, dirns=None, indices:list=None, **kwargs):
        ''' Scatterplot of jump position and amplitude '''
        if dirns is None:
            dirns = sorted(list(self._data.keys()), reverse=True)
        for dirn in dirns:
            jpos, jamp = self.detect_jumps(dirn, indices)
            jpos = self.select_jumps(jpos, self._params['select'])
            jamp = self.select_jumps(jamp, self._params['select'])
            ax.scatter(jpos, jamp, label=dirn, **kwargs)
        ax.legend()
        return ax

    def plot_scatter_colormap(self, ax, dirn, indices:list=None, subs=1,
                              scale='lin', **kwargs):
        jpos, jamp = self.detect_jumps(dirn, indices)
        jpos = self.select_jumps(jpos, self._params['select'])
        jamp = self.select_jumps(jamp, self._params['select'])
        # Create 2D histogram
        hist, xedges, yedges = np.histogram2d(
            jpos, jamp, bins=[self._sweep[::subs], np.linspace(min(jamp), max(jamp), len(self._sweep[::subs]))])
        # Plot the histogram as a colorplot
        if scale == 'lin':
            ax.pcolormesh(xedges, yedges, hist.T, cmap='viridis', **kwargs)
        elif scale == 'log':
            ax.pcolormesh(xedges, yedges, np.log(hist.T), cmap='viridis',  **kwargs)
        return ax

    def plot_jpos_trajectory_seperate(self, ax, hyst, **kwargs):
        dirns = list(self._data.keys())
        for dirn in dirns:
            jpos, _ = self.detect_jumps(dirn)
            jpos = self.select_jumps(jpos, self._params['select'])
            t = list(range(len(jpos)))
            if dirn == 'trace':
                t = [val * 2 - 1 for val in t]
                jpos = np.subtract(jpos, hyst / 2)
            elif dirn == 'retrace':
                t = [val * 2 for val in t]
                jpos = np.add(jpos, hyst / 2)
            ax.plot(t, jpos, **kwargs)
        return ax

"""