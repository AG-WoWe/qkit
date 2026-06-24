import numpy as np
import matplotlib.pyplot as plt
from qkit.drivers.adwinlib.io_handler import calc_r, calc_theta
from math import sqrt, atan2
from scipy.fft import rfft, rfftfreq, fftshift
from scipy.signal import windows, periodogram

def plot(x, y, **kwargs):
    fig, ax = plt.subplots(figsize=(6,4))
    ax.plot(x, y)
    for k, val in kwargs.items():
        match k:
            case 'xscale':
                ax.set_xscale(val)
            case 'yscale':
                ax.set_yscale(val)
            case 'xlim':
                ax.set_xlim(val)
            case 'ylim':
                ax.set_ylim(val)
            case 'type':
                if val == 'fft':
                    ax.set_xlabel('Frequency (Hz)')
                    ax.set_ylabel(r'Amplitude (I/$\sqrt{Hz}$)')
    fig.tight_layout()

def my_rfft(data, sample_rate, window=None, window_params=[]):
    N = len(data)
    # fist catch the case where no window is given -> uniform window
    if window in [None, 'uniform']:
        win = np.ones(N)
    # handle multi paramater windows
    elif window == "gaussian":
        win = getattr(windows, window)(N, window_params[0] * N)
    # else assume no extra parameters needed
    else:
        win = getattr(windows, window)(N)
    # apply window
    data = data * win
    # calculate correction factor
    win_corr_fac = 1 / np.mean(win)
    # calculate ftt for real function with correction factor
    yf = 2/N * np.abs(rfft(data)) * win_corr_fac
    # get fft frequencies
    xf = rfftfreq(N, 1 / sample_rate)
    return(xf, yf)

def measure_fft_at_current_wp(adwin, sample_rate, time, lockin_settings):
    bias = adwin.read_outputs()['vd']
    amp = lockin_settings['amp']
    freq = lockin_settings['freq']
    tao = lockin_settings['tao']
    phase = lockin_settings['phase']
    maf = lockin_settings['maf']
    if amp > 0:
        adwin.init_measurement(
            sample_rate, bias, ['inph', 'quad', 'raw'], amplitude=amp,
            frequency=freq, tao=tao, phase=phase, maf=maf
        )
    else:
        adwin.init_measurement(
            sample_rate, bias, ['raw'], amplitude=amp, frequency=freq, tao=tao,
            phase=phase, maf=maf
        )
    data = adwin.measure(duration = time)
    x, y = my_rfft(data['raw'], sample_rate, window='blackman')
    plot(x, y, xscale='log', yscale='log', type='fft')
    adwin.stop_measurement()
