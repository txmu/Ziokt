"""Publish through the existing native DHT and durable native operation journal."""
import base64
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
from .config import fingerprint,load
from .client import NativeClient
from .dna_protocol import canonical,require
from .protocol import secure_read,strict_json


class Publisher:
    def __init__(self,root,config):
        self.root=Path(root)
        self.gateway=strict_json(secure_read(config['gateway']))
        federation=load(config['federation'])
        require(federation['enabled'] is True,'enabled native federation required')
        provider=next(p for p in federation['providers'] if p['native_project']=='corium'
                      and p['network_id']==self.gateway['network']
                      and Path(p['state_root'])==Path(self.gateway['state_root']))
        self.client=NativeClient(federation['federation_id'],provider)

    def operation(self,publication,kind,document):
        operation='protocol-'+publication[:48]
        action='content.publish';resource='content:'+self.gateway['network']
        title=('ZDNS RNA publication '+publication if kind=='zdns' else 'OpenCI evidence commitment '+document['commitment_hash'])
        # RNA discovery is anchored as content. It must never replace a domain's
        # existing website/service manifest in the NNS target register.
        arguments={'text':title,'data_base64':base64.b64encode(canonical(document)).decode(),
                   'content_type':'application/json'}
        plan=self.client.call('operation.prepare',{'operation_id':operation,'action':action,
                              'resource':resource,'arguments':arguments,'expected_revision':None})
        result=self.client.call('operation.reconcile',{'operation_id':operation})
        if result.get('state')=='prepared':
            result=self.client.call('operation.commit',{'operation_id':operation,'plan_digest':plan['plan_digest']})
        require(result.get('state')=='committed','native journal has not committed publication')
        receipt=result['result']
        return receipt['transaction_hash']

    def inclusion(self,transaction):
        database=Path(self.gateway['state_root'])/'var/lib/corix/networks'/self.gateway['network']/'blockchain/chain.db'
        db=sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True,timeout=3)
        try:
            row=db.execute('SELECT b.height,b.hash FROM transactions t JOIN blocks b ON b.height=t.block_height WHERE t.hash=? AND EXISTS(SELECT 1 FROM json_each(b.transactions) WHERE value=t.hash)',(transaction,)).fetchone()
        finally:db.close()
        return {'native_transaction':transaction,'chain_registration':'confirmed' if row else 'submitted',
                'inclusion':{'height':row[0],'block_hash':row[1]} if row else None,
                'consensus_reward_claimed':False}

    def publish(self,publication,kind,document,expired=False):
        # Hash-addressed public material excludes private OpenCI result contents.
        raw=canonical(document)
        require(hashlib.sha256(raw).hexdigest()==publication,'publication content address')
        if expired:
            return {'broadcast':'expired','chain_registration':'not_submitted','reason':'RNA_VALIDITY_EXPIRED'}
        directory=self.root/'published';directory.mkdir(mode=0o700,exist_ok=True)
        path=directory/(publication+'.json')
        try:fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
        except FileExistsError:
            require(secure_read(path,65536)==raw,'immutable publication changed')
        else:
            with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
        require(fingerprint(Path(self.gateway['corix']))==self.gateway['corix_digest'],'native publisher pin changed')
        helper=Path(__file__).resolve().parents[1]/'gateway/native.sh'
        argv=['bash',str(helper),self.gateway['corix'],self.gateway['state_root'],self.gateway['network'],
              'protocol-publish',publication,str(path)]
        process=subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,start_new_session=True)
        try:output,_=process.communicate(timeout=25)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGKILL);process.communicate()
            output=b'{}'
        broadcast=json.loads(output) if len(output)<=4096 else {}
        # Registration has its own native durable ID; DHT retries cannot create
        # another transaction, and a peer acknowledgement cannot imply inclusion.
        transaction=self.operation(publication,kind,document)
        return {'broadcast':broadcast.get('broadcast','pending'),'anchor_type':'native-content-commitment','nns_target_changed':False,**self.inclusion(transaction)}
