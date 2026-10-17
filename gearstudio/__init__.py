"""pyGearTrain Studio: build, animate and analyse gear trains from pygeartrain."""
import os
import sys

__version__ = '2.0.0'
APP_NAME = 'pyGearTrain Studio'

# pygeartrain is not on PyPI; a copy is vendored next to this package
_VENDOR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'vendor', 'pyGearTrain')
if os.path.isdir(_VENDOR) and _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)
