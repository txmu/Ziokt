"""Ziokt federation, independently delivered native providers."""
__version__ = "1.0.0"

# Install offline network guards before importing providers or application bridges.
from . import runtime_policy as runtime_policy
