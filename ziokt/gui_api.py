"""Owner-authenticated GUI adapter to the same typed, audited MCP dispatcher."""
import hmac
import time
from .gateway import read_token
from .protocol import secure_read, strict_json


class GuiError(ValueError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def dispatch(gateway, authorization, payload=None):
    if not isinstance(authorization, str) or not hmac.compare_digest(authorization, 'Bearer '+read_token(gateway.config['admin_token'])):
        raise GuiError(401, 'Node administrator authentication required')
    path = gateway.config.get('mcp_config')
    if not path:
        raise GuiError(503, 'GUI tool adapter is not configured')
    with gateway.lock:
        now = time.monotonic()
        calls = [t for t in getattr(gateway, '_gui_calls', []) if now-t < 60]
        if len(calls) >= 1200:
            raise GuiError(429, 'GUI request rate exceeded')
        gateway._gui_calls = calls+[now]
        if getattr(gateway, '_gui_service', None) is None:
            from .mcp import Service
            config = strict_json(secure_read(path));config['config_path'] = str(path)
            gateway._gui_service = Service(config)
        service = gateway._gui_service
    client = service.client('ziokt-operator')
    if not client:
        raise GuiError(403, 'Owner MCP client unavailable')
    principal = {'client':'ziokt-operator','scopes':set(client['scopes']), 'expires':2**63, 'token_id':'gateway-gui-owner'}
    if payload is None:
        tools = [{k:v for k,v in tool.items() if k!='scope'} for tool in service.tools.values() if service.permitted(principal, tool)]
        return {'tools':tools, 'count':len(tools)}
    if not isinstance(payload, dict) or set(payload)-{'name','arguments','idempotency_key','confirm'} or not {'name','arguments'}<=set(payload):
        raise GuiError(400, 'Typed tool name and arguments required')
    if not isinstance(payload['name'], str) or not isinstance(payload['arguments'], dict):
        raise GuiError(400, 'String tool name and object arguments required')
    tool = service.tools.get(payload['name'])
    if not tool:
        raise GuiError(404, 'Tool unavailable')
    if tool['annotations']['destructiveHint'] and payload.get('confirm') is not True:
        raise GuiError(409, 'Explicit write confirmation required')
    return service.call(principal, payload['name'], payload['arguments'], payload.get('idempotency_key'))
