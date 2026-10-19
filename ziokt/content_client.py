"""Streaming local file upload client; memory usage is bounded by chunk size.

python -m ziokt.content_client --url https://node --token-file /private/token file
No credentials in argv or URLs. Server endpoint is chosen by the local operator.
"""
import argparse
import base64
import hashlib
import json
import mimetypes
from pathlib import Path
import secrets
from .content_server import remote
from .protocol import secure_read


def upload(peer,path,upload_id=None):
    path=Path(path)
    with path.open('rb') as stream:digest='sha256:'+hashlib.file_digest(stream,'sha256').hexdigest()
    upload_id=upload_id or secrets.token_hex(24)
    size=path.stat().st_size;mime=mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
    def call(op,args):return remote(peer,{'operation':op,'arguments':args})
    state=call('content.upload.begin',{'upload':upload_id,'size':size,'digest':digest,'mime':mime})
    if state['state']=='complete':return call('content.upload.finish',{'upload':upload_id})
    with path.open('rb') as stream:
        position=state['next_missing'];stream.seek(position*16384)
        while True:
            part=stream.read(16384)
            if not part:break
            call('content.upload.put',{'upload':upload_id,'position':position,'data':base64.b64encode(part).decode()});position+=1
    return call('content.upload.finish',{'upload':upload_id})


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--url',required=True);parser.add_argument('--token-file',required=True);parser.add_argument('--ca');parser.add_argument('--upload-id');parser.add_argument('file')
    args=parser.parse_args()
    print(json.dumps(upload({'url':args.url,'token':secure_read(args.token_file,256).decode().strip(),'ca':args.ca},args.file,args.upload_id)))


if __name__=='__main__':main()
