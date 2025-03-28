''' The io_handler is meant to build the interface between the bit
    values of the adc's and dac's and the physical quantities the user
    wants to apply at the DUT. Therefore, i see the Adwin Outputs in
    combination with everything between the adc/dac and the DUT:
    * Magnetic fields: The current sources and the supraconducting
        coils determine the translation factor between bit_values and
        magnetic fields.
    * Current outputs: voltage_dividers, gain_stages, and filters
        determine the voltage which is applied at the sample.
    * Inputs: IV_converters, gain_stages, voltage_dividers determine
        what quantity is measured (can be voltage in 4-point measurement
        or current in IV-converter measurements, inphase/quadrature for
        lokin_measurmeent)
    For all cases the outputs are defined in two seperate configs:
    * Hard_config: Holds of config parameters, which need to be changed
        by physically altering the setup and are not reguarly changed
        like: output_channels, vector_magnet, current sources ...
    * Soft_config: Holds all parameters, which can be easily changed
        between measurements by flipping switches like voltage dividers.
    * WARNING THIS SRIPT HANDLES ONLY 16 bit output channels!

EXAMPLE CONFIGS:

# 'hard wired' configuration of the adwin and accessories
hard_config = {
    'no_output_channels': 8,
    'outputs': {
        'bx': {'card': 3, 'channel': 1, 'scale': 0.995, 'unit': 'T', 'bits':16},
        'by': {'card': 3, 'channel': 3, 'scale': 0.945, 'unit': 'T', 'bits':16},
        'bz': {'card': 3, 'channel': 5, 'scale': 1.265, 'unit': 'T', 'bits':16},
        'vg': {'card': 3, 'channel': 7, 'scale': 10, 'unit': 'V', 'bits':16},
        'vd': {'card': 3, 'channel': 8, 'scale': 10, 'unit': 'V', 'bits':16}
        },
    'inputs': {
        'id': {'card': 2, 'channel': 8, 'scale': 10, 'unit': 'A', 'bits': 18}
        }
    }

# between measurement 'switchable' configuration of adwin accessories 
soft_config = {
    'vdivs': {'vg':0.5, 'vd':0.01},
    'iv_gain': {'id':1e8},
    'readout_channel': 'id'
}

'''

import math
from math import sqrt, atan2
import logging as log
from numpy import ndarray, float32
import numpy as np

__version__ = '1.0_20240425'
__author__ = 'Luca Kosche'

def bit2volt(val: int|float|ndarray|list, bits, vrange, absolute):
    """ Calculate voltage from bit value for card with voltage range -10V
        to 10V with 16-bits (default). 
        absolute=True: 0 -> -vrange
        absolute=False: 0 -> 0"""
    match val:
        case float32() | float() | int() | np.int32():
            if absolute:
                res = val * vrange / 2**(bits-1) - vrange
            else:
                res = val * vrange / 2**(bits-1)
            return res
        case list():
            return [bit2volt(v, bits, vrange, absolute) for v in val]
        case ndarray():
            return np.vectorize(bit2volt)(val, bits, vrange, absolute)
        case _:
            raise AdwinArgumentError

def volt2bit(val, bits=16, vrange=10, absolute=True):
    """ Calculating bit value from voltage for card with voltage range -10V
        to 10V with 16-bits (default). """
    bit0 = 2**(bits-1)
    match val:
        case float32() | float() | int():
            if not math.isnan(val):
                if absolute:
                    res = round(val * bit0 / vrange + bit0)
                    if 0 <= res <= 2**bits:
                        return res
                else:
                    res = round(val * bit0 / vrange)
                    if -bit0 <= res <= bit0:
                        return res
            # if there is no return so far, raise error
            raise AdwinInvalidOutputError
        case list():
            return [volt2bit(v, bits, vrange) for v in val]
        case ndarray():
            return np.vectorize(volt2bit)(val, bits, vrange)
        case _:
            raise AdwinArgumentError

def calc_r(x, y):
    ''' Calc R of lockin signal from X and Y. '''
    match x:
        case int() | float():
            return sqrt(x**2 + y**2)
        case list():
            return [calc_r(x[i], y[i]) for i in range(len(x))]
        case np.ndarray():
            return np.vectorize(calc_r)(x, y)

def calc_theta(x, y):
    ''' Calc theta of lockin signal from X and Y. '''
    match x:
        case int() | float():
            return atan2(y, x)
        case list():
            return [calc_theta(x[i], y[i]) for i in range(len(x))]
        case np.ndarray():
            return np.vectorize(calc_theta)(x, y)

class AdwinTransmissionError(Exception):
    """ Error which happens, when the adwin does send more or less than
        expected samples during readout. There might be some handlers in
        place accpeting some deviation """

class AdwinModeError(Exception):
    """ Error when unsupported functions for the currently seleted mode
        are used """

class AdwinLimitError(Exception):
    """ Error when unsupported parameters are used for the Adwin
        functions """

class AdwinInvalidOutputError(Exception):
    """ Error when the Adwin is supposed to put out a value outside of
        it's range """

class AdwinArgumentError(Exception):
    """ Error raised, when function arguments are systematically of the
        wrong type """

class AdwinNotImplementedError(Exception):
    """ Error raised, when a specific case or function is not implemented"""

class AdwinIO():
    ''' This class holds Adwin output and input configuration and
        translates between physical quantities and bit_values values.
        So far 16-bit output cards are assumed. '''
    def __init__(self, hard_config:dict, soft_config:dict):
        # save a copy of hard_config (which should never be changed)
        self.__hard_config = {**hard_config}
        self.__soft_config = {**soft_config}
        # save configuration outputs, in which the scaling factor will be
        # updated by the soft_config and runtime changes
        self._ports = {**hard_config['outputs'],
                       **hard_config['inputs'],
                       **hard_config['nc']}

        # soft config
        self.update_soft_config(**soft_config)

    def update_soft_config(self,
                           vdivs: dict = None,
                           iv_gain: dict = None):
        ''' update soft configuration parameters '''
        if vdivs:
            self.set_voltage_diviers(vdivs)
        if iv_gain:
            self.set_iv_converters(iv_gain)

    def set_voltage_diviers(self, dividers: dict):
        ''' set total voltage divider for output channels between 
            adwin and sample including dividers, gain or filters.
            Sanity check might need an update. '''
        if isinstance(dividers, dict):
            for name, vdiv in dividers.items():
                # sanity check
                if not 0.0001 <= vdiv <= 1:
                    raise AdwinLimitError
                base_scale = self.__hard_config['outputs'][name]['scale']
                self._ports[name]['scale'] = base_scale * vdiv
                self.__soft_config[name] = vdiv
        else:
            raise AdwinArgumentError

    def set_iv_converters(self, iv_gain: dict):
        ''' set the total gain of the iv_converters for input channels
            (total gain of the IV_stage including potential voltage
            or filters after the IV converter itself)'''
        if isinstance(iv_gain, dict):
            for name, gain in iv_gain.items():
                base_scale = self.__hard_config['inputs'][name]['scale']
                self._ports[name]['scale'] = base_scale / gain
                self.__soft_config[name] = gain
        else:
            raise AdwinArgumentError

    def qty2bit(self, values:int|float, name:str=None, card:int=None,
                channel:int=None, absolute:bool=True):
        ''' Transform the physical quantities of the outputs into bit
            values using the given information about the used setup '''

        if name is not None:
            if name == 'input':
                port_name = self.__hard_config['inputs'].keys()[0]
            else:
                port_name = name
        elif card is not None and channel is not None:
            port_name = self.get_name(card, channel)
            # check that if name, channel and card are given, that the
            # match
            if name is not None:
                if port_name != name:
                    msg = (f'Adwin: {name}: card={card} and channel='
                          +f'{channel} are not consistent.')
                    log.warning(msg)
                    raise AdwinArgumentError
        else:
            log.critical('Adwin: Output/Input not known.')
            raise AdwinArgumentError

        scale = self._ports[port_name]['scale']
        bits = self._ports[port_name]['bits']
        return volt2bit(values, bits, scale, absolute)

    def bit2qty(self, values:int|list, name:str=None, card:int=None,
                    channel:int=None, absolute:bool=False):
        ''' Translate bit values of any channel into the physical
            quantity using the information of the scaling factor, the 
            resolution of the card and any used voltage divider or gain
            between sample and channel. Either the name or both card and
            channel number have to be specified. For absolute=True,
            zero is bit 0 and absolute=False zero is the middle of the
            bit value range'''
        if name is not None:
            if name == 'input':
                input_list = list(self.__hard_config['inputs'])
                if len(input_list) == 1:
                    port_name = input_list[0]
                elif len(input_list == 0):
                    log.critical('ADwin: No input configured.')
                    raise AdwinArgumentError
                else:
                    log.critical('ADwin: More than one input configured'
                                + '. Please specify input by name.')
                    raise AdwinArgumentError
            else:
                port_name = name
        elif card is not None and channel is not None:
            port_name = self.get_name(card, channel)
            # check that if name, channel and card are given, that the
            # match
            if name is not None:
                if port_name != name:
                    msg = (f'Adwin: {name}: card={card} and channel='
                          +f'{channel} are not consistent.')
                    log.warning(msg)
                    raise AdwinArgumentError
        else:
            log.critical('Adwin: Output/Input not known.')
            raise AdwinArgumentError

        scale = self._ports[port_name]['scale']
        bits = self._ports[port_name]['bits']
        return bit2volt(values, bits, scale, absolute)

    def get_name(self, card:int, channel:int):
        ''' Return name of the Output/Input of card, channel '''
        for key, val in self._ports.items():
            if val['card'] == card and val['channel'] == channel:
                return key
        return None

    def list_connected_outputs(self):
        ''' List names of connected outputs of the ADwin '''
        return list(self.__hard_config['outputs'])

    def list_all_outputs(self):
        ''' List names of all outputs of the ADwin '''
        return list(self.__hard_config['outputs']) + list(self.__hard_config['nc'])

    def get_config(self):
        ''' Return current adwin configuration (ports,IVconv,dviv) ''' 
        return {'hard_config': {**self.__hard_config}, 
                'solf_config': {**self.__hard_config}}

    def output_zero_dict(self):
        ''' Return a dictionary with the names of all adwin outputs
            and the values representing the bit values at which the
            outputs are 0V '''
        names = self.list_all_outputs()
        zdict = {}
        for name in names:
            zdict[name] = 2**(self._ports[name]['bits']-1)
        return  zdict

    def get_card_channel(self, name):
        ''' Return the card and channel number of output with "name" '''
        return self._ports[name]['card'], self._ports[name]['channel']

    def get_sorted_channel_list(self):
        ''' Return a list of all output channel names ordered first by
            card and then by channel number '''
        outs = self.list_all_outputs()
        return sorted(outs, key=lambda name: (self._ports[name]['card'],
                      self._ports[name]['channel']))

if __name__ == '__main__':
    pass
