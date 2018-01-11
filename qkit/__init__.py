# root init for QKIT
# these directories are treated as modules
# HR@KIT/2017
__all__ = ['config','gui','measure','tools', 'analysis','core','instruments','services','storage','logs']

# load configuration from $QKITDIR/config/*
from qkit.config.environment import cfg

# if a local.py file is defined, load cfg dict and overwrite environment entries.
try:
    from qkit.config.local import cfg_local
    for entry in cfg_local.iterkeys():
        cfg[entry] = cfg_local[entry]
except ImportError:
    pass

try:    
    from qkit.config.local import cfg as cfg_local
    for entry in cfg_local.iterkeys():
        cfg[entry] = cfg_local[entry]
except ImportError:
    pass

print ("QKIT configuration initialized -> available as qkit.cfg[...]")
# start initialization (qkit/core/init)
def start():
    print("Starting QKIT framework ... -> qkit.core.startup")
    import qkit.core.startup
    qkit.core.startup.start()
