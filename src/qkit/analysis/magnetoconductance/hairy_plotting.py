import sys
import matplotlib.pyplot as plt
import numpy as np
from scipy.ndimage import gaussian_filter1d
#from mpl_toolkits.axes_grid1.axes_divider import make_axes_locatable
from mpl_histcolorbar import HistColorbar, histcolorbar

# plt.style.use('./plt_styles/default.mplstyle')

def calc_diff(tr, rt):
    diff = np.empty(tr.shape)
    for i in range(tr.shape[0]):
        diff[i] = tr[i, :] - rt[i, :]
    return diff

import numpy as np

def find_range_by_percent_included(values, percent):
    # Sort the values
    sorted_values = np.sort(values)
    
    # Calculate the number of values to exclude from each side
    num_values_to_exclude = int(len(sorted_values) * (100 - percent) / 200)
    
    # Find the range
    lower_bound = sorted_values[num_values_to_exclude]
    upper_bound = sorted_values[-num_values_to_exclude - 1]
    
    return lower_bound, upper_bound

class PolarPlotter():
    def __init__(self, step, sweep, data:np.ndarray, sample_rate, **kwargs):
        self._sweep = sweep
        self._step = step
        self._data_raw = data
        self.fs = sample_rate

        self._data = self._data_raw

        self.subsampled = False

    def apply_filter(self, sigma):
        ''' Apply gaussian filter to all sweeps '''
        self._data = gaussian_filter1d(self._data_raw, sigma, axis=1)
        self.subsampled = False

    def apply_subsampling(self, subs_steps, subs_sweep):
        ''' Subsample steps and sweep data '''
        if self.subsampled is False:
            self._step = self._step[::subs_steps]
            self._sweep = self._sweep[::subs_sweep]
            self._data = self._data[::subs_steps, ::subs_sweep]
            self.subsampled = True
        else:
            print('Data is already subsampled. Apply filter first, or load again')

    def plot_values_histogram(self):
        # Create histogram of color values
        fig_hist, ax_hist = plt.subplots()
        color_values = self._data.flatten()
        ax_hist.hist(color_values, bins=50)
        ax_hist.set_title('Histogram of Color Values')
        ax_hist.set_xlabel('Color Value')
        ax_hist.set_ylabel('Frequency')

    def test_plot(self, fc):
        i = 10
        fig, (ax1, ax2) = plt.subplots(2, sharex=True)
        sweep = self._sweep
        trace = self._data['trace'][i, :]
        retrace = self._data['retrace'][i, :]
        diff = self._data['trace'][i, :] - self._data['retrace'][i, :]
        #yf = gaussian_filter1d(self._data['trace'], fc, axis=1)[i, :]
        yf = gaussian_filter1d(trace, fc)
        rf = gaussian_filter1d(retrace, fc)
        df = gaussian_filter1d(diff, fc)
        ax1.plot(sweep, trace)
        ax1.plot(sweep, retrace)
        ax1.plot(sweep, yf)
        ax1.plot(sweep, rf)
        ax2.plot(sweep, diff)
        ax2.plot(sweep, df)
        ax2.plot(sweep[::10], (yf - rf)[::10], linestyle='--')
        #ax.plot(sweep[::10], yf[::10])

    def polar_plot(self, crange=100, **kwargs):
        #split in positive and negative part of sweep
        zidx = np.abs(self._sweep).argmin()
        # positive part of sweep
        swp_pos = self._sweep[zidx:]
        agl_pos = self._step * np.pi / 180
        val_pos = self._data[:, zidx:].T
        # negative part of sweep
        agl_neg = agl_pos + np.pi
        swp_neg = np.abs(self._sweep[:zidx])
        val_neg = -1 * self._data[:, :zidx].T

        vmin, vmax = find_range_by_percent_included(self._data.flatten(), crange)
        print(vmin, vmax)
        #plot posive and negative seperate
        fig, ax = plt.subplots(subplot_kw={'projection': 'polar'})
        ax.pcolormesh(agl_pos, swp_pos, val_pos, vmin=vmin, vmax=vmax, shading='nearest', **kwargs)
        ax.pcolormesh(agl_neg, swp_neg, val_neg, vmin=vmin, vmax=vmax, shading='nearest', **kwargs)






class HarryPlotter:
    ''' Plot the results from JumpDetective. Don't think about sweeps anymore,
        but the extracted data after jump detection '''
    def __init__(self, **kwargs):
        # Check here for all keywords which are not supposed to be given to the
        # plot function!
        if 'style' in kwargs.keys():
            self.load_stylesheet(kwargs['style'])
            kwargs.pop('style')
        # All other keywords will be saved and used by the plot fun
        self.settings = kwargs
    def add_plot(self, **kwargs):
        ''' overwrite by children '''
        pass

    def load_stylesheet(self, path):
        plt.style.use(path)

    def save(self, path, dpi=100):
        plt.savefig(path, dpi=dpi)

    def show(self):
        plt.show()
    
    def add_legend(self):
        self.ax.legend()


class ScatterPlotter(HarryPlotter):
    ''' Scatterplots '''
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.fig, self.ax = plt.subplots()

    def add_plot(self, x, y, **kwargs):
        settings = self.settings.copy()
        settings.update(kwargs)
        print(settings)
        self.ax.scatter(x, y, **settings)


class HistogramPlotter(HarryPlotter):
    ''' Plot Histrograms '''
    def __init__(self, sweep_values, resolution=None, bins=None,  **kwargs):
        super().__init__(**kwargs)
        self.resolution = resolution
        self.bins = bins
        self.fig, self.ax = plt.subplots()
        self.sweep_values = sweep_values
        self.x = None

    def _get_bin_edges(self):
        ''' Return number of bins. If resoltion is specified, calculate bins from
            limits and resolution. Otherwise, use the bins. '''
            # I DONT KNOW EXACTLY WHY; BUT I HAD TO REMOVE THE FIRST AND THE LAST
            # BAR TO NOT HAVE ARTIFACTS AT THE ENDPOINTS. IT SEEMS THAT OTHERWISE I
            # COUNT VALUES DOUBLE FOR THESE BARS.
        # Find the range of the data
        min = np.nanmin(self.x)
        max = np.nanmax(self.x)
        if self.resolution:
            if self.resolution == 'max':
                # If resolution = 'max' create one bin for each sweep value
                # which is between min and max
                bins = [val for val in self.sweep_values if min <= val <=max]
            elif isinstance(self.resolution, (int, float)):
                return int((max - min) / self.resolution)
        elif self.bins:
            if isinstance(self.bins, int):
                return np.linspace(min, max, num=self.bins)
            elif isinstance(self.bins, list):
                return self.bins
        else:
            print('Need either resolution or bins keyword')
            sys.exit()
        # To get the bin_edges we need add a bin and shift everything
        # by half a bin to the side (otherwise, there will be double
        # counting at the edges
        diff = np.mean(np.diff(bins))
        edges = np.append(bins, bins[-1] + diff) - diff / 2
        return edges


    def add_plot(self, x, **kwargs):
        settings = self.settings.copy()
        settings.update(kwargs)
        # save 1D data to plot as histogram, but remove NaN values
        self.x = x
        # get the bin edges for resolution=max and number of bins otherwise
        edges = self._get_bin_edges()
        # create histogram data: counts for all values betw. edges 
        counts, edges = np.histogram(x, bins=edges)
        # find bins (middle of the range over which histogram counted)
        bins = edges[:-1] + np.mean(np.diff(edges)) / 2
        self.ax.bar(bins, counts, width=np.diff(edges), **settings)


