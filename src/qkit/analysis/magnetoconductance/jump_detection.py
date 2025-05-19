from typing import Literal
import numpy as np
import matplotlib.pyplot as plt
from scipy.ndimage import gaussian_filter1d, uniform_filter1d
from scipy.signal import find_peaks

_JDIRN = Literal["up", "down"]
_DETECT = Literal['highest', 'all']
_FILTER_FUNC = Literal['gauss', 'uni']

def slice_arrays_by_x_values(x, y, xlim:tuple=(None, None)):
    ''' Return a sublist of y, cut off at idicees where x < min and x > max '''
    if len(x) == len(y) and None not in xlim:
        xmin = xlim[0]
        xmax = xlim[1]
        ids = sorted((np.abs(x - xmin).argmin(), np.abs(x - xmax).argmin()))
        return x[ids[0]: ids[1]], y[ids[0]: ids[1]]
    return x, y

def filter_and_derive(y, filter_func=None, filter_val=None):
    ''' Filter data and calculate derivative '''
    match filter_func:
        case None:
            yf = y
            d = np.diff(yf, n=1, append=2*yf[-1]-yf[-2])
        case 'uni':
            yf = uniform_filter1d(y, filter_val)
            d = np.diff(yf, n=1, append=2*yf[-1]-yf[-2])
        case 'gauss':
            yf = gaussian_filter1d(y, order=0, sigma=filter_val)
            d = gaussian_filter1d(y, order=1, sigma=filter_val)
        case _:
            raise NotImplementedError(f"Filter {filter_func} is not defined!")
    return yf, d

def detect_jump_by_slope(
    x, y, jdirn:_JDIRN, detect:_DETECT, xlim:tuple=(None, None),
    slope_min:(int, float)=None, filter_func=None, filter_val=None):
    ''' Detect jump (x value and "amplitude") in direction jdirn by looking for
        the heighest slope in range xlim[0] < x xlim[1] with amplitude above
        slope_min '''
    # detect 'all' should only be chosen, if slope_min is given
    if detect == 'all' and slope_min in [None, 0]:
        raise AssertionError("Use detect='all' only with min_slope given")
    # Filter and derive
    _, d = filter_and_derive(y, filter_func, filter_val)
    # Slice array to only look in a specific range
    x_subset, d_subset = slice_arrays_by_x_values(x, d, xlim)
# If downwards jumps is looked for, change sign of derivative
    sign = {'down': -1, 'up': 1}
    d_subset *= sign[jdirn]
    # Peakfinder
    peak_indices, _ = find_peaks(d_subset, height=slope_min)
    if len(peak_indices) > 0:
        if detect == 'highest':
            peak_idx = peak_indices[np.argmax(d_subset[peak_indices])]
            return [x_subset[peak_idx]], [d_subset[peak_idx] * sign[jdirn]]
        elif detect == 'all':
            return x_subset[peak_indices], d_subset[peak_indices] * sign[jdirn]
    return [np.nan], [np.nan]

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


class DataTreatment():
    ''' Class handles filtering and subsampling of a single measurement
        variable (data) together with its x (step), and y(sweep) values '''
    def __init__(self, step:np.array, sweep:np.array, data:np.ndarray):
        self._step = step
        self._sweep = sweep
        self._data_raw = data
        self.data_filtered = None

    def test_filter(self, sweep_no, filter_func, filter_val, subsampling=None):
        ''' Test filtering and subsampling on sweep number 'sweep_no' '''
        x = self._sweep
        y = self._data_raw[sweep_no, :]
        yf = self.filter_single_trace(y, filter_func, filter_val)
        fig, ax = plt.subplots()
        ax.plot(x, y)
        ax.plot(x, yf)
        if subsampling:
            ax.plot(x[::subsampling], yf[::subsampling], linestyle='', marker='.')

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
        ''' Get step, sweep and data subsampled '''
        step = self._step
        sweep = self._sweep[::subsampling]
        if self.data_filtered is not None:
            data = self.data_filtered[:, ::subsampling]
        else:
            data = self._data_raw[:, ::subsampling]
        return step, sweep, data

    def get_measurement(self):
        ''' Get step, sweep and data '''
        return self.get_subsampled(subsampling=1)

class JumpDetective:
    ''' The module takes an object of the HDFData class to extract measurement data
    from a .h/hdf5 file and detect jumps in the sweeps. The HDFData object
    can also be used to save the detected jumps in the .h/hdf5 file analysis0 group.'''
    def __init__(self, step, sweep, data, **params):
        self._step = step
        self._sweep = sweep
        self._data = data

        self._pos = None
        self._amp = None

        self._params = {'method': 'slope',
                        'dirn': None,
                        'filter_func': None,
                        'filter_val': None,
                        'detect': 'highest',  # 'highest, 'all'
                        'select': 'first',    # 'first', 'last', 'all'
                        'jdirns': {'trace': None, 'retrace': None},
                        'xlim': {'trace': (None, None),
                                 'retrace': (None, None)},
                        'slope_min': {'trace': 0, 'retrace': 0}}
        self.update_params(**params)

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

    def detect_jump(self, i, dirn):
        ''' extract the jump and height (amplitude of derivative) for sweep i.
            Return jpos, jamp and a list containing the filtered derivative,
            where all values out of athres have been put to zero. This could be
            changed, if needed. '''
        # update and get parameters
        ffunc = self._params['filter_func']
        fval = self._params['filter_val']
        jdirn = self._params['jdirns'][dirn]
        xlim = self._params['xlim'][dirn]
        smin = self._params['slope_min'][dirn]
        # choose right function for method
        if self._params['method'] == 'slope':
            jpos, jamp = detect_jump_by_slope(self._sweep,
                                              self._data[dirn][i, :],
                                              jdirn,
                                              self._params['detect'],
                                              xlim, smin, ffunc, fval)
        else:
            print('Jump detection method not yet implemented')
            raise NotImplementedError
        return jpos, jamp

    def detect_jumps(self, dirn, indices:list=None):
        ''' Detect jumps in direction dirn for all sweeps with index inindices
        '''
        if indices is None:
            indices = range(len(self._step))
        jpos = []
        jamp = []
        for i in indices:
            jp, ja = self.detect_jump(i, dirn)
            jpos.append(jp)
            jamp.append(ja)
        return jpos, jamp

    def select_jumps(self, x, select):
        ''' Either just use the first or last sweep, or if 'all' count every
            jump as a seperate measurement '''
        if select == 'first':
            res = np.empty(len(x))
            for i, val in enumerate(x):
                res[i] = val[0]
        elif select == 'last':
            res = np.empty(len(x))
            for i, val in enumerate(x):
                res[i] = val[-1]
        elif select == 'all':
            # flatten x array
            res = np.array([item for row in x for item in row])
        return res

    def get_jump_trajectory(self, hyst):
        ''' Return the jump positions in chronological order '''
        dirns = list(self._data.keys())
        # check that trace and retrace is available
        if all([dirn in dirns for dirn in ['trace', 'retrace']]):
            # check if only one jump per trace/retace is detected
            p = self._params
            if p['detect'] == 'highest' or p['select'] in ['first', 'last']:
                s = self._params['select']
                jpos_tr, _ = self.detect_jumps('trace')
                jpos_tr = self.select_jumps(jpos_tr, self._params['select'])
                jpos_rt, _ = self.detect_jumps('retrace')
                jpos_rt = self.select_jumps(jpos_rt, self._params['select'])
                if len(jpos_tr) == len(jpos_rt):
                    jpos_traj = np.empty(len(jpos_tr) + len(jpos_rt))
                    for i, _ in enumerate(self._step):
                        #trace
                        jpos_traj[2*i] = jpos_tr[i] - hyst / 2
                        #retrace
                        jpos_traj[2*i+1] = jpos_rt[i] + hyst / 2
            else:
                raise AssertionError('Not yet implemented')
        return jpos_traj

    def plot_jump(self, ax, i, dirn, **kwargs):
        ''' Plot jump i in direction dirn after filtering '''
        ffunc = self._params['filter_func']
        fval = self._params['filter_val']
        x = self._sweep
        y = self._data[dirn][i, :]
        yf, _ = filter_and_derive(y, ffunc, fval)
        ax.plot(x, y, **kwargs)
        ax.plot(x, yf, **kwargs)
        return ax

    def plot_sweep(self, ax, i):
        ''' Plot sweep i (all available traces) '''
        for dirn in self._data:
            ax.plot(self._sweep, self._data[dirn][i, :], label=dirn)
        ax.legend()
        return ax

    def plot_derivative(self, ax, i, dirn, plot_detected_jump=False, **kwargs):
        ''' Plot derivative and [jpos, jamp] '''
        ffunc = self._params['filter_func']
        fval = self._params['filter_val']
        x = self._sweep
        y = self._data[dirn][i, :]
        _, d = filter_and_derive(y, ffunc, fval)
        ax.plot(x, d, **kwargs)
        if plot_detected_jump:
            jpos, jamp = self.detect_jump(i, dirn)
            ax.plot(jpos, jamp, linestyle='', marker='X', color='red')
        return ax

    def plot_jpos_histogram(self, ax, dirns=None, indices:list=None, **kwargs):
        ''' Plot histogram of jump positions '''
        if dirns is None:
            dirns = list(self._data.keys())
        for dirn in dirns:
            jpos, _ = self.detect_jumps(dirn, indices)
            jpos = self.select_jumps(jpos, self._params['select'])
            bin_edges, _ = create_bin_edges(self._sweep)
            # if label is not given, use dirn as label
            if 'label' not in kwargs:
                kwargs['label'] = dirn
            ax.hist(jpos, bins = bin_edges, **kwargs)
        ax.legend()
        return ax

    def plot_hist_both_jdirns_per_trace(self, ax, dirn, **kwargs):
        ''' Plot histogram with jump positions for up and down jumps for a
            single sweep direction '''
        # save jdirn to restore afterwards
        buffer = self._params['jdirns'][dirn]
        # add missing jump direction, so that the missing one is plottet last
        jdirns = list(_JDIRN.__args__)
        jdirns.remove(buffer)
        jdirns = [buffer, jdirns[0]]
        # loop over both jump directions
        for jdirn in jdirns:
            self._params['jdirns'][dirn] = jdirn
            ax = self.plot_jpos_histogram(ax, [dirn], label=jdirn, **kwargs)
        # restore jump direction
        self._params['jdirns'][dirn] = buffer
        ax.legend()

    def plot_scatter(self, ax, dirns=None, indices:list=None,
                     **kwargs):
        ''' Scatterplot of jump position and amplitude '''
        if dirns is None:
            dirns = list(self._data.keys())
        for dirn in dirns:
            jpos, jamp = self.detect_jumps(dirn, indices)
            jpos = self.select_jumps(jpos, self._params['select'])
            jamp = self.select_jumps(jamp, self._params['select'])
            ax.scatter(jpos, jamp, label=dirn, **kwargs)
        ax.legend()
        return ax

    def plot_jpos_trajectory(self, ax, hyst, **kwargs):
        jpos_traj = self.get_jump_trajectory(hyst)
        ax.plot(range(len(jpos_traj)), jpos_traj, **kwargs)
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

    def plot_transition_matrix(self, ax, hyst, **kwargs):
        traj = self.get_jump_trajectory(hyst)
        i = traj[:-1]
        j = traj[1:]
        ax.scatter(i, j, color='blue', **kwargs)
        return ax

    def plot_conductance_hist_map(self, ax, bins=100):
        # use some standard values depending on given data
        dirns = list(self._data.keys())
        # Find max and min conductance values
        min = np.min([np.min(self._data[dirn]) for dirn in dirns])
        max = np.max([np.max(self._data[dirn]) for dirn in dirns])
        # Create bin_num bin_edges for histogram between min and max
        bin_edges = np.linspace(min, max, num=bins+1, endpoint=True)
        # Find the middle value of each bin
        bin_mids = np.empty(bins)
        for i in range(bins):
            bin_mids[i] = (bin_edges[i] + bin_edges[i+1]) / 2
        # Create the data array holding all the histogram data
        C = np.empty((bins, len(self._step)))
        # Calculate all histograms
        for idx, _ in enumerate(self._step):
            if 'trace' in dirns:
                yt = self._data['trace'][idx, :]
            else:
                yt = []
            if 'retrace' in dirns:
                yr = self._data['trace'][idx, :]
            else:
                yr = []
            counts, _ = np.histogram(np.concatenate([yt, yr]), bins=bin_edges)
            C[:, idx] = counts
        ax.pcolormesh(self._step, bin_mids, C)
        return ax