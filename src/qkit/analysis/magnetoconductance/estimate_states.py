#%%
import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import find_peaks, peak_widths
from scipy.optimize import least_squares

def _soft_step(z, width):
    """
    Smooth Heaviside: 0.5*(1 + tanh(z/width))
    width>0 makes the function differentiable for the optimizer.
    """
    return 0.5 * (1.0 + np.tanh(z / max(width, 1e-12)))

def _soft_box(x, a, b, w):
    """
    Smooth indicator of a <= x <= b using soft steps.
    Approaches 1 between a and b, ~0 outside.
    """
    return _soft_step(x - a, w) * _soft_step(b - x, w)

def two_gauss_with_midplateau(x, p):
    """
    Model:
      y = A1*exp(-0.5*((x-m1)/s1)^2) + A2*exp(-0.5*((x-m2)/s2)^2) + c * I[a=m1, b=m2](x)
    where I is a soft box (smooth approximation to a top-hat) confined between the centers.
    Parameters p (in scaled x-units, see fitter):
      p = [A1, A2, m1, d, s1, s2, c, w]
      m2 = m1 + d
    All amplitudes and c are constrained non-negative by bounds in the fitter.
    """
    A1, A2, m1, d, s1, s2, c, w = p
    m2 = m1 + d
    g1 = A1 * np.exp(-0.5 * ((x - m1) / np.maximum(s1, 1e-12)) ** 2)
    g2 = A2 * np.exp(-0.5 * ((x - m2) / np.maximum(s2, 1e-12)) ** 2)
    plateau = c * _soft_box(x, m1, m2, w)
    return g1 + g2 + plateau

def fit_two_gaussians_with_flat_between(
    x, y,
    fp_distance = 0.2,
    min_sep_sigma=1.0,
    robust=True,
    return_model=True
):
    """
    Fit two Gaussian peaks with a constant value *between* the peaks and zero baseline outside.

    Assumptions enforced / supported:
      - Both peaks lie within [min(x), max(x)].
      - y >= 0 (enforced via bounds on amplitudes and c).
      - Peak stds are similar but fitted independently.
      - Peak separation > (wider std) is encouraged via lower bound on center separation.

    Parameters
    ----------
    x, y : 1D arrays
        Data. x may be in tiny units (e.g. 1e-9..1e-4). The routine rescales internally.
    fp_distance: float
        Peakfinder min distance in units of x range.
    min_sep_sigma : float
        Minimum separation in units of the *initial* sigma guess (>=1 recommended).
    robust : bool
        If True, uses a Huber loss to reduce outlier influence.
    return_model : bool
        If True, also return the evaluated best-fit model on the original x-grid.

    Returns
    -------
    result : dict with keys
        'A1','A2','m1','m2','s1','s2','c','w','success','cost','y_fit'
        Centers (m1,m2) and stds (s1,s2) are in the ORIGINAL x units.
    """
    x = np.asarray(x, dtype=float).ravel()
    y = np.asarray(y, dtype=float).ravel()

    if x.size != y.size:
        raise ValueError(f"x and y must have the same length, got {x.size} and {y.size}.")
    if x.size < 8:
        raise ValueError("Not enough data points to fit (need >= 8).")
    if np.any(y < 0):
        raise ValueError("This fitter assumes non-negative y; found negative values.")

    # Sort by x (if not already)
    order = np.argsort(x)
    x = x[order]
    y = y[order]

    # Scale x to [0,1] for numerical stability; y scaled by its max to ~O(1)
    xmin, xmax = x[0], x[-1]
    span = xmax - xmin
    if span <= 0:
        raise ValueError("x must span a non-zero range.")
    xs = (x - xmin) / span

    ymax = np.max(y) if np.max(y) > 0 else 1.0
    ys = y / ymax

    # Initial guesses via peak detection on scaled data
    # A light smoothing helps robustness, but keep it optional/minimal
    # (Here we skip explicit smoothing to avoid user dependencies.)
    peaks, _ = find_peaks(ys, distance=len(x)*fp_distance )  # enforce some separation
    if len(peaks) >= 2:
        # take two highest peaks
        top2 = peaks[np.argsort(ys[peaks])][-2:]
        i1, i2 = np.sort(top2)
    elif len(peaks) == 1:
        # one detected peak; place second near opposite side
        i1 = peaks[0]
        i2 = np.clip(i1 + len(ys)//3, 0, len(ys)-1)
        if i2 == i1:
            i2 = min(len(ys)-1, i1+1)
    else:
        # no peaks found — fall back to quartiles
        i1 = len(ys)//3
        i2 = 2*len(ys)//3

    m1_0, m2_0 = xs[i1], xs[i2]
    if m1_0 > m2_0:
        m1_0, m2_0 = m2_0, m1_0

    # Estimate widths using peak_widths if peaks exist
    try:
        widths_sample = peak_widths(ys, [i1, i2], rel_height=0.5)[0]  # in samples
        # Convert sample widths (approx FWHM) to sigma via: FWHM = 2*sqrt(2*ln 2)*sigma
        fwhm_to_sigma = 1.0 / (2.0*np.sqrt(2.0*np.log(2.0)))
        s1_0 = (widths_sample[0] / max(len(ys)-1, 1)) * fwhm_to_sigma
        s2_0 = (widths_sample[1] / max(len(ys)-1, 1)) * fwhm_to_sigma
        s_guess = float(np.clip(np.median([s1_0, s2_0, 0.03]), 1e-3, 0.2))
    except Exception:
        s_guess = 0.03  # in scaled units as a robust default

    # Initial amplitudes
    A1_0 = float(ys[i1])
    A2_0 = float(ys[i2])

    # Initial plateau: median y between the two centers
    lo, hi = min(i1, i2), max(i1, i2)
    mid_slice = ys[lo:hi+1] if hi > lo else ys
    c_0 = float(np.clip(np.median(mid_slice), 0.0, np.max(ys)))

    # Soft-step width for the box (small → sharper edges)
    w_0 = 0.5 * s_guess
    w_0 = float(np.clip(w_0, 1e-3, 0.1))

    # Separation lower bound as min_sep_sigma * initial sigma guess
    min_d = float(np.clip(min_sep_sigma * s_guess, 5e-3, 0.5))
    d_0 = float(np.clip(m2_0 - m1_0, min_d, 0.9))

    # Parameter vector (scaled-x coordinates):
    # p = [A1, A2, m1, d, s1, s2, c, w]
    p0 = np.array([A1_0, A2_0, m1_0, d_0, s_guess, s_guess, c_0, w_0], dtype=float)

    # Bounds
    # amplitudes & c >= 0; m1 in [0, 1-min_d], d in [min_d, 1], s in [smin, smax], w in [1e-3, 0.2]
    smin, smax = 5e-4, 0.5
    lb = np.array([0.0, 0.0, 0.0, min_d, smin, smin, 0.0, 1e-3])
    ub = np.array([10.0, 10.0, 1.0 - min_d, 1.0, smax, smax, 10.0, 0.2])

    # Residual function
    def residuals(p):
        yhat = two_gauss_with_midplateau(xs, p)
        # Encourage non-overlapping peaks implicitly via d lower bound; no extra penalty needed.
        return yhat - ys

    # Fit
    loss = "huber" if robust else "linear"
    res = least_squares(residuals, p0, bounds=(lb, ub), loss=loss, f_scale=0.05, max_nfev=2000)

    p_hat = res.x
    A1, A2, m1s, d, s1s, s2s, cs, ws = p_hat
    m2s = m1s + d

    # Convert back to original x-units and y scale
    m1 = xmin + m1s * span
    m2 = xmin + m2s * span
    s1 = s1s * span
    s2 = s2s * span
    A1 = A1 * ymax
    A2 = A2 * ymax
    c = cs * ymax
    w = ws * span

    y_fit = None
    if return_model:
        # Evaluate model on original x-grid (using scaled params for consistency)
        y_fit_scaled = two_gauss_with_midplateau(xs, res.x)
        y_fit = y_fit_scaled * ymax

    return {
        "A1": A1, "A2": A2,
        "m1": m1, "m2": m2,
        "s1": s1, "s2": s2,
        "c": c, "w": w,
        "success": bool(res.success),
        "cost": float(res.cost),
        "y_fit": y_fit,
    }

def fit_two_states(y, bins=100, fp_distance=0.2, min_sep_sigma=0, ax=None):
    ''' Fit two states by making a histogram of y and fit double gaussian with constant
        pletaeu in the middle '''
    yhist, bin_edges = np.histogram(y, bins=bins)
    bin_mids = np.array([(b + bin_edges[i+1]) / 2 for i, b in enumerate(bin_edges[:-1])])
    res = fit_two_gaussians_with_flat_between(bin_mids, yhist, fp_distance, min_sep_sigma)
    m1 = res['m1']
    s1 = res['s1']
    m2 = res['m2']
    s2 = res['s2']
    yfit = res['y_fit']

    if ax:
        ax.plot(bin_mids, yhist, label='conductance histogram')
        ax.plot(bin_mids, yfit, label='double gaussian fit')
        ax.errorbar(m1, 0.6065 * yfit[np.argmin(np.abs(bin_mids-m1))], xerr=s1, color='grey')
        ax.errorbar(m2, 0.6065 * yfit[np.argmin(np.abs(bin_mids-m2))], xerr=s2, color='grey')
        ax.set_xlabel('Conductance as measured')
        ax.set_ylabel('Count')
        ax.legend()
    mean_std = (s1 + s2)/2
    return {'mu1': m1, 'mu2': m2, 'std1': s1, 'std2': s2, 'std': mean_std}

def fit_joint_parallel_fixed_gap_single_x(x, Y, gap, n_iter=50, tol=1e-12):
    """
    Joint fit for multiple traces sharing the same x grid.

    Model per trace j:
      y_j[i] = m*x[i] + b_j + s_j[i]*(gap/2),  where s_j[i] ∈ {-1,+1}

    Parameters
    ----------
    x : array-like, shape (N,) or (N,1)
    Y : array-like, shape (J,N) or (N,J)
        Multiple traces. If shape is (N,J) it will be transposed.
    gap : float
        Fixed vertical separation between the two curves.
    n_iter : int
    tol : float

    Returns
    -------
    m : float
        Shared slope across traces (in original x units).
    b_centers : ndarray, shape (J,)
        Center intercept for each trace in original x units.
    labels : ndarray, shape (J,N)
        0 = lower curve, 1 = upper curve for each point.
    """
    x = np.asarray(x).ravel()
    Y = np.asarray(Y)

    if Y.ndim != 2:
        raise ValueError("Y must be 2D (J,N) or (N,J).")

    # Ensure Y is (J, N)
    if Y.shape[1] != x.size and Y.shape[0] == x.size:
        Y = Y.T
    if Y.shape[1] != x.size:
        raise ValueError(f"x has length {x.size} but Y has shape {Y.shape} (expected (J,{x.size})).")

    J, N = Y.shape
    d2 = gap / 2.0

    # Normalize x for numerical stability
    x0 = x.mean()
    xs = x.std() if x.std() > 0 else 1.0
    xn = (x - x0) / xs  # (N,)

    # Flatten data: stack traces
    y = Y.reshape(-1)                 # (J*N,)
    xrep = np.tile(xn, J)             # (J*N,)
    jidx = np.repeat(np.arange(J), N) # (J*N,)

    # Init labels per trace via median split
    labels = (Y >= np.median(Y, axis=1, keepdims=True)).astype(int)  # (J,N)
    z = labels.reshape(-1)  # (J*N,)
    s = np.where(z == 1, +1.0, -1.0)

    # Prebuild one-hot columns for b_j using indexing trick:
    # We'll solve least squares on A = [xrep, onehot(jidx)]
    # Construct onehot efficiently:
    B = np.eye(J)[jidx]  # (J*N, J)

    m_old = None
    for _ in range(n_iter):
        A = np.column_stack([xrep, B])  # (J*N, 1+J)

        # Fit to adjusted y
        y_adj = y - s * d2
        beta, *_ = np.linalg.lstsq(A, y_adj, rcond=None)
        m_n = beta[0]
        b_n = beta[1:]  # (J,) in normalized-x coordinates

        # Reassign
        yhat_center = m_n * xrep + b_n[jidx]
        r_upper = y - (yhat_center + d2)
        r_lower = y - (yhat_center - d2)
        z_new = (np.abs(r_upper) < np.abs(r_lower)).astype(int)
        s_new = np.where(z_new == 1, +1.0, -1.0)

        if m_old is not None and abs(m_n - m_old) < tol and np.all(z_new == z):
            z, s = z_new, s_new
            break

        m_old = m_n
        z, s = z_new, s_new

    # Convert back to original x units
    m = m_n / xs
    b_centers = b_n - m * x0  # because m_n*xn = m*(x-x0)
    labels = z.reshape(J, N)

    return m, b_centers, labels

def robust_gap_estimate(y):
    y = np.asarray(y).ravel()
    med = np.median(y)
    lo = np.median(y[y < med])
    hi = np.median(y[y >= med])
    return float(hi - lo)

def find_nearest_idc(i, number, max_i):
    """ Find nearest indices around index i with given number of points """
    half = number // 2
    i_min = max(0, i - half)
    i_max = i_min + number -1
    if i_max > max_i:
        i_max = max_i
        i_min = i_max - (number -1)
    return i_min, i_max

def remove_linear_slope(x, y, i, conductance_array, include_neighbors=10, istart=None, istop=None, ax=None):
    """ Remove linear slope (around center of the trace) from y using neighboring traces """
    i_min, i_max = find_nearest_idc(i, include_neighbors, conductance_array.shape[0] - 1)
    subarray = conductance_array[i_min:i_max + 1, istart:istop]
    gap = robust_gap_estimate(subarray)
    m, b_centers, labels = fit_joint_parallel_fixed_gap_single_x(x[istart:istop], subarray , gap)
    y_detrended = y - (m * x)
    if ax:
        ax.plot(x, y, label='raw')
        ax.plot(x, y_detrended, label='detrended')
    return y_detrended, m, b_centers[i - i_min], gap


if __name__ == '__main__':
    pass