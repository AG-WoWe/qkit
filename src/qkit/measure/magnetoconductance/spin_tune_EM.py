# spin_watch.py intented for use with arbitrary measurement hardware.
# JF@KIT 04/2021

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
from qkit.gui.notebook.Progress_Bar import Progress_Bar
from qkit.measure.spin_suite.spin_tune import Tuning


class Tuning_EM(Tuning):

    def measure1D(self, data_to_show = None):
        """
        Starts a 1D - measurement, along the x coordinate.
        
        Parameters
        ----------
        data_to_show : List of strings, optional
            Name of Datasets, which qviewkit opens at measurement start.
        """
        assert self._x_parameter, f"{__name__}: Cannot start measure1D. x_parameters required."
        self._measurement_object.measurement_func = "%s: measure1D" % __name__
        self.pb = Progress_Bar(len(self._x_parameter.values) * self.multiplexer.no_active_nodes)

        self._open_qviewkit(datasets = data_to_show)

        try:
            while self.pb.progr < self.pb.max_it:
                print(f'Wait for {self._x_parameter.wait_time}')
                qkit.flow.sleep(self._x_parameter.wait_time)
                latest_data = self.multiplexer.measure()
                self._append_vector(latest_data, self._datasets, direction = 1)
                try:
                    if list(latest_data.values())[0] is not None:
                        print(list(latest_data.values())[0])
                        self.pb.iterate(addend = len(list(latest_data.values())[0]))
                except:
                    print(latest_data)
                if self.watchdog.stop:
                    warn(f"{__name__}: {self.watchdog.message}")
                    break
        finally:
            self.watchdog.reset()
            self._end_measurement()