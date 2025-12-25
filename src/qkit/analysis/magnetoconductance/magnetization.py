#%%
from hairy_plotter import HairyPlotter
from scipy.optimize import least_squares
import numpy as np

def energy_difference(x, mu, delta, x0=0.0):
    """
    Splitting between upper and lower adiabatic energies.
    Parameters
    ----------
    x : float or array
    s : float          # diabatic slope difference
    delta : float      # minimum gap at x0
    x0 : float         # crossing center
    """
    x = np.asarray(x)
    return np.sqrt((2 * mu * (x - x0))**2 + delta**2)

def energies(x, mu, delta, x0=0.0, E0=0.0):
    """
    Adiabatic eigenenergies [E_lower, E_upper].
    """
    split = energy_difference(x, mu, delta, x0)
    return np.vstack((E0 - 0.5 * split, E0 + 0.5 * split))

def spin_up_prob_with_delta(B, T, mu, delta):
    """
    Thermal probability of the diabatic spin-up state (m_s=+1/2)
    for a two-level system with zero-field mixing gap Delta.

    Parameters
    ----------
    B : float or array
        Magnetic field [T]
    T : float
        Temperature [K]
    g : float
        g-factor (default 2.0 for electron)
    delta_K : float
        Zero-field splitting in Kelvin units (Delta/k_B). If you have Delta in eV,
        use delta_K = Delta_eV / (8.617333262e-5).

    Returns
    -------
    p_up : float or array
        Probability of spin-up in the diabatic basis.
    """
    B = np.asarray(B)
    Dz = 2 * mu * B          # Zeeman term in K
    Esplit = np.sqrt(Dz**2 + delta**2)
    # Avoid division-by-zero at Esplit_K=0
    with np.errstate(divide='ignore', invalid='ignore'):
        term = np.where(Esplit > 0, Dz / Esplit, 0.0)
    return 0.5 * (1.0 + term * np.tanh(0.5 * Esplit / T))

def spin_expectation_nuclear(B, T, mu, delta, xi, pni):
    """
    Thermal expectation value <sigma_z> of a two-level spin system with an
    avoided crossing, averaged over 4 nuclear spin states (I = 3/2).

    Parameters
    ----------
    B : float or array_like
        Magnetic field (T).
    T : float
        Temperature (same energy units as mu and delta, using k_B = 1).
    mu : float
        Magnetic moment of the spin (energy per Tesla, same units as delta/T).
    delta : float
        Energy gap at the avoided crossing (same energy units as mu*B).
    xi : array_like, shape (4,)
        Field shifts for the nuclear states [xi1, xi2, xi3, xi4] (in T).
    pni : array_like, shape (4,)
        Nuclear populations [pn1, pn2, pn3, pn4] (will be normalized).

    Returns
    -------
    sz : float or ndarray
        Expectation value <sigma_z> as a function of B.
        If B is scalar -> float, if array -> ndarray with same shape as B.

    Notes
    -----
    If you want <S_z>, use:
        Sz = 0.5 * hbar * sz
    """

    # Convert inputs
    B = np.atleast_1d(np.asarray(B, dtype=float))   # shape (N,)
    T = float(T)
    xi = np.asarray(xi, dtype=float).reshape(-1, 1) # shape (4, 1)
    pni = np.asarray(pni, dtype=float)

    # Normalize nuclear populations
    pni = pni / np.sum(pni)

    beta = 1.0 / T

    # epsilon_i(B) = 2 * mu * (B - xi_i)
    # Broadcasting: xi -> (4,1), B -> (1,N) => epsilon -> (4,N)
    epsilon = 2.0 * mu * (B - xi)
    Omega = np.sqrt(epsilon**2 + delta**2)          # (4,N)

    # <sigma_z> in each nuclear subspace i
    sz_i = -(epsilon / Omega) * np.tanh(0.5 * beta * Omega)  # (4,N)

    # Weighted sum over nuclear populations: pni (4,) @ sz_i (4,N) -> (N,)
    sz = pni @ sz_i

    # If input B was scalar, return scalar
    if sz.size == 1:
        return float(sz[0])
    return sz

def theta_to_T_pni(theta):
    """
    Map unconstrained theta to physical parameters T > 0 and pni >= 0, sum=1.
    theta[0] = logT
    theta[1:5] = a_i  -> pni via softmax
    """
    logT = theta[0]
    a = np.array(theta[1:5])
    
    T = np.exp(logT)                  # T > 0
    exp_a = np.exp(a - np.max(a))     # softmax, numerically stable
    pni = exp_a / np.sum(exp_a)       # 4-element vector, positive, sum=1
    
    return T, pni

def residuals_theta(theta, B_data, sz_data, sz_err, mu, delta, xi):
    """
    Residuals between data and model as a function of unconstrained theta.
    """
    T, pni = theta_to_T_pni(theta)
    sz_model = spin_expectation_nuclear(B_data, T, mu, delta, xi, pni)
    
    if sz_err is None:
        return sz_model - sz_data
    else:
        return (sz_model - sz_data) / sz_err

def init_theta(T0, pni0):
    """
    Build initial theta from an initial guess of T and pni.
    pni0 should be length-4, positive and sum to 1 (but we re-normalize anyway).
    """
    pni0 = np.asarray(pni0, dtype=float)
    pni0 = pni0 / np.sum(pni0)
    
    logT0 = np.log(T0)
    # inverse of softmax (up to a constant): we can just take a_i = log(p_i)
    # any constant offset to all a_i doesn't matter, so this is fine.
    a0 = np.log(pni0)
    
    theta0 = np.concatenate(([logT0], a0))
    return theta0

def fit_Jz(B_data, sz_data, mu, xi, delta, sz_err=None, T0=None, pni0=None):
    theta0 = init_theta(T0, pni0)

    result = least_squares(
        residuals_theta,
        theta0,
        args=(B_data, sz_data, sz_err, mu, delta, xi),
        method='trf',  # trust region reflective (good default)
    )

    theta_fit = result.x
    T_fit, pni_fit = theta_to_T_pni(theta_fit)
    print("Fit success:", result.success)
    print("Fit message:", result.message)
    print("Best-fit T:", T_fit)
    print("Best-fit pni:", pni_fit)
    return T_fit, pni_fit, result

#%%
if __name__ == "__main__":

    plotter = HairyPlotter('plot_config.json')
    fig, [ax1, ax2] = plotter.create_subplots(nrows=2, ncols=1)

    kB = 1
    mub = 0.671714 # in K/T

    B = np.linspace(-0.08, 0.06, 120)
    mu = 9 * mub
    delta = 1e-6
    T = 0.08


    # for delta in [1e-6, 0.1, 0.58]:
    #     E0, E1 = energies(B, mu, delta)
    #     line = ax1.plot(B, E0)
    #     ax1.plot(B, E1, color=line[0].get_color(), label=f'Δ={delta:.1e} K')
    #     ax2.plot(B, spin_up_prob_with_delta(B, T=T, mu=mu, delta=delta))
    # #plotter.save_pdf('magnetization_example.pdf')

    # delta = 1e-6
    # for delta in [1e-6, 0.58]:
    #     E0, E1 = energies(B, mu, delta)
    #     line = ax1.plot(B, E0)
    #     ax1.plot(B, E1, color=line[0].get_color(), label=f'Δ={delta:.1e} K')
    #     #ax2.plot(B, spin_up_prob_with_delta(B, T=temp, mu=mu, delta=delta))

    ax2.plot(B, spin_up_prob_with_delta(B, T=0.1, mu=mu, delta=0.5))
    ax2.plot(B, spin_up_prob_with_delta(B, T=0.3, mu=mu, delta=1e-6))

#%%

    #mu    = 9.0          # e.g. in K/T if you use mu_B/k_B
    xi    = [-0.049, -0.02, 0.008, 0.035]  # T
    pni   = [0.25, 0.25, 0.25, 0.25]    # equal populations
    T     =  0.1        # K
    #B     = np.linspace(-0.1, 0.1, 501) # T

    #ax2.plot(B, spin_up_prob_with_delta(B, T, mu, delta))
    
    #fit
    B_data = B
    sz_data = spin_expectation_nuclear(B, T, mu, delta, xi, pni)
    T0 = 0.01
    pni0 = [0.25,0.25,0.25,0.25]
    t_fit, pni_fit, _ = fit_Jz(B_data, sz_data, mu, xi, delta, T0=T0, pni0=pni0)
    # plot original
    ax2.plot(B, -1/2 * sz_data + 0.5)
    # plot fit
    ax2.plot(B, -1/2 * spin_expectation_nuclear(B, t_fit, mu, delta, xi, pni_fit) + 0.5, linestyle='--')

# %%
