"""Call an explicitly pinned native ETP compiler; never reimplement its frontend."""
import base64
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
from .protocol import ProtocolError,encoded,secure_read,strict_json
from .tc16_spec import unpack,execute_package


def compile_native(source,settings):
    if not isinstance(source,str) or not 1<=len(source.encode())<=65536:raise ProtocolError('ETP_LEGACY_SOURCE_LIMIT','Bounded Legacy UTF-8 source required')
    if not isinstance(settings,dict) or set(settings)!={'binary','sha256'}:raise ProtocolError('ETP_LEGACY_NOT_CONFIGURED','Owner-approved native compiler required')
    binary=secure_read(settings['binary'],128*1024*1024,private=False)
    if 'sha256:'+hashlib.sha256(binary).hexdigest()!=settings['sha256']:raise ProtocolError('ARTIFACT_DIGEST_MISMATCH','Native compiler differs from approved digest')
    with tempfile.TemporaryDirectory(prefix='etp-legacy-compiler-') as area:
        snapshot=Path(area)/'compiler';snapshot.write_bytes(binary);snapshot.chmod(0o700)
        try:process=subprocess.run([str(snapshot)],input=encoded({'source':source})+b'\n',stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=10,env={'PATH':os.defpath,'HOME':area,'LANG':'C'})
        except (OSError,subprocess.TimeoutExpired):raise ProtocolError('ETP_LEGACY_COMPILER_UNAVAILABLE','Native compiler failed or timed out') from None
    if process.returncode or not 1<=len(process.stdout)<=196608:raise ProtocolError('ETP_LEGACY_COMPILER_FAILED','Native compiler returned invalid output or failed')
    frame=strict_json(process.stdout,196608,string_limit=100000)
    if not isinstance(frame,dict) or type(frame.get('ok')) is not bool:raise ProtocolError('ETP_LEGACY_RESPONSE','Typed native response required')
    if frame['ok'] is False:
        error=frame.get('error',{})
        message=error.get('message','Native source compilation rejected') if isinstance(error,dict) else 'Native source compilation rejected'
        raise ProtocolError('ETP_LEGACY_COMPILE',str(message)[:1024])
    value=frame.get('result');fields={'schema','semantic_profile','source_sha256','compiler','package','debug','legacy_result'}
    if not isinstance(value,dict) or set(value)!=fields or value['schema']!='etp.legacy-compiled.v1' or value['semantic_profile']!='etp-legacy-pure-return-v1' or value['compiler']!='etp-native-legacy-unified-v1' or value['source_sha256']!=hashlib.sha256(source.encode()).hexdigest():raise ProtocolError('ETP_LEGACY_RESPONSE','Versioned native source and compiler identity mismatch')
    if type(value['legacy_result']) is not int or not 0<=value['legacy_result']<=65535 or not isinstance(value['package'],str) or len(value['package'])>94000:raise ProtocolError('ETP_LEGACY_RESPONSE','Invalid return value or package budget')
    try:blob=base64.b64decode(value['package'],validate=True)
    except ValueError:raise ProtocolError('ETP_LEGACY_RESPONSE','Invalid package encoding') from None
    metadata,code=unpack(blob,{'tc16-unified-v1'})
    if metadata['capability_profile']!='pure-v1' or metadata['entrypoint']!=0:raise ProtocolError('ETP_LEGACY_CAPABILITY','Native pure profile required')
    actual=execute_package(blob,10000)
    if actual['exception'] is not None or not actual['halted'] or actual['registers'][0]!=value['legacy_result']:raise ProtocolError('ETP_LEGACY_DIVERGENCE','Native reference result differs from Unified execution')
    debug=value['debug']
    if not isinstance(debug,dict) or set(debug)!={'functions'} or not isinstance(debug['functions'],dict) or not 1<=len(debug['functions'])<=4096 or any(not isinstance(name,str) or not name or type(address) is not int or not 0<=address<len(code) for name,address in debug['functions'].items()):raise ProtocolError('ETP_LEGACY_DEBUG','Native function symbol table rejected')
    return {**value,'execution_authorized':False,'legacy_application_compatibility_verified':False}
