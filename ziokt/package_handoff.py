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
from .protocol import ProtocolError, encoded, secure_read
from .ufsdcpm import read_package

NATIVE_PATH = 'shadow6/package.zip'


def stage_native_package(blob, publisher, native, trust_file, artifacts, package_root):
    """Local operator adapter; install/activate still use native prepare/commit.

    ``native`` is the installed shadow6_pkg module, never a remote-supplied path.
    Dependencies are checked against reverified active native app packages. DCPM
    v1 dependencies have names only; they do not imply version constraints.
    """
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
        'schema':'ziokt.dcpm-shadow6-handoff.v1',
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
    args=parser.parse_args()
    import sys
    sys.path.insert(0,str(args.shadow6_root/'Package-Manager'))
    import shadow6_pkg
    receipt=stage_native_package(secure_read(args.package,6*1024*1024),args.publisher,shadow6_pkg,args.trust_file,ArtifactStore(args.artifact_root),args.package_root)
    print(encoded(receipt).decode())


if __name__=='__main__':main()
