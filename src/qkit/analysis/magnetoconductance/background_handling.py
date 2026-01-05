import numpy as np

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

def remove_linear_slope(x, y, i, conductance_array, include_neighbors=10, istart=None, istop=None):
    """ Remove linear slope (around center of the trace) from y using neighboring traces """
    i_min, i_max = find_nearest_idc(i, include_neighbors, conductance_array.shape[0] - 1)
    subarray = conductance_array[i_min:i_max + 1, istart:istop]
    gap = robust_gap_estimate(subarray)
    m, b_centers, labels = fit_joint_parallel_fixed_gap_single_x(x[istart:istop], subarray , gap)
    y_detrended = y - (m * x)
    return y_detrended, m, b_centers[i - i_min], gap