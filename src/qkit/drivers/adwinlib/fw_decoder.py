"""
In NanoQt and all programs of the spin-transistor group, the firmware
running on the adwin can be read out from Par_1 (high priority process)
and Par_2 (low priority process, ONLY Spin-Transistor).

The version is decoded in a 32bit integer divided in 4 bitfields of 8
bits each. The first field holds the software 'name' decoded as an
integer number (SEE DEFINED CONSTANTS AT THE BEGINNING OF THIS MODULE)
and the next fields hold the version number.

Speciality for Spin-Transistor Software: the first number of the version
tells you what kind of process it is. atm. there is 1=lockin, 2=sweep

Example in hex representation of the 4 bitfields:
012ah -> 0.1.2.10 -> Nanoqt: version 1.2.10
12b3h -> 1.2.11.3 -> Spin-Transistor: Sweep_process: version 11.3
"""

class AdwinFirmwareError(Exception):
    """ Error raised, when Firmware running on Adwin is not compatible
        with python adwin driver"""

FIRMWARE_CODE = {'0': 'NANOQT',
                 '1': 'SPIN-TRANSISTOR',
                 '2': 'ELECTROMIGRATION'}
ST_PROCESS_CODE = {'1': 'LOCKIN',
                   '2': 'SWEEP'}
EM_PROCESS_CODE = {'1': 'READOUT',
                   '2': 'SWEEP'}

def firmware_int32_to_string(fw_int32):
    """ Split 32bit integer firnware code read from the Adwin Par_1 or
        Par_2 into the 4 bitfieldsto a string where each field is
        separated by '.' """
    # convert the integer to a 24-bit binary representation
    fw_binary = f"{fw_int32:032b}"
    # split the bits into major, minor and patch level (8 bits each)
    software = int(fw_binary[:8], 2)
    major = int(fw_binary[8:16], 2)  # highest byte
    minor = int(fw_binary[16:24], 2)  # middle byte
    patch = int(fw_binary[24:], 2)  # lowest byte
    # create the version string
    return f"{software}.{major}.{minor}.{patch}"

def decode_adbasic_firmware(fw_int32):
    """ Returns version string of loaded software and its name."""
    # CONVERT INTEGER TO STRING
    fw_code = firmware_int32_to_string(fw_int32)

    # DETECT SOFTWARE
    try:
        software = FIRMWARE_CODE[fw_code.split('.')[0]]
    except KeyError:
        software = 'unknown'
    # fw_int32 = 0 is a plausible case beeing confused with NanoQt
    if fw_int32 == 0:
        software = 'unknown'

    # DETECT VERSION
    version = '.'.join(fw_code.split('.')[1:])

    if software == 'unknown':
        raise AdwinFirmwareError("Unknown firmware version")

    return software, version