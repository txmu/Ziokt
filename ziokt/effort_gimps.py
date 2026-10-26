"""Public GIMPS workers delegate native authority and verification to Corium."""
import hashlib
import secrets
import time

from .effort_web import EffortPool
from .protocol import ProtocolError, encoded, strict_json
from .runtime_policy import require_network


class GimpsPool(EffortPool):
    def issue(self):
        require_network()
        with self.lock:
            pending=self.db.execute('SELECT problem,operation FROM submissions WHERE result IS NULL LIMIT 1').fetchone()
            if pending:self.recover(pending[0],pending[1])
            now=time.time()
            self.jobs={token:job for token,job in self.jobs.items() if job['expires']>now}
            if len(self.jobs)>=128:raise ProtocolError('BACKPRESSURE','GIMPS worker job budget exhausted')
            job=self.client.call('compute.challenge',{'engine':'gimps'})
            if (not isinstance(job,dict) or job.get('schema')!='corium.gimps-challenge.v1' or
                    job.get('submitter_id')!=self.submitter or self.expected_network and job.get('network_id')!=self.expected_network):
                raise ProtocolError('NETWORK_MISMATCH','native GIMPS node and signer must match configuration')
            if job.get('available') is not True:return {'available':False,'engine':'gimps','reason':job.get('reason','no-native-task'),'retry_ms':5000}
            p=job.get('exponent')
            if (type(p) is not int or not 2<=p<=4096 or job.get('problem_id')!=str(p) or
                    job.get('proof_schema')!='corium.gimps-proof.v2' or job.get('method')!='lucas-lehmer' or
                    not isinstance(job.get('engine_id'),str) or len(job['engine_id'])>128):
                raise ProtocolError('INVALID_JOB','bounded native GIMPS task required')
            job=dict(job,engine='gimps',token=secrets.token_hex(24),expires=int(now)+90)
            self.jobs[job['token']]=job
            return job

    def submit(self,token,proof):
        require_network()
        with self.lock:
            job=self.jobs.get(token) if isinstance(token,str) else None
            if not job or job['expires']<=time.time():raise ProtocolError('STALE_JOB','native GIMPS job expired')
            if (not isinstance(proof,dict) or set(proof)!={'schema','exponent','method','residue','is_prime','iterations'} or
                    proof.get('schema')!='corium.gimps-proof.v2' or proof.get('exponent')!=job['exponent'] or
                    proof.get('method')!='lucas-lehmer' or type(proof.get('residue')) is not str or len(proof['residue'])>1234 or
                    len(encoded(proof))>6144):raise ProtocolError('INVALID_PROOF','native portable GIMPS proof required')
            # Reuse Corium's exact algorithm, also embedded into its standalone monolith.
            from ._runtime import _native_gimps
            residue=proof['residue']
            if (not residue.isascii() or not residue.isdecimal() or str(int(residue))!=residue or
                    type(proof['is_prime']) is not bool or type(proof['iterations']) is not int or
                    proof['iterations']!=job['exponent']-2):raise ProtocolError('INVALID_PROOF','canonical GIMPS result required')
            valid,expected=_native_gimps.lucas_lehmer_verify(job['exponent'],int(residue))
            if not valid or proof['is_prime']!=(expected==0):raise ProtocolError('INVALID_PROOF','Corium Lucas-Lehmer recomputation failed')
            problem=job['engine_id']+':'+job['problem_id']
            previous=self.db.execute('SELECT operation,nonce,result FROM submissions WHERE problem=?',(problem,)).fetchone()
            if previous and previous[2]:return dict(strict_json(previous[2]),duplicate=True)
            if previous:result=self.recover(problem,previous[0])
            else:
                operation='web-gimps-'+hashlib.sha256((job['network_id']+problem+self.submitter).encode()).hexdigest()[:40]+'-'+secrets.token_hex(4)
                plan=self.client.call('operation.prepare',{'operation_id':operation,'action':'compute.submit','resource':'compute:'+job['engine_id'],
                    'arguments':{'engine_id':job['engine_id'],'problem_id':job['problem_id'],'proof_data':proof},'expected_revision':None})
                with self.db:self.db.execute('INSERT INTO submissions VALUES (?,?,?,NULL)',(problem,operation,encoded(proof).decode()))
                result=self.client.call('operation.commit',{'operation_id':operation,'plan_digest':plan['plan_digest']})
            if result.get('state')!='committed':raise ProtocolError('RESULT_UNKNOWN','native GIMPS submission awaits reconciliation')
            receipt={'accepted':True,'engine':'gimps','phase':result['result']['phase'],'transaction_hash':result['result']['transaction_hash'],'confirmed':False}
            with self.db:self.db.execute('UPDATE submissions SET result=? WHERE problem=?',(encoded(receipt),problem))
            return dict(receipt,duplicate=False)
