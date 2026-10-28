"""Supervise a node-local RetroShare service and private API/profile credentials."""
import argparse
import base64
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import threading
import time
import urllib.request
from .protocol import secure_read

def post(port,path,arguments,auth=None):
    headers={'Content-Type':'application/json'}
    if auth:headers['Authorization']='Basic '+base64.b64encode((auth['username']+':'+auth['password']).encode()).decode()
    request=urllib.request.Request('http://127.0.0.1:'+str(port)+'/'+path,data=json.dumps(arguments).encode(),headers=headers)
    with urllib.request.urlopen(request,timeout=30) as response:return json.loads(response.read(262145))

def private_json(path,value):
    temporary=path.with_suffix('.new');fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as stream:json.dump(value,stream);stream.write('\n')
    os.replace(temporary,path)

def run(root,binary,api_port,p2p_port):
    root=Path(root).resolve();root.mkdir(parents=True,mode=0o700,exist_ok=True);root.chmod(0o700)
    state=root/'node.json';auth_file=root/'api-auth.json'
    if state.exists():config=json.loads(secure_read(state,16384))
    else:
        config={'label':'Ziokt-'+secrets.token_hex(6),'profile_password':secrets.token_urlsafe(40),'api_user':'ziokt','api_password':secrets.token_urlsafe(40),'location':None}
        private_json(state,config)
    auth={'username':config['api_user'],'password':config['api_password']};private_json(auth_file,auth)
    log=root/'native.log';fd=os.open(log,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
    done=threading.Event()
    child=subprocess.Popen([binary,'--base-dir',str(root/'profile'),'--jsonApiPort',str(api_port),'--jsonApiBindAddress','127.0.0.1','--port',str(p2p_port),'-s'],stdin=subprocess.DEVNULL,stdout=fd,stderr=fd)
    os.close(fd)
    def stop(*_):done.set()
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,stop)
    try:
        deadline=time.monotonic()+45
        while True:
            if child.poll() is not None:raise RuntimeError('RetroShare native process exited; inspect private native.log')
            try:
                if post(api_port,'rsLoginHelper/isLoggedIn',{}).get('retval') is not None:break
            except (OSError,ValueError):pass
            if time.monotonic()>deadline:raise RuntimeError('RetroShare loopback API startup timed out')
            if done.wait(.25):return
        if not config.get('location'):
            created=post(api_port,'rsLoginHelper/createLocationV2',{'locationId':'0'*32,'pgpId':'0'*16,'locationName':config['label'],'pgpName':config['label'],'password':config['profile_password'],'apiUser':auth['username'],'apiPass':auth['password']})
            location=created.get('locationId')
            if not isinstance(location,str) or location=='0'*32:raise RuntimeError('RetroShare profile creation failed; inspect native profile state')
            config['location']=location;private_json(state,config)
        if not post(api_port,'rsLoginHelper/isLoggedIn',{}).get('retval'):
            result=post(api_port,'rsLoginHelper/attemptLogin',{'account':config['location'],'password':config['profile_password'],'apiUser':auth['username'],'apiPass':auth['password']})
            if result.get('retval')!=0:raise RuntimeError('RetroShare profile login failed')
        # No friend import, certificate publication or directory sharing here.
        print(json.dumps({'schema':'ziokt.retroshare-node.v1','location':config['location'],'api_port':api_port,'api_loopback_only':True}),flush=True)
        while not done.wait(1):
            if child.poll() is not None:raise RuntimeError('RetroShare native service stopped')
    finally:
        if child.poll() is None:
            child.terminate()
            try:child.wait(timeout=15)
            except subprocess.TimeoutExpired:child.kill();child.wait()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);parser.add_argument('--binary',default='/usr/bin/retroshare-service');parser.add_argument('--api-port',type=int,default=9092);parser.add_argument('--p2p-port',type=int,default=60850);args=parser.parse_args()
    if not all(1024<=port<=65535 for port in (args.api_port,args.p2p_port)) or args.api_port==args.p2p_port:raise ValueError('distinct unprivileged RetroShare ports required')
    run(args.root,args.binary,args.api_port,args.p2p_port)
if __name__=='__main__':main()
