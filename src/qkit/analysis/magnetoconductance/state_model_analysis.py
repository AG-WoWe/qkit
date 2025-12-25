import numpy as np
import matplotlib.pyplot as plt
from numba import njit, prange

def next_higher_val(val, arr):
    idx = np.argmax(arr > val)
    if idx == 0:
        if val > max(arr):
            return None
    return arr[idx]

def extract_jumps_from_states(t, states, return_indices=False):
    # get state changes by differetiating states
    d_states = np.diff(states)
    # states changes with positive/negative sign are up/down jumps
    j_ups = np.where(d_states > 0)[0]
    j_downs = np.where(d_states < 0)[0]
    if return_indices:
        return {'up': j_ups, 'down': j_downs}
    return {'up': t[j_ups], 'down': t[j_downs]}

# dwell times from states
def dwell_times_from_states(t, states):
    jump_indicees = extract_jumps_from_states(t, states, return_indices=True)
    up_idc = jump_indicees['up']
    down_idc = jump_indicees['down']
    if any(len(arr) == 0 for arr in [up_idc, down_idc]):
        return {'high': np.array([]), 'low': np.array([])}
    # calc dwell times for high state (time between up jump and next down jump)
    t_high = []
    for jump_idx in up_idc:
        next_jump_idx = next_higher_val(jump_idx, down_idc)
        if next_jump_idx:
            t_high.append(t[next_jump_idx] - t[jump_idx])
    # calc dwell times for low state
    t_low = []
    for jump_idx in down_idc:
        next_jump_idx = next_higher_val(jump_idx, up_idc)
        if next_jump_idx:
            t_low.append(t[next_jump_idx] - t[jump_idx])
    return {'high': np.array(t_high), 'low': np.array(t_low)}

def total_dwell_time_from_states(t, states, return_fraction=True):
    total = len(states)
    high_count = np.count_nonzero(states > 0)
    low_count = np.count_nonzero(states < 0)
    # test if all found
    if high_count + low_count != len(states):
        raise Exception('Something unexpected happend when counting states.')
    # return fraction if specified
    high_ratio = (high_count / total)
    low_ratio = (low_count / total)
    if return_fraction:
        return {'high': high_ratio, 'low': low_ratio}
    # return total time in state else
    total_time = t[-1] - t[0]
    return {'high': float(high_ratio * total_time),
            'low': float(low_ratio * total_time)}


def _build_lattice(v_low, v_high, samples_per_full_slope):
    M = int(round(samples_per_full_slope))
    if not (v_high > v_low):
        raise ValueError("Require v_high > v_low.")
    if M <= 0:
        raise ValueError("samples_per_full_slope must be > 0.")

    s_eff = (v_high - v_low) / M
    values = v_low + s_eff * np.arange(M + 1)

    # States in deterministic order
    states = []
    for m in range(M + 1):
        if m == 0:
            poss = (0, +1)
        elif m == M:
            poss = (0, -1)
        else:
            poss = (-1, +1)
        for v in poss:
            states.append((m, v))
    states = np.array(states, dtype=np.int32)
    S = states.shape[0]

    idx_of = {(int(m), int(v)): i for i, (m, v) in enumerate(states)}

    def legal_next_vs(m):
        if m == 0:  return (0, +1)
        if m == M:  return (0, -1)
        return (-1, +1)

    # Build forward edges first (at most 2 per state)
    fwd = [[] for _ in range(S)]  # list of (j, unit_switch_cost)
    for i in range(S):
        m, v = int(states[i, 0]), int(states[i, 1])
        for v_next in legal_next_vs(m):
            m_next = m + v_next
            if not (0 <= m_next <= M):
                continue
            # clip destination velocity at rails if needed
            if m_next == 0 and v_next == -1:
                v_state = 0
            elif m_next == M and v_next == +1:
                v_state = 0
            else:
                if 1 <= m_next <= M - 1:
                    v_state = v_next
                else:
                    v_state = v_next
            j = idx_of[(m_next, v_state)]
            unit_swc = 0.0 if v_state == v else 1.0
            fwd[i].append((j, unit_swc))

    # Invert to predecessors with dynamic width
    pred_lists = [[] for _ in range(S)]
    for i in range(S):
        for (j, unit_swc) in fwd[i]:
            pred_lists[j].append((i, unit_swc))

    max_deg = max((len(pl) for pl in pred_lists), default=0)
    # (0,0) and (M,0) can hit 4; interiors 2; some states (e.g., (0,+1)) may be 0.
    pred_idx = -np.ones((S, max_deg), dtype=np.int32)
    pred_swc = np.zeros((S, max_deg), dtype=np.float64)
    pred_deg = np.zeros(S, dtype=np.int32)
    for j in range(S):
        deg = len(pred_lists[j])
        pred_deg[j] = deg
        for k, (i, unit_swc) in enumerate(pred_lists[j]):
            pred_idx[j, k] = i
            pred_swc[j, k] = unit_swc

    m_of_state = states[:, 0].astype(np.int32)
    v_of_state = states[:, 1].astype(np.int32)
    return values, m_of_state, v_of_state, pred_idx, pred_swc, pred_deg

@njit(parallel=True, fastmath=True)
def _dp_numba(y, values, m_of_state, pred_idx, pred_swc, pred_deg, lambda_switch):
    T = y.shape[0]
    S = m_of_state.shape[0]
    INF = 1.0e300

    # DP layers
    prev = np.empty(S, dtype=np.float64)
    curr = np.empty(S, dtype=np.float64)

    # back[t, j] = argmin predecessor state index leading to (t,j)
    back = -1 * np.ones((T, S), dtype=np.int32)

    # t = 0 initialization: cost = emission only
    for j in range(S):
        m = m_of_state[j]
        err = y[0] - values[m]
        prev[j] = err * err
        back[0, j] = -1

    # main DP
    for t in range(1, T):
        # For each next-state j, minimize over its predecessors (race-free).
        # Parallelize over j.
        for j in prange(S):
            best_cost = INF
            best_i = -1
            deg = pred_deg[j]
            m = m_of_state[j]
            emit = y[t] - values[m]
            emit = emit * emit
            for k in range(deg):
                i = pred_idx[j, k]
                if i < 0:
                    continue
                cost = prev[i] + pred_swc[j, k] * lambda_switch + emit
                if cost < best_cost:
                    best_cost = cost
                    best_i = i
            curr[j] = best_cost
            back[t, j] = best_i
        # swap layers
        tmp = prev
        prev = curr
        curr = tmp

    # find best final state
    j_best = 0
    best_final = prev[0]
    for j in range(1, S):
        if prev[j] < best_final:
            best_final = prev[j]
            j_best = j

    return back, j_best

def fit_two_state_fixed_slope(
    x,
    y,
    v_low,
    v_high,
    std_var,
    samples_per_full_slope,
    penalty,
    plot=False,
    **pltkwargs
):
    """
    Parallel DP (Numba) for two-state-with-linear-ramps model.
    Multicore speedup via prange over next-layer states using predecessor lists.
    """
    y = np.asarray(y, dtype=np.float64)
    T = y.size
    if T == 0:
        raise ValueError("y must be non-empty.")
    if not (v_high > v_low):
        raise ValueError("Require v_high > v_low.")
    if samples_per_full_slope <= 0:
        raise ValueError("samples_per_full_slope must be > 0.")

    # Build lattice & predecessor graph (Python side, once)
    values, m_of_state, v_of_state, pred_idx, pred_swc_unit, pred_deg = _build_lattice(
        float(v_low), float(v_high), float(samples_per_full_slope)
    )
    # Scale unit switch costs by lambda_switch inside numba kernel
    lambda_switch = penalty * std_var**2
    back, j_best = _dp_numba(
        y, values, m_of_state, pred_idx, pred_swc_unit, pred_deg, float(lambda_switch)
    )

    # Backtrace
    m_path = np.empty(T, dtype=np.int32)
    v_path = np.empty(T, dtype=np.int32)

    j = j_best
    for t in range(T - 1, -1, -1):
        m_path[t] = m_of_state[j]
        v_path[t] = v_of_state[j]
        j = back[t, j] if t > 0 else j

    y_fit = values[m_path]

    # Binarize velocities to get states
    states = np.empty(len(v_path))
    # Fix starting state using m_path if first velocity is zero
    if v_path[0] == 0:
        if m_path[0] == 0:
            v_path[0] = -1
        elif m_path[0] == max(m_path):
            v_path[0] = 1
        else:
            raise Exception('Bug: Should not be reachable')
    
    # since the first values are already non-zero we can just replace
    # all zero velocity values with the previous velocity value -> stay in state
    for i, v in enumerate(v_path):
        if v == 0:
            states[i] = states[i-1]
        else:
            states[i] = v

    if plot:
        fig, ax0 = plt.subplots()
        ax0.plot(x, y, label='data')
        ax0.plot(x, y_fit, label='fit')
        if 'xlabel' in pltkwargs:
            ax0.set_xlabel(pltkwargs['xlabel'])
        if 'ylabel' in pltkwargs:
            ax0.set_ylabel(pltkwargs['ylabel'])

    return y_fit, states

def reconstruct_yfit_from_jump_idc(t, jump_indicees, v_low, v_high, samples_per_full_slope):
    """
    Reconstruct the fitted signal purely from up/down jump indices.

    Instead of updating the ramp one sample too early (which caused visible phase
    errors) we treat jumps as events that happen *after* sample ``idx`` and only
    change the velocity for the subsequent sample. The initial state is inferred
    from the first jump direction, falling back to the low state if no jump is
    available.
    """
    t = np.asarray(t)
    N = t.size
    if N == 0:
        return np.array([])

    M = int(round(samples_per_full_slope))
    if M <= 0:
        raise ValueError("samples_per_full_slope must be > 0.")
    if not (v_high > v_low):
        raise ValueError("Require v_high > v_low.")

    s_eff = (v_high - v_low) / M
    values = v_low + s_eff * np.arange(M + 1)

    jump_up = np.sort(np.asarray(jump_indicees.get('up', []), dtype=np.int64))
    jump_down = np.sort(np.asarray(jump_indicees.get('down', []), dtype=np.int64))

    # Build lookup of events happening after sample i
    events = {}
    for idx in jump_up:
        if 0 <= idx < N:
            events.setdefault(idx, []).append(+1)
    for idx in jump_down:
        if 0 <= idx < N:
            events.setdefault(idx, []).append(-1)

    def infer_start_state():
        if not events:
            return -1  # default to low state
        first_idx = min(events)
        directions = events[first_idx]
        # Prefer the first valid direction; mixed directions collapse by priority
        if +1 in directions and -1 in directions:
            return -1  # ambiguous, default to low so first event can ramp up
        return -1 if directions[0] == +1 else +1

    start_state = infer_start_state()
    current_m = 0 if start_state == -1 else M
    current_v = 0

    y_fit = np.empty(N, dtype=float)
    for i in range(N):
        # emit current value before applying possible jump at i
        y_fit[i] = values[current_m]

        if i in events:
            # apply the most recent direction; multiple events collapse to last
            for direction in events[i]:
                current_v = direction

        # advance for next sample
        current_m += current_v
        if current_m <= 0:
            current_m = 0
            current_v = 0
        elif current_m >= M:
            current_m = M
            current_v = 0

    return y_fit
