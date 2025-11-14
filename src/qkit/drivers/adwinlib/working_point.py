''' The working point module has the purpose to a complete working point of a
    spin-transistor or similar. It works nicely in combination with the adwin,
    because it controls all parameters of a qorking point. So far this are:
        * magnetic fields (either cartesian or spherical coordinates)
            -> this module handles the translation from the abstract spherical
               representation to the cartesian 3D vector magnets used in the 
               experiment
        * voltages applied to the transistor

    ToDO:   * No init values for magnetic field and error handling if no valid
              values are set by the user. (this makes sure that after a restart
              of the software the magnetic fields are not accidently turned off
              but the user has to set explisit values in the measurement script
              ).
              * Add sanity checks if the values set are in the allowed range
              (this would need the config of the adwin here)
    '''

all = ['VectorMagnet3D', 'WorkingPoint']
version = '0.2_20251114'
author = 'Luca Kosche'

from numpy import cos, sin, pi, nan
import numpy as np

class MagnetUnderdefinedError(Exception):
    """ Error which is thrown when the VectorMagnet has not enough
        parameters to calculate """

class UnderdefinedError(Exception):
    """ Error which is raised when not all parameters of the working point are
        set """

def grad2rad(grad):
    """ Transform angle in grad to rad """
    return grad * 2 * pi / 360

class WorkingPoint():
    '''
    The workingpoint holds all output channels (coordinates) which are
    controlled by the adwin. The names for all channels can be defined by the
    user either in a list, or as dictionary with name: init:value.

    outs is returning a dictionary with real coordinates (bx, by, bz for the
    magnet) which the adwin can use as output

    There are 3 possibilities to define the magnetic fields:
    * cartesian: bx, by, bz
    * spherical: theta, phi, b
    * vector3d: seperates the magnetic field in a parallel and transverse field
                which can be controlled and rotated seperately
        Two modes change which component can be rotated
        "sweep": THETA and PHI and Bp define the direction and length of
                 the magnetic field to be swept. The transverse field
                 direction is a linear combination of the unit vectors
                 in spherical cordinates e_theta and e_phi and defined
                 by the angle PSI. The length is defined by Bt.
        "normal": THETA and PHI define the direction of the transverse
                  Field whereas psi defines the direction of Bp.
                  This allows to sweep Bp in the normal plane defines by
                  Bt leaving the transverse field direction constant
                  (not possible in sweep mode).
               
          z |      / Bp
            |theta/.
            |    / .
            |   /  .
            |  /   .
            | /    .
            |/_____.____ y
            /  .   .
           /     . .
          /  phi    . 
       x /
'''
    def __init__(self, coordinates:list|dict, magnet=None):
        self._coords = {}
        self._magnetcoords = {
            'cartesian': ['bx', 'by', 'bz'],
            'spherical': ['theta', 'phi', 'b'],
            'vector3d': ['theta', 'phi', 'psi', 'bt', 'bp', 'mode']}
        # create list of all coords assosiated with the magnet
        self._mcoords = list(set([item for val in self._magnetcoords.values() for item in val]))
        # set magnet
        if magnet is None:
            self._magnet = None
        elif magnet in self._magnetcoords.keys():
            self._magnet = magnet
            for coord in self._magnetcoords[magnet]:
                self._coords[coord] = nan
        else:
            raise Exception('This is not a valid magnet value')

        if isinstance(coordinates, list):
            for coord in coordinates:
                self._coords[coord] = nan
        if isinstance(coordinates, dict):
            for coord, val in coordinates.items():
                self._coords [coord] = val
        self._create_properties(self._coords.keys())

    @property
    def outs(self):
        ''' the outputs property '''
        match self._magnet:
            case None:
                outputs = {k: v for k, v in self._coords.items() if k not in self._mcoords}
            case 'cartesian':
                for coord in self._magnetcoords['cartesian']:
                    outputs[coord] = self._coords[coord]
            case 'spherical':
                # calc bx, by, bz and add to outputs
                self.calc_cartesian_from_spherical()
                outputs = {k: v for k, v in self._coords.items() if k not in self._mcoords}
            case 'vector3d':
                # calc bx, by, bz and add to outputs
                self.calc_cartesian_from_vector3d()
                outputs = {k: v for k, v in self._coords.items() if k not in self._mcoords}
        # check that all values are set
        if nan in outputs.values():
            raise UnderdefinedError
        # optional for future check if values are allowed (but config would be needed)
        return outputs

    def set(self, **kwargs):
        ''' set multiple outputs with a single function call '''
        for key, val in kwargs.items():
            if key in self._coords:
                self._set_coord(key, val)
            else:
                raise Exception(f'Coordinate with key {key} is not available!')

    # _get_coord, _set_coord are generic getter and setter to be able to create
    # the properties dynamically for whatever coords are defined by the user

    def _get_coord(self, name: str):
        ''' getter function for coord "name" '''
        if name in self._magnetcoords['cartesian'] and self._magnet in ['spherical', 'vector3d']:
            match self._magnet:
                case 'spherical':
                    self.calc_cartesian_from_spherical()
                case 'vector3d':
                    self.calc_cartesian_from_vector3d()
        return self._coords[name]

    def _set_coord(self, name: str, val):
        ''' setter function for coord "name" '''
        if name in self._coords:
            #optional for later: sanity check (but config would be needed)
            self._coords[name] = val
        else:
            raise Exception('Coordinate not available')

    def _create_properties(self, names):
        ''' dynamically create properties for all output names '''
        for n in names:
            setattr(
                WorkingPoint,
                n,
                property(
                    fget=lambda self, var=n: self._get_coord(var),
                    fset=lambda self, val, var=n: self._set_coord(var, val)
                )
            )

    def calc_cartesian_from_spherical(self):
        # check that all parameters in self._magnetcoord['spherical'] are available
        spherical = {k: v for k, v in self._coords.items() if k in self._magnetcoords['spherical']}
        if nan in spherical.values():
            raise MagnetUnderdefinedError

        theta = grad2rad(spherical['theta'])
        phi = grad2rad(spherical['phi'])
        b = spherical['b']

        e_r = np.array([sin(theta) * cos(phi), sin(theta) * sin(phi), cos(theta)])

        bp = b * e_r
        
        for i, comp in enumerate(['bx', 'by', 'bz']):
            self._set_coord(comp, bp[i])


    def calc_cartesian_from_vector3d(self):
        # check that all parameters in self._magnetcoord['verctor3d'] are available
        vector3d = {k: v for k, v in self._coords.items() if k in self._magnetcoords['vector3d']}
        if nan in vector3d.values():
            raise MagnetUnderdefinedError

        theta = grad2rad(vector3d['theta'])
        phi = grad2rad(vector3d['phi'])
        psi = grad2rad(vector3d['psi'])
        bp = vector3d['bp']
        bt = vector3d['bt']

        e_r = np.array([sin(theta) * cos(phi), sin(theta) * sin(phi), cos(theta)])
        e_theta = np.array([cos(theta) * cos(phi), cos(theta) * sin(phi), -sin(theta)])
        e_phi = np.array([-sin(phi), cos(phi), 0.0])

        if vector3d['mode'] == 'sweep':
            # caclulate Bp as linear comb. of E_r
            # Bp_vec =  Bp * E_r
            bp_vec = bp * e_r
            # calculate Bt as linear comb. of E_theta and E_phi
            # Bt_vec =  Bt * ( cos(psi) * E_theta + sin(psi)  * E_phi )
            bt_vec = bt * (cos(psi) * e_theta + sin(psi) * e_phi)

        elif vector3d['mode'] == 'normal':
            # caclulate Bt as linear comb. of E_r
            # Bt_vec =  Bt * E_r
            bt_vec = bt * e_r
            # calculate Bp as linear comb. of E_theta and E_phi
            # Bp_vec =  Bp * ( cos(psi) * E_theta + sin(psi)  * E_phi )
            bp_vec = bp * (cos(psi) * e_theta + sin(psi) * e_phi)
        
        # cartesian = superposition of parallel and transverse fields
        b_vec = bt_vec + bp_vec
        # return as tuple for safety reasons (harder to mess up later)
        for i, comp in enumerate(['bx', 'by', 'bz']):
            self._set_coord(comp, b_vec[i])