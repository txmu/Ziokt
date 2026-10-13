"""Community materials and reviewed native actions retain original execution gates."""
from .artifacts import ArtifactStore
from .community import content_id
from .protocol import ProtocolError, encoded
from .security import sign


def materialize(community, manifest, store):
    """Hand immutable bytes to an operator-selected original artifact store.

    This is not package admission: native install must still verify the original
    publisher, signature, selector, ABI and permissions.
    """
    data = community.get_file(manifest)
    return {'artifact_digest': store.put(data), 'native_signature_verified': False}


def native_workflow(community, private, federation, journal, manifest, *, domain, object_key,
                    apply=False, expected_digest=None, confirmed=False, leadership=None, guard=None):
    if domain not in {'hosting', 'compute'} or federation.get('federation_id') != community.community_id:
        raise ProtocolError('SCOPE_MISMATCH', 'native job requires matching community federation scope')
    public = sign({}, private, 'test')['public_key']
    def admission():
        with community.lock:
            community._current(); community._member(public, domain)
            community._member(public, 'files')
        if guard: guard()
    admission()
    plan = journal.plan(manifest, federation)
    if not apply: return {'plan': plan, 'native_apply_required': True}
    if expected_digest != plan['plan_digest']:
        raise ProtocolError('STALE_PLAN', 'community native job differs from reviewed workflow')
    result = journal.apply(manifest['workflow_id'], federation, expected_digest, confirmed,
                           leadership=leadership, guard=admission)
    receipt = encoded(result)
    # Native committed status can still explicitly report application_ready=false.
    # Persist the original receipt, without claiming metadata is runtime health.
    with community.lock:
        admission()
        materials = community.put_file(receipt)
        community._member(public, 'files')
        receipt_key = 'receipt-'+content_id(receipt)[7:55]
        community.publish(private, 'files', receipt_key, {'name': manifest['workflow_id']+'.json', **materials})
        body = ({'job': manifest['workflow_id'], 'workflow_digest': expected_digest,
                 'result': 'ziokt://'+community.community_id+'/files/'+receipt_key} if domain == 'compute' else
                {'service': manifest['workflow_id'], 'workflow_digest': expected_digest,
                 'content': 'ziokt://'+community.community_id+'/files/'+receipt_key})
        event = community.publish(private, domain, object_key, body)
    return {'plan': result, 'receipt_event': event, 'materials': materials, 'runtime_ready': False}


def stage_package(community, package_key, store):
    """Retrieve package materials from community and stage to native artifact store.

    Verifies that package exists in community causal DAG, downloads complete CAS blob,
    and stages it into the local native ArtifactStore for execution verification.
    """
    state = community.view('packages', package_key)
    heads = set(state['heads'])
    active = [e for e in state['events'] if e['id'] in heads and not e['deleted']]
    if not active:
        raise ProtocolError('NOT_FOUND', f'package {package_key} not found')
    event = active[-1]
    body = event['body']
    manifest = {'chunks': body['chunks'], 'size': body['size'], 'digest': body['digest']}
    materialized = materialize(community, manifest, store)
    return {
        'package_key': package_key,
        'event_id': event['id'],
        'author': event['author'],
        'name': body['name'],
        'version': body['version'],
        'native_kind': body['native_kind'],
        'native_signature': body['native_signature'],
        'artifact_digest': materialized['artifact_digest'],
        'native_signature_verified': False
    }
