import numpy as np
import matplotlib.pyplot as plt
from scipy.signal.windows import dpss
from scipy.signal import find_peaks, iirnotch, filtfilt
from scipy.fft import rfft
from scipy.ndimage import gaussian_filter1d
from scipy.signal import find_peaks

def gaussian_filter(x, sigma):
    return gaussian_filter1d(x, order=0, sigma=sigma)

def notch_cascade(y, fs, freqs, Q):
    """
    Zero-phase notch filtering at each frequency using filtfilt.
    freq must be same unit as fs.
    For each frequency specify a bw in same unit as freqs
    """
    for idx, f0 in enumerate(freqs):
        if f0 <= 0 or f0 >= fs/2:
            continue
        b, a = iirnotch(f0, Q, fs)
        y = filtfilt(b, a, y)
    return y

def multitaper_psd(
    x: np.ndarray,
    fs: float,
    NW: float = 2.5,
    Kmax: int = None,
    nfft: int = None,
    detrend: str = "constant",  # "constant" (remove mean) or None
    sides: str = "onesided",    # "onesided" or "twosided" (real signals: use "onesided")
    weight: str = "eigen"):      # "equal" or "eigen"
    """
    Multitaper (Thomson) power spectral density estimate.

    Parameters
    ----------
    x : array_like
        1D time-domain signal.
    fs : float
        Sampling frequency [Hz].
    NW : float, default 2.5
        Time-halfbandwidth product. Typical values: 2–4.
    Kmax : int or None, default None
        Number of tapers. If None, uses K = floor(2*NW) - 1 (>=1).
    nfft : int or None, default None
        FFT length. If None, uses next power of two >= len(x).
    detrend : {"constant", None}, default "constant"
        Remove the mean before analysis if "constant".
    sides : {"onesided", "twosided"}, default "onesided"
        One-sided PSD (for real signals) or two-sided.
    weight : {"equal","eigen"}, default "eigen"
        How to combine taper spectra:
        - "equal": simple average across tapers
        - "eigen": weights proportional to the DPSS eigenvalues (slightly lower variance)

    Returns
    -------
    f : ndarray
        Frequency vector [Hz].
    Pxx : ndarray
        PSD estimate [power/Hz].
    Pk : ndarray or None
        Eigenspectra with shape (K, len(f)) if requested, else None.

    Notes
    -----
    - This uses **non-iterative** weighting. Adaptive (frequency-by-frequency)
      weighting (Thomson) can be added, but the eigenvalue-weighted average
      already captures most of the multitaper variance reduction without
      smearing narrow lines.
    - Scaling matches SciPy's 'density' convention (power/Hz).
    """
    x = np.asarray(x, dtype=float)
    N = x.size
    if detrend == "constant":
        x = x - np.mean(x)

    if nfft is None:
        nfft = 1 << int(np.ceil(np.log2(N)))

    if Kmax is None:
        Kmax = max(1, int(np.floor(2*NW) - 1))

    # DPSS tapers and eigenvalues
    tapers, eigvals = dpss(N, NW, Kmax, return_ratios=True)  # tapers shape (K, N)

    # Apply tapers, FFT (use rfft for real signals -> one-sided)
    Xk = rfft(tapers * x, n=nfft, axis=-1)  # shape (K, nfft/2+1)

    # Two-sided frequency grid for rfft is implicit; we'll build one-sided f
    freqs = np.fft.rfftfreq(nfft, d=1/fs)

    # Periodogram scaling: 'density' like scipy.signal.periodogram
    # For a window w, density scaling is: (1/(fs * sum(w**2))) * |FFT|^2
    # DPSS are energy-normalized, but we compute the exact sum(w^2) for each taper.
    w2 = np.sum(tapers**2, axis=1)  # shape (K,)
    Sk = (np.abs(Xk)**2) / (fs * w2[:, None])  # shape (K, F)

    # If the user wants a two-sided PSD, reconstruct it from rfft output
    if sides == "twosided":
        # Mirror positive freqs (exclude DC and Nyquist) and scale properly.
        # For PSD density, onesided = twosided * 2 on bins (except DC/Nyq).
        # So to get twosided from rfft result, divide the interior bins by 2.
        # Build a two-sided frequency vector and spectra.
        # However, most users of real signals want onesided. Keep simple:
        raise NotImplementedError("twosided output not implemented in this concise version.")

    # Combine across tapers
    if weight not in ("equal", "eigen"):
        raise ValueError("weight must be 'equal' or 'eigen'.")

    if weight == "equal":
        w = np.ones_like(eigvals)
    else:  # "eigen": eigenvalue-proportional weights
        w = eigvals.copy()
        # Avoid degenerate cases
        w = np.maximum(w, 1e-12)

    w = w / np.sum(w)
    Pxx = np.sum((w[:, None]) * Sk, axis=0)   # weighted average across tapers

    # One-sided density convention: rfft already produced one-sided spectrum.
    # BUT SciPy doubles interior bins for onesided density when using real FFT;
    # we must do the same (because we have not doubled yet).
    # Double all bins except DC and (if exists) Nyquist:
    if nfft % 2 == 0:
        # even nfft: Nyquist exists at -fs/2 and +fs/2 -> rfft has an endpoint
        Pxx[1:-1] *= 2.0
        Sk[:, 1:-1] *= 2.0
    else:
        # odd nfft: no Nyquist bin in rfft
        Pxx[1:] *= 2.0
        Sk[:, 1:] *= 2.0

    return freqs, Pxx

def remove_sharp_noise_peaks(
    time, data, fs, select:tuple, fft_res=2, fmin=1, Q=100, init_prom=1, promhist=True, plot=True):
    ''' Remove sharp peaks in the frequency domain of a time trace by detecting
        the peaks and applying a cascade of notch filters on the time trace '''
    # Step 1: Calculate FFT in which we want to look for peaks
    f, fft = multitaper_psd(data, fs, NW=fft_res)

    # Step 2: Find Peaks in FFT
    # If select is prominence, select the peaks by prominence
    if select[0] == 'prominence':
        # find peaks with prominence limit
        peaks, props = find_peaks(np.log(fft), prominence=select[1])
        proms = props["prominences"]
        # remove peaks below f_min
        thrs = np.where(f[peaks] < fmin)[0]
        if len(thrs)>=1:
            peaks = peaks[thrs[-1] + 1:]
            proms = proms[thrs[-1] + 1:]
        print(f'{len(peaks)} peaks found at prom={select[1]}')
    # If select is by peak_number try using init_prome to find peaks with
    # prominence values and sort by prominence to take the highest
    elif select[0] == 'nb_peaks':
        nb_target = select[1]
        nb_found = 0
        while nb_found < nb_target:
            # find peaks with prominence limit
            peaks, props = find_peaks(np.log(fft), prominence=init_prom)
            proms = props["prominences"]
            # remove peaks below f_min
            thrs = np.where(f[peaks] < fmin)[0]
            if len(thrs)>=1:
                peaks = peaks[thrs[-1] + 1:]
                proms = proms[thrs[-1] + 1:]
            nb_found = len(peaks)
            print(f'{nb_found} peaks found at prom={init_prom}')
            init_prom /= 10
        # when enough peaks are found sort by prominence and select highest
        #sort peaks by prominence
        sorted_indices = np.argsort(proms)[::-1]  # descending order
        peaks = peaks[sorted_indices[:nb_target]]  # take nb_peaks most prominent
        proms = proms[sorted_indices[:nb_target]]
    else:
        raise Exception('Not implemented!')
    fpeaks = np.sort(f[peaks])
    print(f'{len(fpeaks)} peaks selected with prominence above {min(proms)}')

    # Step 3: Apply notch filters for all peaks
    result = notch_cascade(data, fs, fpeaks, Q)

    # Step 4: If plotting was request, do
    if promhist:
        _, props = find_peaks(np.log(fft), prominence=init_prom)
        proms = props["prominences"]
        fig, ax = plt.subplots()
        ax.hist(proms, bins=50)
    if plot:
        fig, [ax0, ax1] = plt.subplots(2)
        ax0.plot(time, data, label='raw')
        ax0.plot(time, result, label='result')
        ax1.vlines(fpeaks, 0, 1, color='grey', alpha=0.5, transform=ax1.get_xaxis_transform())
        ax1.plot(f, fft, label='raw')
        f, fft = multitaper_psd(result, fs, NW=fft_res)
        ax1.plot(f, fft, label='result')
        ax1.set_yscale('log')
        ax1.set_xscale('log')
        ax0.legend()
        ax1.legend()
        fig.tight_layout()
    return result