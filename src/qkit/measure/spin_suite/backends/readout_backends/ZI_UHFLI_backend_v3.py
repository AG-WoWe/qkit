#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mo Jan  26 10:21:24 2026

@author: lr1740
"""
from qkit.measure.spin_suite.backends.readout_backends.RO_backend_base import RO_backend_base

class ZI_UHFLI_backend_v3(RO_backend_base):

    def __init__(self, UHFLI):
        """
        Parameters
        ----------
        UHFLI :
            Instance of ZI_UHFLI_DAQ.
        """
        super().__init__()

        self.UHFLI = UHFLI
        self._id = self.UHFLI._device_id

        # Register measurements
        self.register_measurement("demod0","V", ["x", "y", "r", "theta", "timestamp"])

        # Backend state
        self._active = False

    # ==========================================================
    # DEMOD 0 CONFIGURATION
    # ==========================================================

    def demod0_get_sample_rate(self):
        """
        Return the demodulator sample rate in Hz.
        """
        return self.UHFLI.get_dem0_sample_rate()

    def demod0_set_measurement_count(self, meas_num):
        """
        Set the number of triggered measurements.
        """
        self.UHFLI.set_daq_measurement_count(meas_num)

    def demod0_set_sample_count(self, sample_num):
        """
        Set the number of samples acquired per trigger.
        """
        duration = self.demod0_get_sample_rate() * sample_num

        
        self.UHFLI.set_daq_sample_count(sample_num)

    def demod0_set_averages(self, grid_num):
        """
        Set the number of grid rows/averages.
        """
        self.UHFLI.set_daq_grid(grid_num)

    # ==========================================================
    # ACTIVATION
    # ==========================================================

    def demod0_activate(self):
        """
        Enable demodulator 0 and prepare the DAQ for acquisition.
        """
        self.UHFLI.set_dem0_demod_enable(True)
        # Configure the DAQ through the driver.
        self.UHFLI.setup_triggered_readout()
        # Subscribe to demod0 signals.
        self.UHFLI.sub_dem0()
        self._active = True

    def demod0_deactivate(self):
        """
        Disable demodulator 0.
        """
        self.UHFLI.set_dem0_demod_enable(False)
        self._active = False

    # ==========================================================
    # ACQUISITION
    # ==========================================================

    def arm(self):
        """
        Arm/start the DAQ acquisition.
        """
        if not self._active:
            return
        self.UHFLI.arm()

    def finished(self):
        """
        Return True when the acquisition has finished.
        """
        if not self._active:
            return True
        return self.UHFLI.finished()

    def read(self):
        """
        Read the acquired data.
        The driver is responsible for converting the Zurich
        Instruments DAQ result into the qkit data structure.
        """
        if not self._active:
            return {}
        return self.UHFLI.read()

    def stop(self):
        """
        Stop the current acquisition.
        """
        if not self._active:
            return
        self.UHFLI.stop()

    # ==========================================================
    # OPTIONAL CLEANUP
    # ==========================================================

    def close(self):
        """
        Disable the demodulator and stop the DAQ.
        """
        try:
            self.stop()
        finally:
            self.demod0_deactivate()
    

    