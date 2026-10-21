"""Integration credentials exist only in temporary CI state, never production."""
import hashlib
import json


def configuration(root):
    principals={}
    for name,role in [('owner','admin'),('builder','worker'),('verifier','worker')]:
        principals[name]={'role':role,'projects':['demo'],'token_sha256':hashlib.sha256((name+'-integration-token').encode()).hexdigest()}
        if role=='worker':principals[name]['worker']=name
    path=root/'config.json';path.write_text(json.dumps({'schema':'openci.controller.v1','principals':principals}));path.chmod(0o600)
    return path


def task(name,image,pool):
    return {'id':name,'needs':[],'outputs':['result.json'],'image':image,'argv':['python3','/src/build.py'],'arch':'x86_64','pool':pool,'cpu':1,'memory_mb':128,'timeout':30,'attempts':2}
