'''
Here are some methods which might be needed to communitate with a
running adbasic firmware of nanoqt. For example reading the current
outputs of the dac cards.
'''

NANOQT_OUTPUTS_DATA = 3

def read_nanoqt_outputs(adw, aio, output_card):
    '''
        Return current outputs of nanoqt.
        Inputs: adw: ADwin.Adwin() instance (able to Read ADwin parameters),
                aio: AdwinIO instance (holding channel configuration),
                output_card used in NanoQt
    '''
    # Nanoqt outputs are allways given as an array with 8 values for a single
    # output card, which needs to be specified
    outputs_bit = adw.GetData_Long(NANOQT_OUTPUTS_DATA, 1, 8)
    channels = range(1, 9)
    # get the names of the channels according to adwin config
    names = [aio.get_name(output_card, ch) for ch in channels]
    return dict(zip(names, outputs_bit))
