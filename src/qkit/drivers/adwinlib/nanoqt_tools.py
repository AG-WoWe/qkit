'''
Here are some methods which might be needed to communitate with a
running adbasic firmware of nanoqt. For example reading the current
outputs of the dac cards.
'''

NANOQT_OUTPUTS_DATA = 3

def read_nanoqt_outputs(adwin_instance):
    ''' read the current outputs of nanoqt '''
    return(adwin_instance.GetData_Long(NANOQT_OUTPUTS_DATA, 1, 8))