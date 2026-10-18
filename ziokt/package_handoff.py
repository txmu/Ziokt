"""Versioned DCPM -> native Shadow6 handoff without re-signing or execution.

A transport package contains exactly shadow6/package.zip, an independently
signed Shadow6 package. Both trust decisions are required. Generic DCPM files
are deliberately rejected: changing their format cannot manufacture native trust.
"""
import argparse
import hashlib
from pathlib import Path
import tempfile

from .artifacts import ArtifactStore
from .protocol import ProtocolError, encoded, secure_read, strict_json
from .ufsdcpm import read_package, verify_reference_package, MAX_REFERENCE_FILE

NATIVE_PATH = 'shadow6/package.zip'


def stage_native_package(blob, publisher, native, trust_file, artifacts, package_root, *, reference_store=None):
    """Local operator adapter; install/activate still use native prepare/commit.

    ``native`` is the installed shadow6_pkg module, never a remote-supplied path.
    Dependencies are checked against reverified active native app packages. DCPM
    v1 dependencies have names only; they do not imply version constraints.
    """
    envelope = strict_json(blob,6*1024*1024)
    schema = envelope.get('manifest',{}).get('payload',{}).get('schema') if isinstance(envelope,dict) else None
    source_objects = []
    if schema == 'ziokt.dcpm-package.v2':
        if reference_store is None:
            raise ProtocolError('REFERENCE_STORE_REQUIRED','v2 admission requires the authenticated source object store')
        report = verify_reference_package(reference_store,blob,publisher)
        manifest = report['manifest']
        if len(manifest['files']) != 1 or manifest['files'][0]['path'] != NATIVE_PATH:
            raise ProtocolError('PACKAGE_FORMAT','exact independently signed native archive required')
        entry = manifest['files'][0]
        if entry['size'] > MAX_REFERENCE_FILE:
            raise ProtocolError('PACKAGE_LIMIT','native archive exceeds artifact admission quota')
        archive = bytearray()
        for chunk in reference_store.stream(entry['object']):
            archive.extend(chunk)
            if len(archive)>MAX_REFERENCE_FILE:raise ProtocolError('PACKAGE_LIMIT','native archive quota exceeded')
        files = {NATIVE_PATH:bytes(archive)}
        source_objects = [entry['object']]
    else:
        manifest, files = read_package(blob, publisher)
    if set(files) != {NATIVE_PATH}:
        raise ProtocolError('PACKAGE_FORMAT', 'adapter v1 requires exactly one independently signed native archive')
    archive = files[NATIVE_PATH]
    package_root = Path(package_root)
    # Reject unresolved dependencies before publishing a native artifact.
    for dependency in manifest['dependencies']:
        if not native.IDENTITY.fullmatch(dependency):
            raise ProtocolError('DEPENDENCY_INCOMPATIBLE', 'DCPM dependency is not a native package identity')
        base = package_root/'app'/dependency
        try:
            pointer = native.strict_json(native.secure_read(base/'active.json',4096))
            if set(pointer) != {'schema_version','version'} or pointer['schema_version'] != 1 or not native.VERSION.fullmatch(pointer['version']):
                raise ValueError('invalid active pointer')
            active, source = native.verify_package(base/'versions'/pointer['version'],Path(trust_file))
            source.close()
            if (active['kind'],active['id'],active['version']) != ('app',dependency,pointer['version']):
                raise ValueError('dependency identity differs')
        except (OSError,ValueError,TypeError):
            raise ProtocolError('DEPENDENCY_MISSING', 'verified active native dependency required: '+dependency)
    with tempfile.TemporaryDirectory(prefix='ziokt-native-admission-') as directory:
        path = Path(directory)/'package.zip';path.write_bytes(archive);path.chmod(0o600)
        signed, source = native.verify_package(path,Path(trust_file))
        source.close()
    if (manifest['name'],manifest['version']) != (signed['id'],signed['version']):
        raise ProtocolError('PACKAGE_IDENTITY_MISMATCH', 'DCPM and native package name/version differ')
    installed = package_root/signed['kind']/signed['id']/'versions'/signed['version']
    if installed.exists():
        prior, source = native.verify_package(installed,Path(trust_file));source.close()
        if prior != signed:
            raise ProtocolError('VERSION_CONFLICT', 'native version already has different signed content')
    artifact = artifacts.put(archive)
    provenance = {
        'schema':'ziokt.dcpm-shadow6-handoff.v2' if source_objects else 'ziokt.dcpm-shadow6-handoff.v1',
        'source_objects':source_objects,
        'source_digest':'sha256:'+hashlib.sha256(blob).hexdigest(),
        'source_publisher':publisher,'source_signature':verify_envelope(blob),
        'artifact_digest':artifact,'native_signer':signed['signer'],
        'native_manifest_digest':'sha256:'+hashlib.sha256(native.canonical(signed)).hexdigest(),
        'selector':signed['kind']+'/'+signed['id']+'@'+signed['version'],
        'dependencies':manifest['dependencies'],
        'verification':'independent-dcpm-and-native-signatures',
        'installation_authorized':False,'execution_authorized':False,
        'installed':False,'activated':False,'service_health':'not-observed',
    }
    # Keep the original signed envelope for repeatable source verification.
    provenance['source_artifact'] = artifacts.put(blob)
    provenance['receipt_digest'] = artifacts.put(encoded(provenance))
    return provenance


def verify_envelope(blob):
    from .protocol import strict_json
    return strict_json(blob,6*1024*1024)['manifest']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package',required=True,type=Path)
    parser.add_argument('--publisher',required=True)
    parser.add_argument('--shadow6-root',required=True,type=Path)
    parser.add_argument('--trust-file',required=True,type=Path)
    parser.add_argument('--artifact-root',required=True,type=Path)
    parser.add_argument('--package-root',required=True,type=Path)
    parser.add_argument('--reference-vault',type=Path)
    parser.add_argument('--reference-key-file',type=Path)
    parser.add_argument('--reference-app',choices=['dcpm','ufs'],default='dcpm')
    args=parser.parse_args()
    import sys
    sys.path.insert(0,str(args.shadow6_root/'Package-Manager'))
    import shadow6_pkg
    from .safefs import Vault
    from .chunkstore import ChunkStore
    store=None
    try:
        if bool(args.reference_vault)!=bool(args.reference_key_file):raise ValueError('both reference vault and private key file are required')
        if args.reference_vault:store=ChunkStore(Vault(args.reference_vault,args.reference_app,secure_read(args.reference_key_file,32)))
        receipt=stage_native_package(secure_read(args.package,6*1024*1024),args.publisher,shadow6_pkg,args.trust_file,ArtifactStore(args.artifact_root),args.package_root,reference_store=store)
    finally:
        if store:store.close()
    print(encoded(receipt).decode())


if __name__=='__main__':main()


def stage_bridge_package(settings, bridge, digest, authority):
    """Admit a v1/v2 envelope from an authenticated source bridge into pinned native storage."""
    from .safefs import Vault
    from .chunkstore import ChunkStore
    native=load_native_module(settings)
    vault=Vault(bridge.vault_root,bridge.app,bridge.appkey);store=ChunkStore(vault)
    try:
        blob=vault.get(digest)[1]
        return stage_native_package(blob,authority,native,settings['trust_file'],ArtifactStore(settings['artifact_root']),settings['package_root'],reference_store=store)
    finally:store.close()


def update_native_signer(settings, signer=None, public_key=None, decision=None):
    """Owner-approved, atomic native signer allowlist; no signer is trusted by default."""
    import json
    import os
    import re
    trust=Path(settings['trust_file']);document=strict_json(secure_read(trust,1048576))
    if set(document)!={'schema_version','signers'} or document['schema_version']!=1 or not isinstance(document['signers'],dict):
        raise ProtocolError('INVALID_TRUST','native trust store schema invalid')
    if decision is None:return document
    if not isinstance(signer,str) or not re.fullmatch(r'[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?',signer):
        raise ProtocolError('INVALID_SIGNER','bounded native signer name required')
    if decision=='approve':
        if not isinstance(public_key,str) or not re.fullmatch('[a-f0-9]{64}',public_key):raise ProtocolError('INVALID_SIGNER','Ed25519 public key required')
        old=document['signers'].get(signer)
        if old and old!=public_key:raise ProtocolError('SIGNER_CONFLICT','revoke the existing key before replacing it')
        document['signers'][signer]=public_key
    elif decision=='revoke':document['signers'].pop(signer,None)
    else:raise ProtocolError('INVALID_DECISION','approve or revoke required')
    if len(document['signers'])>256:raise ProtocolError('SIGNER_LIMIT','native signer quota exceeded')
    with tempfile.NamedTemporaryFile(dir=trust.parent,prefix='.native-trust-',delete=False) as f:
        temporary=Path(f.name);f.write(encoded(document));f.flush();os.fsync(f.fileno())
    try:temporary.chmod(0o600);os.replace(temporary,trust)
    finally:temporary.unlink(missing_ok=True)
    return {'signer':signer,'decision':decision,'trusted_signers':len(document['signers']),'installation_authorized':False}


def load_native_module(settings):
    import types
    required={'module','module_digest','trust_file','artifact_root','package_root'}
    if not isinstance(settings,dict) or not required<=set(settings) or set(settings)-required-{'native_config'}:
        raise ProtocolError('NATIVE_ADMISSION_UNCONFIGURED','explicit native admission paths and pinned module required')
    source=secure_read(settings['module'],2*1024*1024,private=False)
    if 'sha256:'+hashlib.sha256(source).hexdigest()!=settings['module_digest']:
        raise ProtocolError('NATIVE_ADMISSION_CHANGED','native admission module digest changed')
    native=types.ModuleType('ziokt_native_package_manager');native.__file__=settings['module']
    exec(compile(source,settings['module'],'exec'),native.__dict__)
    return native


def approve_native_admission(settings, receipt_digest, selector):
    native=load_native_module(settings);artifacts=ArtifactStore(settings['artifact_root'])
    receipt=strict_json(artifacts.get(receipt_digest))
    if receipt.get('selector')!=selector or receipt.get('verification')!='independent-dcpm-and-native-signatures':
        raise ProtocolError('INVALID_ADMISSION','exact staged receipt and selector required')
    archive=artifacts.get(receipt['artifact_digest'])
    with tempfile.TemporaryDirectory(prefix='ziokt-native-approval-') as directory:
        path=Path(directory)/'package.zip';path.write_bytes(archive);path.chmod(0o600)
        manifest,source=native.verify_package(path,Path(settings['trust_file']));source.close()
    if manifest['kind']+'/'+manifest['id']+'@'+manifest['version']!=selector:
        raise ProtocolError('INVALID_ADMISSION','native selector mismatch')
    config_path=Path(settings['native_config']);config=strict_json(secure_read(config_path))
    resources=set(config.get('allowed_resources',[]));resources.add(selector)
    if len(resources)>256:raise ProtocolError('ADMISSION_LIMIT','native resource allowlist limit exceeded')
    config.update(package_root=settings['package_root'],package_trust_file=settings['trust_file'],artifact_root=settings['artifact_root'],allow_mutations=True,allowed_resources=sorted(resources),allowed_operations=sorted(set(config.get('allowed_operations',[]))|{'package.install','package.activate'}))
    write_private_json(config_path,config)
    return {'selector':selector,'admission_approved':True,'installed':False,'activated':False}


def write_private_json(path, value):
    import os
    with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.native-config-',delete=False) as stream:
        temporary=Path(stream.name);stream.write(encoded(value));stream.flush();os.fsync(stream.fileno())
    try:temporary.chmod(0o600);os.replace(temporary,path)
    finally:temporary.unlink(missing_ok=True)
