"""All eleven component targets execute through the same native application router."""
import base64
import json
import hashlib
import secrets
import time
import os
import subprocess
import sys
from test_native_integration import NativeFixture,ROOT
from ziokt.application_router import ApplicationRouter
from ziokt.cli import write_exclusive,write_binary_exclusive
from ziokt.community import create_policy,RIGHTS
from ziokt.component_links import COMPONENTS
from ziokt.protocol import ProtocolError
from ziokt.security import sign


class ApplicationRouterTests(NativeFixture):
    def test_all_targets_execute_and_method_grants_are_enforced(self):
        signing=secrets.token_bytes(32);public=sign({},signing,'test')['public_key'];policy=create_policy(signing,'apps',{public:sorted(RIGHTS)})
        policy_file=self.base/'policy.json';write_exclusive(policy_file,policy)
        federation=self.base/'federation.json';write_exclusive(federation,self.federation)
        routes={};methods=['component.status','component.health','ano.evaluate','ano.laws','ano.calculate','ano.defence','vault.put','vault.get','vault.publish','tc16.run','tri.put','tri.get','tri.publish','package.build','package.verify','package.publish','sim.reminders.replace','sim.reminders.pull']
        for component in COMPONENTS-{'shadow6','corium','etp'}:
            directory=self.base/component;directory.mkdir(mode=0o700);vault=directory/'vault';vault.mkdir(mode=0o700)
            for name,key in [('signing',signing),('encryption',secrets.token_bytes(32)),('application',secrets.token_bytes(32))]:write_binary_exclusive(directory/(name+'.key'),key)
            config={'schema':'ziokt.companion-bridge.v1','application':component,'community_root':str(directory/'community'),'owner':public,'policy':str(policy_file),'signing_key':str(directory/'signing.key'),'encryption_key':str(directory/'encryption.key'),'application_key':str(directory/'application.key'),'vault_root':str(vault)}
            config_path=directory/'bridge.json';write_exclusive(config_path,config);routes[component]={'config':str(config_path),'methods':methods}
        for provider in self.providers:routes[provider['native_project']]={'federation_config':str(federation),'provider':provider['provider_id'],'methods':['status.get']}
        worker=self.base/'etp';worker.write_text('#!/usr/bin/env python3\nimport sys,json\nfor line in sys.stdin:\n r=json.loads(line)\n if r["method"]=="etp.shutdown":break\n result={"schema":"ziokt.etp-stats.v1","native":{"fixture":True},"fixture":True}\n print(json.dumps({"id":r["id"],"ok":True,"result":result}),flush=True)\n');worker.chmod(0o700)
        config=self.base/'etp.json';write_exclusive(config,{})
        routes['etp']={'binary':str(worker),'digest':'sha256:'+hashlib.sha256(worker.read_bytes()).hexdigest(),'config':str(config),'methods':['etp.stats','etp.health']}
        path=self.base/'router.json';write_exclusive(path,{'schema':'ziokt.application-router.v1','components':routes});router=ApplicationRouter(path);self.addCleanup(router.close)
        for component in sorted(COMPONENTS):
            result=router.call(component,'status.get' if component in {'shadow6','corium'} else 'etp.stats' if component=='etp' else 'component.status',{})
            if component in {'shadow6','corium'}:self.assertEqual(result['provider_id'],component+'-local')
            elif component=='etp':self.assertTrue(result['fixture'])
            else:self.assertEqual(result['application'],component)
        self.assertEqual(router.call('etp','etp.health',{'challenge':'b'*32})['checks']['external_peer'],'not_assessed')
        for component in ('ufs','dcpm'):
            health=router.call(component,'component.health',{'challenge':'c'*32})
            self.assertEqual(health['schema'],'ziokt.component-health.v1')
            self.assertEqual(health['checks']['community_database_and_identity'],'passed')
            self.assertEqual(health['checks']['standalone_service'],'not_assessed')
        self.assertEqual(router.call('zda','ano.evaluate',{'circuit':{'op':'merge','args':[True,False]}})['result'],'positive')
        gate=router.call('zda','ano.defence',{'evidence':{'signature':True,'authorized':None},'required':['signature','authorized']})
        self.assertEqual(gate['decision'],'hold');self.assertFalse(gate['cryptographic_proof'])
        from ziokt.ano import ZDANumber
        calculation={'kind':'zda','operation':'add','left':ZDANumber(1).document(),'right':ZDANumber(2).document()}
        self.assertEqual(router.call('zda','ano.calculate',calculation)['result'],ZDANumber(3).document())
        cpu=router.call('tc16','tc16.run',{'source':'int main() { return 65535 + 2; }','syntax':'tcc','cycles':1000});self.assertEqual(cpu['registers'][0],1)
        project=router.call('tri','tri.put',{'program':'HALT','state':{'from':'native'}})
        self.assertEqual(router.call('tri','tri.get',{'digest':project['digest']})['program'],'HALT')
        self.assertIn('event',router.call('tri','tri.publish',{'digest':project['digest']}))
        for component in ('safefs','ufs','dcpm','watchat','sim-manager'):
            obj=router.call(component,'vault.put',{'name':'artifact.txt','data_base64':base64.b64encode(b'private payload').decode()})
            self.assertEqual(base64.b64decode(router.call(component,'vault.get',{'digest':obj['digest']})['data_base64']),b'private payload')
            if component in {'ufs','dcpm'}:
                package=router.call(component,'package.build',{'name':'fixture','version':'1','files':{'artifact.txt':obj['digest']},'dependencies':[]})
                verified=router.call(component,'package.verify',{'digest':package['digest'],'authority':public})
                self.assertEqual(verified['files_verified'],1);self.assertFalse(verified['installation_authorized'])
                self.assertIn('event',router.call(component,'package.publish',{'digest':package['digest'],'authority':public}))
                with self.assertRaises(ProtocolError):router.call(component,'package.verify',{'digest':package['digest'],'authority':'0'*64})
        user='12345678-1234-1234-1234-123456789abc';items=[{'id':'a'*64,'due':int(time.time()*1000)+60000,'webhook':False}]
        first=router.call('sim-manager','sim.reminders.replace',{'user':user,'items':items})
        self.assertTrue(router.call('sim-manager','sim.reminders.replace',{'user':user,'items':items})['duplicate'])
        pulled=router.call('sim-manager','sim.reminders.pull',{'user':user});self.assertEqual(pulled['items'],items);self.assertEqual(pulled['event'],first['event'])
        for target,method,params in [('corium','operation.commit',{}),('sim-manager','tc16.run',{'source':'HALT','syntax':'assembly','cycles':2}),('unknown','component.status',{})]:
            with self.assertRaises(ProtocolError):router.call(target,method,params)

        # The same request contract is reachable through both real native CLIs.
        for entry in ([sys.executable,str(ROOT.parent/'Shadow6/CLI/shadow6.py'),'ziokt'],['bash',str(ROOT.parent/'Corium/corix_v108.sh'),'ziokt']):
            for target in sorted(COMPONENTS):
                method='status.get' if target in {'shadow6','corium'} else 'etp.stats' if target=='etp' else 'component.status'
                request=self.base/('request-'+target+'.json')
                if request.exists():request.unlink()
                write_exclusive(request,{'target':target,'method':method,'params':{}})
                result=subprocess.run([*entry,'companion','app','call','--bridge-config',str(path),'--request',str(request)],env={**os.environ,'PYTHONPATH':str(ROOT)},capture_output=True,text=True,timeout=15)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)

            request=self.base/'numeric-request.json'
            if request.exists():request.unlink()
            write_exclusive(request,{'target':'zda','method':'ano.calculate','params':calculation})
            result=subprocess.run([*entry,'companion','app','call','--bridge-config',str(path),'--request',str(request)],env={**os.environ,'PYTHONPATH':str(ROOT)},capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual(json.loads(result.stdout)['result'],ZDANumber(3).document())
