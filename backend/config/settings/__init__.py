from .base import *

# Default to development settings
try:
    from .development import *
except ImportError:
    pass
