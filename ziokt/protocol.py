"""Public protocol reference, without third-party runtime dependencies."""
from . import _runtime
ProtocolError = _runtime.ProtocolError
strict_json = _runtime.strict_json
encoded = _runtime.encoded
secure_read = _runtime.secure_read
identifier = _runtime.identifier
MAX_REQUEST = _runtime.MAX_REQUEST
MAX_RESPONSE = _runtime.MAX_RESPONSE
MAX_OBJECTS = _runtime.MAX_OBJECTS
PROTOCOL = _runtime.PROTOCOL
