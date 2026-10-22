"""Domain-separated worker result statements; signatures attest identities, not work."""
import hashlib
from ziokt.protocol import ProtocolError
from ziokt.security import verify
from .state import Error,encoded,identifier

DOMAIN='OpenCI/worker-receipt/v1'


def statement(worker,assignment,result):
    identifier(worker)
    return {'schema':'openci.worker-receipt.v1','worker':worker,'pipeline':assignment['pipeline'],
            'task':assignment['task']['id'],'attempt':assignment['attempt'],'source':assignment['source'],
            'task_digest':'sha256:'+hashlib.sha256(encoded(assignment['task']).encode()).hexdigest(),
            'lease_digest':'sha256:'+hashlib.sha256(assignment['lease'].encode()).hexdigest(),'result':result}


def check(envelope,public,expected):
    try:actual=verify(envelope,public,DOMAIN,maximum=8192)
    except (ProtocolError,ValueError,TypeError):raise Error('WORKER_SIGNATURE_REJECTED','Worker result signature rejected',403) from None
    if actual!=expected:raise Error('WORKER_STATEMENT_MISMATCH','Worker signature does not bind the assigned input, lease and output',409)
    return actual
