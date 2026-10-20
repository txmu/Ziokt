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
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--url',required=True);parser.add_argument('--token-file');parser.add_argument('--ca');parser.add_argument('--upload-id');parser.add_argument('--download-id');parser.add_argument('--output');parser.add_argument('--max-segments',type=int);parser.add_argument('file',nargs='?')
    args=parser.parse_args();peer={'url':args.url,'token':secure_read(args.token_file,256).decode().strip() if args.token_file else '', 'ca':args.ca}
    if args.download_id:
        if args.file or not args.output:parser.error('--download-id requires --output and no upload file')
        from .content_download import download_file
        result=download_file(peer,args.download_id,args.output,max_segments=args.max_segments)
    else:
        if not args.file or not args.token_file or args.output or args.max_segments:parser.error('upload requires file and --token-file')
        result=upload(peer,args.file,args.upload_id)
    print(json.dumps(result))


if __name__=='__main__':main()
