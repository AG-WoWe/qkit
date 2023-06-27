# -*- coding: utf-8 -*-

# qplexkit.py driver for the homemade qplexkit used for DC multiplexing
# Micha Wildermuth, micha.wildermuth@kit.edu 2023
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

import qkit
from qkit.services.qplexkit import qplexkit
from qkit.core.instrument_base import Instrument
from qkit.config.services import cfg
import logging
import zmq

""" copy docstrings from qplexkit """
import sys
from typing import Callable, TypeVar
if sys.version_info <= (3, 9):
    from typing_extensions import ParamSpec
else:
    from typing import ParamSpec

P = ParamSpec("P")
T = TypeVar("T")


def wraps(wrapper: Callable[P, T]):
    def decorator(func: Callable) -> Callable[P, T]:
        func.__doc__ = wrapper.__doc__
        return func
    return decorator


class qplexkit(Instrument):
    """
    This is the driver for the homemade qplexkit. It is the interface to the Raspberry Pi that controls a current
    source to switch relays at cryogenic temperatures.

    Usage:
    ------
    Initialize with
    <name> = qkit.instruments.create('<name>', 'qplexkit', address=<address>, port=<port>)
    """

    def __init__(self, name, address, port=None):
        """
        Initializes VISA communication with the instrument Yokogawa GS820.

        Parameters
        ----------
        name: string
            Name of the instrument (driver).
        address: string
            IP-address of Raspberry Pi
        port: int, string
            Port of zeroMQ server

        Returns
        -------
        None

        Examples
        --------
        >>> import qkit
        QKIT configuration initialized -> available as qkit.cfg[...]

        >>> qkit.start()
        Starting QKIT framework ... -> qkit.core.startup
        Loading module ... S10_logging.py
        Loading module ... S12_lockfile.py
        Loading module ... S14_setup_directories.py
        Loading module ... S20_check_for_updates.py
        Loading module ... S25_info_service.py
        Loading module ... S30_qkit_start.py
        Loading module ... S65_load_RI_service.py
        Loading module ... S70_load_visa.py
        Loading module ... S80_load_file_service.py
        Loading module ... S85_init_measurement.py
        Loading module ... S98_started.py
        Loading module ... S99_init_user.py
        Initialized the file info database (qkit.fid) in 0.000 seconds.

        >>> qpk = qkit.instruments.create('qpk', 'qplexkit', address='00.00.000.00', port=5555)
        """
        self.__name__ = __name__
        # create instrument
        logging.info(__name__ + ': Initializing instrument qplexkit')
        Instrument.__init__(self, name, tags=['physical'])
        self.cfg = cfg['qplexkit']

        ''' set up zeroMQ client '''
        self._address = address
        if port is None:
            self._port = self.cfg['server_port']
        else:
            self._port = port
        self._context = zmq.Context()
        self.socket = self._context.socket(zmq.REQ)
        self.connect()

        ''' qkit-instrument parameters & functions '''
        self.add_parameter('switch_time',
                           type=float,
                           flags=Instrument.FLAG_GETSET,
                           minval=0,
                           units='s')
        self.add_parameter('experiment',
                           type=int,
                           flags=Instrument.FLAG_GETSET,
                           minval=0,
                           maxval=11)
        self.add_parameter('relays',
                           type=list,
                           flags=Instrument.FLAG_GET)
        self.add_parameter('current_divider',
                           type=bool,
                           flags=Instrument.FLAG_GETSET)
        self.add_parameter('amplifier',
                           type=bool,
                           flags=Instrument.FLAG_GETSET)
        self.add_function('set_relay')
        self.add_function('get_relay')
        self.add_function('get_ccr')
        self.add_function('read_ccr')
        self.add_function('reset')
        self.add_function('get_attr')

    def connect(self, **kwargs):
        self.socket.connect(f'''tcp://{kwargs.get('address', self._address)}:{kwargs.get('port', self._port)}''')

    def disconnect(self, **kwargs):
        self.socket.disconnect(f'''tcp://{kwargs.get('address', self._address)}:{kwargs.get('port', self._port)}''')

    def _query(self, msg):
        """
        Sends a message <msg> and returns the read answer <ans>.

        parameters
        ----------
        msg: str
            Message that is sent to the zeroMQ server running on a Raspberry Pi.
            The message is dumped via json and encoded as binary-string to be zeroMQ compatible.

        returns
        -------
        ans: str
            Answer that is returned at query after the sent message <msg>.
        """
        self.socket.send_json(msg)
        return self.socket.recv_json()

    @wraps(qplexkit.qplexkit.set_switch_time)
    def do_set_switch_time(self, val):
        msg = ("set_switch_time", tuple([val]), dict({}))
        return self._query(msg)

    @wraps(qplexkit.qplexkit.get_switch_time)
    def do_get_switch_time(self):
        msg = ("get_switch_time", tuple([]), dict({}))
        return self._query(msg)

    @wraps(qplexkit.qplexkit.set_experiment)
    def do_set_experiment(self, exp, protect=False, **kwargs):
        msg = ("set_experiment", tuple([exp, protect]), dict(kwargs))
        return self._query(msg)

    @wraps(qplexkit.qplexkit.get_experiment)
    def do_get_experiment(self, **kwargs):
        msg = ("get_experiment", tuple([]), dict(kwargs))
        return self._query(msg)

    @wraps(qplexkit.qplexkit.set_current_divider)
    def do_set_current_divider(self, status, **kwargs):
        msg = ("set_current_divider", tuple([int(status)]), dict(kwargs))
        return self._query(msg)

    @wraps(qplexkit.qplexkit.get_current_divider)
    def do_get_current_divider(self, **kwargs):
        msg = ("get_current_divider", tuple([]), dict(kwargs))
        return bool(self._query(msg))

    @wraps(qplexkit.qplexkit.set_amplifier)
    def do_set_amplifier(self, status, **kwargs):
        msg = ("set_amplifier", tuple([int(status)]), dict(kwargs))
        return self._query(msg)

    @wraps(qplexkit.qplexkit.get_amplifier)
    def do_get_amplifier(self, **kwargs):
        msg = ("get_amplifier", tuple([]), dict(kwargs))
        return bool(self._query(msg))

    @wraps(qplexkit.qplexkit.set_relay)
    def set_relay(self, rel, status, **kwargs):
        msg = ("set_relay", tuple([rel, int(status)]), dict(kwargs))
        return self._query(msg)

    @wraps(qplexkit.qplexkit.get_relay)
    def get_relay(self, rel, **kwargs):
        msg = ("get_relay", tuple([rel]), dict(kwargs))
        return bool(self._query(msg))

    @wraps(qplexkit.qplexkit.get_relays)
    def do_get_relays(self, **kwargs):
        msg = ("get_relays", tuple([]), dict(kwargs))
        return self._query(msg)

    @wraps(qplexkit.qplexkit.get_ccr)
    def get_ccr(self, rel, **kwargs):
        msg = ("get_ccr", tuple([rel]), dict(kwargs))
        return self._query(msg)

    @wraps(qplexkit.qplexkit.read_ccr)
    def read_ccr(self, n=-1, timestamp=False, **kwargs):
        msg = ("read_ccr", tuple([n, timestamp]), dict(kwargs))
        return self._query(msg)

    @wraps(qplexkit.qplexkit.reset)
    def reset(self):
        msg = ("reset", tuple([]), dict({}))
        return self._query(msg)

    def get_attr(self, attr):
        """
        Gets a class attribute <attr> of the qplexkit instance running on the Raspberry Pi.

        Parameters
        ----------
        attr: string
            Name of class attribute.

        Returns
        -------
        val:
            Value of the class attribute.
        """
        msg = ("get_attr", tuple([attr]), dict({}))
        return self._query(msg)

