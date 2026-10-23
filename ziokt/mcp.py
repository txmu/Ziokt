"""Scoped MCP 2026-07-28 / 2025-11-25 bridge over existing native contracts.

No command strings, arbitrary URLs, SQL, or host file paths are accepted as tools.
"""
import base64
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import re
import secrets
import sys
import threading
import time
from urllib.parse import parse_qs, quote, urlencode, urlsplit
from .gateway_store import database, encoded
from .mcp_schemas import BRIDGE, ETP
from .gateway import Server, unique, read_token
from .protocol import ProtocolError, secure_read, strict_json

LATEST='2026-07-28'
VERSIONS=(LATEST,'2025-11-25','2025-06-18','2025-03-26')
BRIDGE_READ={'package.verify.references','object.status','object.reference','object.chunk.get','component.status','component.health','ano.laws','ano.calculate','ano.defence','ano.evaluate','vault.get','tri.get','package.verify','sim.reminders.pull','chat.pull'}
BRIDGE_WRITE={'naming.publish','package.release.references','package.build.references','object.begin','object.chunk.put','object.finish','object.abort','object.release','object.gc','file.read','safefs.read','tc16.run','vault.put','vault.publish','tri.put','tri.publish','package.build','package.publish','sim.reminders.replace','component.send','component.receive','file.publish','safefs.publish','chat.append','chat.ack'}
READ_NATIVE={'privacy.status','privacy.review.list','privacy.review.get','zkn.shield.notes','zkn.shield.images','capabilities.get','status.get','objects.list','events.list','content.get','governance.fact','zkt.status','zkt.account','identity.fact','zkn.list','zkn.fact','zkc.list','zkc.fact','service.binding','compute.challenge','operation.status'}
log=logging.getLogger(__name__)


def schema(properties=None,required=()):
    return {'type':'object','properties':properties or {},'required':sorted(required),'additionalProperties':False}


def _validate_health(result,component,challenge,*,native_etp=False):
    expected={'pinned_native_process_rpc':'passed','native_engine_stats':'passed','external_peer':'not_assessed'} if native_etp else None
    now=time.time_ns()//1_000_000
    if (not isinstance(result,dict) or set(result)!={'schema','component','challenge','observed_at_ms','checks'} or
            result['schema']!='ziokt.component-health.v1' or result['component']!=component or
            result['challenge']!=challenge or type(result['observed_at_ms']) is not int or
            abs(now-result['observed_at_ms'])>5000 or not isinstance(result['checks'],dict)):
        raise ProtocolError('INVALID_HEALTH_PROOF','fresh component health challenge required')
    if native_etp and result['checks']!=expected:
        raise ProtocolError('INVALID_HEALTH_PROOF','native ETP stats checks required')
    if not native_etp:
        checks=result['checks']
        if (set(checks)!={'application_bridge','community_database_and_identity','vault_configuration','standalone_service','external_peer'} or
                checks['application_bridge']!='passed' or checks['community_database_and_identity']!='passed' or
                checks['vault_configuration'] not in {'configured','not_configured'} or
                checks['standalone_service']!='not_assessed' or checks['external_peer']!='not_assessed'):
            raise ProtocolError('INVALID_HEALTH_PROOF','scoped application bridge checks required')
    return result
STRING={'type':'string','maxLength':65536}
PARAMS={'type':'object','maxProperties':64}
TELEGRAM_INBOX_MAX_HISTORY=2000


def ensure_telegram_schema(db):
    db.executescript('''
      CREATE TABLE IF NOT EXISTS telegram_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS telegram_inbox (
        update_id INTEGER PRIMARY KEY, chat_id TEXT NOT NULL, user_id TEXT NOT NULL,
        message_id INTEGER NOT NULL, text TEXT NOT NULL, payload BLOB NOT NULL,
        received_at INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
        received_at_ms INTEGER NOT NULL DEFAULT 0,
        last_accessed_at_ms INTEGER NOT NULL DEFAULT 0,
        finished_at_ms INTEGER,
        reply_duration_ms INTEGER,
        processing_duration_ms INTEGER);
      CREATE TABLE IF NOT EXISTS telegram_confirmations (
        code_hash TEXT PRIMARY KEY, update_id INTEGER NOT NULL, chat_id TEXT NOT NULL,
        user_id TEXT NOT NULL, tool TEXT NOT NULL, arguments BLOB NOT NULL,
        created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
        state TEXT NOT NULL, result BLOB);
    ''')
    columns={row[1] for row in db.execute('PRAGMA table_info(telegram_inbox)')}
    additions={
        'received_at_ms':'INTEGER NOT NULL DEFAULT 0',
        'last_accessed_at_ms':'INTEGER NOT NULL DEFAULT 0',
        'finished_at_ms':'INTEGER',
        'reply_duration_ms':'INTEGER',
        'processing_duration_ms':'INTEGER',
    }
    for name,definition in additions.items():
        if name not in columns:
            db.execute('ALTER TABLE telegram_inbox ADD COLUMN '+name+' '+definition)
    db.execute('UPDATE telegram_inbox SET received_at_ms=received_at*1000 WHERE received_at_ms=0')
    db.execute('UPDATE telegram_inbox SET last_accessed_at_ms=received_at_ms WHERE last_accessed_at_ms=0')


def prune_telegram_inbox(db, now_ms=None):
    now_ms=now_ms if now_ms is not None else time.time_ns()//1_000_000
    db.execute("DELETE FROM telegram_inbox WHERE status!='pending' AND received_at<?",(now_ms//1000-30*86400,))
    db.execute('''DELETE FROM telegram_inbox
      WHERE status!='pending' AND update_id NOT IN (
        SELECT update_id FROM telegram_inbox WHERE status!='pending'
        ORDER BY last_accessed_at_ms DESC, received_at_ms DESC, update_id DESC
        LIMIT ?)''',(TELEGRAM_INBOX_MAX_HISTORY,))


class McpError(Exception):
    def __init__(self,code,message,status=400,data=None):self.code,self.message,self.status,self.data=code,message,status,data


class Service:
    def __init__(self,config):
        self.config=config
        from .build_info import snapshot
        self.build_info=snapshot()
        self.root=Path(config['state']);self.root.mkdir(parents=True,mode=0o700,exist_ok=True);self.root.chmod(0o700)
        self.db=self.root/'mcp.db'
        self.lock=threading.RLock()
        with database(self.db) as db:
            db.executescript('CREATE TABLE IF NOT EXISTS codes(hash TEXT PRIMARY KEY,client TEXT,redirect TEXT,challenge TEXT,scopes TEXT,expires INT); CREATE TABLE IF NOT EXISTS tokens(hash TEXT PRIMARY KEY,client TEXT,scopes TEXT,expires INT,refresh INT); CREATE TABLE IF NOT EXISTS calls(client TEXT,key TEXT,tool TEXT,digest TEXT,result BLOB,state TEXT,PRIMARY KEY(client,key)); CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,at INT,client TEXT,tool TEXT,digest TEXT,outcome TEXT); CREATE TABLE IF NOT EXISTS rates(client TEXT PRIMARY KEY,window INT,count INT); CREATE TABLE IF NOT EXISTS cimd(client TEXT PRIMARY KEY,metadata BLOB,expires INT); CREATE TABLE IF NOT EXISTS revoked_clients(client TEXT PRIMARY KEY,at INT);')
        self.db.chmod(0o600)
        if config.get('telegram',{}).get('worker_enabled') is True:
            with database(self.db) as db:
                ensure_telegram_schema(db)
        self.tools={}
        self.dispatch={}
        self.add('ziokt_privacy_status','Report actual ownership and transport privacy boundaries; never claim shielded ledger ownership without native consensus support.',schema(),False,'ziokt:read',('privacy-status',))
        self.add('ziokt_naming_status','Report suffix authorities and configured independent naming realms; DNS never grants service access.',schema(),False,'ziokt:read',('naming-status',))
        if config.get('dns_config'):
            self.add('ziokt_name_resolve','Resolve explicitly published public records through the selected node-backed realm. No public DNS fallback.',schema({'name':{'type':'string','maxLength':254},'realm':{'type':'string','maxLength':63}},('name',)),False,'ziokt:read',('name-resolve',))
            self.add('ziokt_name_service','Verify naming ownership and retrieve content references or sealed service descriptors. Does not decrypt or authorize access.',schema({'name':{'type':'string','maxLength':254},'realm':{'type':'string','maxLength':63},'component':{'type':'string','enum':['corium','shadow6','etp','safefs','sim','tri','ufs','dcpm','watchat','zda','ziokt','tc16']}},('name','component')),False,'ziokt:names:read',('name-service',))
        self.add('ziokt_tracker_status','Report optional Tracker deployments. Trackers supplement existing DHT, gossip and direct discovery.',schema(),False,'ziokt:read',('tracker-status',))
        for alias in config.get('trackers',{}):
            if not re.fullmatch('[a-z][a-z0-9_]{0,31}',alias):raise ValueError('bounded tracker alias required')
            for method in ('status','query','register','revoke'):
                write=method in {'register','revoke'}
                fields={} if method=='status' else {'limit':{'type':'integer','minimum':1,'maximum':8}} if method=='query' else {'sequence':{'type':'integer','minimum':0,'maximum':2**53-1}} if method=='revoke' else {'envelope':PARAMS,'publish':{'type':'boolean','const':True},'anonymous':{'type':'boolean'},'relay_authorization':{'type':['object','null']}}
                self.add('tracker_'+alias+'_'+method,'Explicit optional Tracker '+method+'; signed federation scope, lease expiry and member permissions apply.',schema(fields,tuple(fields)),write,'ziokt:discovery:'+('write' if write else 'read'),('tracker',alias,method))
        self.add('ziokt_components','List configured components, exact source build and OpenCI receipt integration boundaries; capability presence is not runtime or settlement proof.',schema(),False,'ziokt:read',('components',))
        if config.get('federation'):
            from .config import load
            from ._runtime import OPERATIONS
            federation=load(config['federation'])
            for provider in federation['providers']:
                project=provider['native_project'];pid=provider['provider_id']
                for method in sorted(READ_NATIVE):
                    if method=='health.challenge':continue
                    if project=='shadow6' and (method.startswith(('zkt.','zkn.','zkc.')) or method in {'content.get','governance.fact','identity.fact','compute.challenge','privacy.status','privacy.review.list','privacy.review.get'}):continue
                    if project=='corium' and method=='service.binding':continue
                    native_params = PARAMS
                    if method in {'privacy.review.list', 'zkn.shield.notes', 'zkn.shield.images'}:
                        native_params = schema({'limit': {'type': 'integer', 'minimum': 1, 'maximum': 64},
                                                'cursor': {'type': 'string', 'pattern': '^(?:[a-f0-9]{64})?$'}})
                    elif method == 'privacy.status':
                        native_params = schema()
                    elif method == 'privacy.review.get':
                        native_params = schema({'request_id': {'type': 'string', 'pattern': '^[a-f0-9]{64}$'}}, ('request_id',))
                    self.add(pid.replace('-','_')+'_'+method.replace('.','_'),f'{pid}: native {method}. Parameters follow the pinned native contract.',schema({'params':native_params},('params',)),False,project+':read',('native',pid,method))
                self.add(pid.replace('-','_')+'_health','Fresh challenge against the pinned native provider process. Application and peer readiness remain separate.',schema(),False,project+':read',('native-health',pid))
                for action in sorted(OPERATIONS[project]):
                    self.add(pid.replace('-','_')+'_'+action.replace('.','_')+'_plan',f'Create a reviewable {pid} {action} workflow; does not execute it.',schema({'resource':STRING,'arguments':PARAMS,'expected_revision':{'type':['string','null']},'operation_id':{'type':'string','maxLength':64}},('resource','arguments','expected_revision','operation_id')),True,project+':'+action+':plan',('plan',pid,action))
        if config.get('federation'):
            from .mcp_corium import READ,WRITE
            for provider in federation['providers']:
                if provider['native_project']!='corium':continue
                for method,wire in {**READ,**WRITE}.items():
                    fields={} if method in {'ping','chain_state','cbb_messages'} else {'payload':STRING if method not in {'block_announce','phoenix_propose','phoenix_notarize','cbb_relay'} else PARAMS}
                    self.add('corium_'+method,'Call the original signed Corium '+wire+' verifier. CBB expires after 24 hours and does not imply consensus finality.',schema(fields,tuple(fields)),method in WRITE,'corium:protocol:'+('write' if method in WRITE else 'read'),('corium-protocol',provider['provider_id'],wire))
                self.add('corium_cbb_publish','Publish a native node-signed CBB emergency bulletin, valid for 24 hours. Requires administrator write scope.',schema({'message':{'type':'string','minLength':1,'maxLength':65536}},('message',)),True,'corium:cbb:write',('corium-cbb',provider['provider_id']))
                self.add('corium_cbb_sync','Synchronize and verify signed native emergency bulletins from approved native peers.',schema(),True,'corium:cbb:write',('corium-cbb-sync',))
                for action in ('new','join','move','forfeit'):
                    fields={'invite':{'type':'string','pattern':'^$|^[a-f0-9]{64}$'}} if action=='new' else {'game_id':{'type':'string','maxLength':80,'pattern':'^game-[A-Za-z0-9_-]+$'}}
                    if action=='move':fields['position']={'type':'integer','minimum':1,'maximum':9}
                    self.add('corium_cbb_game_'+action,'Native signed CBB tic-tac-toe '+action+'. Game state is verified by the native CBB engine.',schema(fields,tuple(fields)),True,'corium:cbb:write',('corium-cbb-game',action))
                self.add('corium_cbb_games','List signed, unexpired native CBB game invitations and moves.',schema(),False,'corium:protocol:read',('corium-protocol',provider['provider_id'],'CBB_SYNC_REQUEST'))
                self.add('corium_cbb_game_state','Verify and read a native CBB game state.',schema({'game_id':{'type':'string','pattern':'^game-[A-Za-z0-9_-]+$','maxLength':80}},('game_id',)),False,'corium:protocol:read',('corium-cbb-game-state',))
        for app in config.get('bridges',{}):
            if not re.fullmatch('[a-z0-9-]{1,64}',app):raise ValueError('invalid bridge name')
            for method in sorted(BRIDGE_READ|BRIDGE_WRITE):
                if app=='ziokt' and method not in {'naming.publish','component.status'}:continue
                if method=='naming.publish' and app not in {'ziokt','shadow6','etp','safefs','sim-manager','sim','tri','ufs','dcpm','watchat','zda','tc16'}:continue
                settings=strict_json(secure_read(config['bridges'][app]))
                if method.startswith('object.') and not settings.get('vault_root'):continue
                if method.startswith('file.') and not settings.get('inbox'):continue
                if method.startswith('ano.') and method!='ano.laws' and app!='zda':continue
                if method=='tc16.run' and app!='tc16':continue
                if method.startswith('tri.') and app!='tri':continue
                if method.startswith('sim.') and app!='sim-manager':continue
                if method.startswith('chat.') and app!='watchat':continue
                if method.startswith('package.') and app not in {'ufs','dcpm'}:continue
                self.add(app.replace('-','_')+'_'+method.replace('.','_'),f'{app}: {method} through its authenticated application bridge.',schema({'params':BRIDGE.get(method,PARAMS)},('params',)),method in BRIDGE_WRITE,app+(':write' if method in BRIDGE_WRITE else ':read'),('bridge',app,method))
        if config.get('native_package_handoff'):
            self.add('ziokt_package_admission_approve','Owner: whitelist an exact staged, independently signed native package for later install/activate plans. Does not install or run code.',schema({'receipt_digest':STRING,'selector':STRING,'confirm':{'type':'boolean','const':True}},('receipt_digest','selector','confirm')),True,'ziokt:admin',('native-admission',))
            self.add('ziokt_package_signer_list','Owner: inspect the native package publisher allowlist.',schema(),False,'ziokt:admin',('native-signers','list'))
            self.add('ziokt_package_signer_update','Owner: explicitly approve or revoke an Ed25519 native package publisher. Does not install or activate code.',schema({'signer':STRING,'public_key':{'type':'string','pattern':'^[a-f0-9]{64}$'},'decision':{'type':'string','enum':['approve','revoke']},'confirm':{'type':'boolean','const':True}},('signer','decision','confirm')),True,'ziokt:admin',('native-signers','update'))
            for app in ('dcpm','ufs'):
                if app in config.get('bridges',{}):
                    self.add(app+'_package_stage_native','Verify both DCPM and native signatures and stage a v1/v2 reference package. Does not install, activate or run it.',schema({'digest':STRING,'authority':STRING},('digest','authority')),True,app+':write',('native-package-stage',app))
        self.add('ziokt_workflow_status','Read the caller-owned workflow.',schema({'workflow_id':STRING},('workflow_id',)),False,'ziokt:read',('workflow-status',))
        self.add('ziokt_workflow_apply','Execute a caller-owned reviewed plan with exact digest and explicit confirmation.',schema({'workflow_id':STRING,'plan_digest':STRING,'confirm':{'type':'boolean','const':True}},('workflow_id','plan_digest','confirm')),True,'ziokt:apply',('workflow-apply',))
        if config.get('gateway'):
            for method,write,props,required in [
                ('status',False,{},()),('forum_list',False,{'limit':{'type':'integer','minimum':1,'maximum':100}},('limit',)),
                ('forum_publish',True,{'payload':PARAMS},('payload',)),('manifest',False,{'root':STRING},('root',)),
                ('file_publish',True,{'name':STRING,'data_base64':STRING},('name','data_base64'))]:
                self.add('gateway_'+method,'Native gateway '+method,schema(props,required),write,'gateway:'+('write' if write else 'read'),('gateway',method))
        for item in config.get('etp',{}):
            for method,write in [('etp.health',False),('etp.mailbox.status',False),('etp.mailbox.request',True),('etp.stats',False),('etp.receive',True),('etp.onion.send',True),('etp.forum.identity',True),('etp.forum.subscribe',True),('etp.forum.publish',True),('etp.forum.get',False)]:
                self.add(item.replace('-','_')+'_'+method.replace('.','_'),'Pinned native ETP '+method+('; fresh stats challenge, peer readiness separate.' if method=='etp.health' else ''),schema({'params':ETP.get(method,PARAMS)},('params',)),write,'etp:'+('write' if write else 'read'),('etp',item,method))
        telegram=config.get('telegram',{})
        if telegram.get('enabled') is True:
            if not isinstance(telegram.get('allowed_chat_ids'),list) or not telegram['allowed_chat_ids']:
                raise ValueError('Telegram requires an explicit nonempty chat allowlist')
            from .telegram import TelegramBot
            # Validate the private token file before advertising any Telegram tools.
            TelegramBot(telegram)
            self.add('telegram_bot_status','Read the configured Telegram bot identity and webhook mode.',schema(),False,'telegram:read',('telegram','status'))
            self.add('telegram_get_updates','Read recent Telegram updates only from explicitly allowlisted chats. Optional offset filters update IDs.',schema({'offset':{'type':'integer','minimum':0,'maximum':2**53-1}},()),False,'telegram:read',('telegram','updates'))
            self.add('telegram_send_message','Send plain text to an explicitly allowlisted Telegram chat.',schema({'chat_id':{'type':'string','pattern':'^-?[0-9]{1,20}$','maxLength':21},'text':{'type':'string','minLength':1,'maxLength':4096}},('chat_id','text')),True,'telegram:write',('telegram','send'))
            chat={'chat_id':{'type':'string','pattern':'^-?[0-9]{1,20}$','maxLength':21}}
            message={'message_id':{'type':'integer','minimum':1,'maximum':2**53-1}}
            member={'user_id':{'type':'integer','minimum':1,'maximum':2**53-1}}
            for tool,desc,props,required,write,op in [
                ('telegram_get_chat','Read an allowlisted chat.',chat,('chat_id',),False,'get-chat'),
                ('telegram_get_chat_member','Read one member of an allowlisted chat.',{**chat,**member},('chat_id','user_id'),False,'get-member'),
                ('telegram_edit_message','Edit text in an allowlisted chat.',{**chat,**message,'text':{'type':'string','minLength':1,'maxLength':4096}},('chat_id','message_id','text'),True,'edit'),
                ('telegram_delete_message','Delete a message in an allowlisted chat.',{**chat,**message},('chat_id','message_id'),True,'delete'),
                ('telegram_forward_message','Forward a message between allowlisted chats.',{**chat,'from_chat_id':chat['chat_id'],**message},('chat_id','from_chat_id','message_id'),True,'forward'),
                ('telegram_copy_message','Copy a message between allowlisted chats.',{**chat,'from_chat_id':chat['chat_id'],**message},('chat_id','from_chat_id','message_id'),True,'copy'),
                ('telegram_send_photo','Send a Telegram file_id photo to an allowlisted chat.',{**chat,'file_id':{'type':'string','minLength':1,'maxLength':512},'caption':{'type':'string','maxLength':1024}},('chat_id','file_id'),True,'photo'),
                ('telegram_send_document','Send a Telegram file_id document to an allowlisted chat.',{**chat,'file_id':{'type':'string','minLength':1,'maxLength':512},'caption':{'type':'string','maxLength':1024}},('chat_id','file_id'),True,'document'),
                ('telegram_send_location','Send coordinates to an allowlisted chat.',{**chat,'latitude':{'type':'number','minimum':-90,'maximum':90},'longitude':{'type':'number','minimum':-180,'maximum':180}},('chat_id','latitude','longitude'),True,'location'),
                ('telegram_send_poll','Send a poll to an allowlisted chat.',{**chat,'question':{'type':'string','minLength':1,'maxLength':300},'options':{'type':'array','minItems':2,'maxItems':10,'items':{'type':'string','minLength':1,'maxLength':100}},'is_anonymous':{'type':'boolean'}},('chat_id','question','options'),True,'poll'),
                ('telegram_answer_callback','Answer a callback query read from allowlisted updates.',{'callback_query_id':{'type':'string','minLength':1,'maxLength':256},'text':{'type':'string','maxLength':200}},('callback_query_id',),True,'callback'),
                ('telegram_pin_message','Pin a message in an allowlisted chat.',{**chat,**message},('chat_id','message_id'),True,'pin'),
                ('telegram_unpin_message','Unpin a message in an allowlisted chat.',{**chat,**message},('chat_id','message_id'),True,'unpin'),
                ('telegram_set_chat_title','Set the title of an allowlisted group or channel.',{**chat,'title':{'type':'string','minLength':1,'maxLength':128}},('chat_id','title'),True,'title'),
                ('telegram_set_chat_description','Set the description of an allowlisted group or channel.',{**chat,'description':{'type':'string','maxLength':255}},('chat_id','description'),True,'description')]:
                self.add(tool,desc,schema(props,required),write,'telegram:'+('write' if write else 'read'),('telegram',op))
        self.add('ziokt_audit_read','Administrator: inspect recent tool names, request digests and outcomes without exposing payloads or tokens.',schema({'limit':{'type':'integer','minimum':1,'maximum':100}},('limit',)),False,'ziokt:admin',('admin','audit'))
        for action in ('revoke','restore'):
            self.add('ziokt_client_'+action,'Administrator: '+action+' an OAuth client and its current access tokens.',schema({'client_id':{'type':'string','maxLength':256}},('client_id',)),True,'ziokt:admin',('admin',action))
        if config.get('gateway'):
            self.add('corium_registration_submit','Apply for external_chain or pouw_engine whitelist membership. Only owner approval makes an entry eligible.',schema({'entry':schema({'kind':{'type':'string','enum':['external_chain','pouw_engine']},'target':{'type':'string','pattern':'^[a-z0-9][a-z0-9_-]{0,63}$'},'description':{'type':'string','minLength':1,'maxLength':2048},'weight':{'type':'integer','minimum':1,'maximum':1000000},'genesis_hash':{'type':'string','pattern':'^[a-f0-9]{64}$'},'verifier_hash':{'type':'string','pattern':'^[a-f0-9]{64}$'},'pkg_id':{'type':'string','maxLength':160},'compute_program_hash':{'type':'string','pattern':'^[a-f0-9]{64}$'},'verifier_script_hash':{'type':'string','pattern':'^[a-f0-9]{64}$'}},('kind','target','description','weight'))},('entry',)),True,'corium:registry:submit',('registry','submit'))
            self.add('corium_registration_list','Read approved registrations or your own applications; administrator can inspect all pending applications.',schema({'status':{'type':'string','enum':['approved','pending','rejected','revoked','submitting','all']}},('status',)),False,'corium:registry:read',('registry','list'))
            self.add('corium_registration_decide','Owner only: approve, reject or revoke an immutable application using its exact digest. PoUW approval submits native governance, not instant consensus activation.',schema({'registration_id':{'type':'string','pattern':'^[a-f0-9]{32}$'},'digest':{'type':'string','pattern':'^[a-f0-9]{64}$'},'decision':{'type':'string','enum':['approve','reject','revoke']},'confirm':{'type':'boolean','const':True}},('registration_id','digest','decision','confirm')),True,'ziokt:admin',('registry','decide'))
        if config.get('shadow6_control') or config.get('shadow6_mcp'):
            from .shadow6_control_mcp import attach_shadow6_control
            attach_shadow6_control(self, config.get('shadow6_control') or config.get('shadow6_mcp'))
        if config.get('content_fabric',{}).get('enabled') is True:
            from .content_api import attach
            attach(self,config['content_fabric'])
        self.scopes=sorted({tool['scope'] for tool in self.tools.values()})
        self.etp={}
        self.content_etp=None;self.content_etp_config=None

    def attach_shadow6_control(self,config=None,adapter=None):
        from .shadow6_control_mcp import attach_shadow6_control
        return attach_shadow6_control(self,config=config,adapter=adapter)

    def close(self):
        with self.lock:
            if self.content_etp is not None:self.content_etp.close();self.content_etp=None
            for gateway in self.etp.values():gateway.close()
            self.etp.clear()
        if getattr(self,'shadow6_control',None):
            self.shadow6_control.close()

    def etp_backend(self,settings):
        from .etp import EtpGateway
        settings={field:settings[field] for field in ('binary','digest','config')}
        key='shared-'+hashlib.sha256(encoded(settings)).hexdigest()
        with self.lock:
            if key not in self.etp:
                if len(self.etp)>=16:raise ProtocolError('ETP_BACKEND_QUOTA','Deactivate old native bindings before adding another backend')
                self.etp[key]=EtpGateway(settings['binary'],settings['digest'],settings['config'])
            return self.etp[key]

    def native_content_etp(self,settings):
        config=settings.get('native_etp') if settings.get('enabled') is True else None
        raw=encoded(config)
        with self.lock:
            if raw!=self.content_etp_config:
                if self.content_etp is not None:self.content_etp.close()
                previous=json.loads(self.content_etp_config) if self.content_etp_config is not None else None
                if previous is not None:
                    key='shared-'+hashlib.sha256(encoded(previous['gateway'])).hexdigest()
                    old=self.etp.pop(key,None)
                    if old is not None:old.close()
                self.content_etp=None;self.content_etp_config=raw
                if config is not None:
                    from .content_etp_application import EtpApplications
                    def live_file_policy(account):
                        live=self.current().get('content_fabric',{})
                        if live.get('enabled') is not True:return None
                        current=live.get('native_etp')
                        if not isinstance(current,dict):return None
                        return current.get('accounts',{}).get(account,{}).get('fileshare')
                    self.content_etp=EtpApplications(config,transport=lambda method,params:self.etp_backend(config['gateway']).call(method,params),file_policy=live_file_policy)
            return self.content_etp

    def add(self,name,description,input_schema,write,scope,route):
        if name in self.tools:raise ValueError('tool name collision')
        if write:
            input_schema={**input_schema,'properties':{**input_schema['properties'],'idempotency_key':{'type':'string','minLength':16,'maxLength':128,'pattern':'^[A-Za-z0-9_-]{16,128}$','description':'Unique operation key; reuse the same value only when retrying identical arguments.'}},'required':input_schema['required']}
            description+=' Idempotency is automatic; optionally supply idempotency_key to retry across transport requests.'
        schemes=[{'type':'oauth2','scopes':[scope]}]
        self.tools[name]={'securitySchemes':schemes,'_meta':{'securitySchemes':schemes},'name':name,'description':description,'inputSchema':input_schema,'annotations':{'readOnlyHint':not write,'destructiveHint':write,'idempotentHint':False,'openWorldHint':True},'scope':scope}
        self.dispatch[name]=route
        if hasattr(self,'scopes') and scope not in self.scopes:
            self.scopes=sorted(set(self.scopes)|{scope})

    def token_digest(self,token):
        return hashlib.sha256((self.config['issuer']+'/mcp\n'+token).encode()).hexdigest()

    def current(self):
        return strict_json(secure_read(self.config['config_path'])) if self.config.get('config_path') else self.config

    def client(self,client_id):
        current=self.current()
        if client_id in current.get('revoked_clients',[]):return None
        with database(self.db) as db:
            if db.execute('SELECT 1 FROM revoked_clients WHERE client=?',(client_id,)).fetchone():return None
        if client_id in current['clients']:return current['clients'][client_id]
        if not current.get('cimd_enabled') or not isinstance(client_id,str) or not re.fullmatch(r'https://chatgpt\.com/oauth/(?:[A-Za-z0-9_-]{1,128}/)?client\.json',client_id):return None
        with database(self.db) as db:row=db.execute('SELECT metadata,expires FROM cimd WHERE client=?',(client_id,)).fetchone()
        if row and row[1]>time.time():metadata=json.loads(row[0])
        else:
            import urllib.request
            from .gateway_store import NoRedirect
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
            with opener.open(client_id,timeout=10) as response:raw=response.read(16385)
            if len(raw)>16384:raise ValueError('CIMD metadata budget')
            metadata=json.loads(raw,object_pairs_hook=unique)
            if metadata.get('client_id')!=client_id:raise ValueError('CIMD identifier mismatch')
            redirects=metadata.get('redirect_uris',[])
            if not isinstance(redirects,list) or not 1<=len(redirects)<=8 or any(not isinstance(uri,str) or not re.fullmatch(r'https://chatgpt\.com/(?:connector_platform_oauth_redirect|connector/oauth/[A-Za-z0-9_-]{1,128})',uri) for uri in redirects):raise ValueError('CIMD redirect rejected')
            methods=metadata.get('token_endpoint_auth_methods_supported',[metadata.get('token_endpoint_auth_method')])
            if 'none' not in methods:raise ValueError('public PKCE client method unavailable')
            with database(self.db) as db:db.execute('INSERT OR REPLACE INTO cimd VALUES (?,?,?)',(client_id,encoded(metadata),int(time.time())+3600))
        return {'redirect_uris':metadata['redirect_uris'],'scopes':current.get('cimd_scopes',self.scopes)}

    def auth(self,header):
        if not isinstance(header,str) or not header.startswith('Bearer ') or len(header)>256:raise McpError(-32001,'authentication required',401)
        digest=self.token_digest(header[7:]);now=int(time.time())
        with database(self.db) as db:
            row=db.execute('SELECT client,scopes,expires FROM tokens WHERE hash=? AND refresh=0',(digest,)).fetchone()
            if not row or row[2]<=now:raise McpError(-32001,'invalid or expired access token',401)
            client=self.client(row[0])
            if not client:raise McpError(-32001,'client revoked',401)
            scopes=set(json.loads(row[1]))&set(client['scopes'])
            old=db.execute('SELECT window,count FROM rates WHERE client=?',(row[0],)).fetchone()
            window=now//60
            count=old[1]+1 if old and old[0]==window else 1
            if count>120:raise McpError(-32001,'rate limit',429)
            db.execute('INSERT OR REPLACE INTO rates VALUES (?,?,?)',(row[0],window,count))
        return {'client':row[0],'scopes':scopes,'expires':row[2],'token_id':digest}

    def issue(self,client,scopes):
        access,refresh=secrets.token_urlsafe(48),secrets.token_urlsafe(48);now=int(time.time())
        with database(self.db) as db:
            db.execute('DELETE FROM tokens WHERE expires<?',(now,));db.execute('DELETE FROM codes WHERE expires<?',(now,))
            for token,ttl,is_refresh in [(access,900,0),(refresh,86400,1)]:
                db.execute('INSERT INTO tokens VALUES (?,?,?,?,?)',(self.token_digest(token),client,json.dumps(sorted(scopes)),now+ttl,is_refresh))
        return {'access_token':access,'token_type':'Bearer','expires_in':900,'refresh_token':refresh,'scope':' '.join(sorted(scopes))}

    def validate(self,args,spec):
        if not isinstance(args,dict) or set(args)-set(spec['properties']) or not set(spec['required'])<=set(args):raise ValueError('exact tool arguments required')
        for key,value in args.items():
            field=spec['properties'][key];kind=field['type'];kinds=kind if isinstance(kind,list) else [kind]
            actual='null' if value is None else 'boolean' if type(value) is bool else 'integer' if type(value) is int else 'string' if isinstance(value,str) else 'object' if isinstance(value,dict) else 'array'
            if type(value) is float:actual='number'
            if actual not in kinds:raise ValueError('invalid '+key)
            if actual=='object':
                if not field.get('minProperties',0)<=len(value)<=field.get('maxProperties',4096):raise ValueError('object budget exceeded')
                if 'properties' in field:self.validate(value,field)
                elif isinstance(field.get('additionalProperties'),dict):
                    for entry in value.values():self.validate({'entry':entry},{'properties':{'entry':field['additionalProperties']},'required':['entry']})
            if actual=='array' and not field.get('minItems',0)<=len(value)<=field.get('maxItems',128):raise ValueError('array budget exceeded')
            if actual=='array' and 'items' in field:
                for item in value:self.validate({'item':item},{'properties':{'item':field['items']},'required':['item']})
            if 'enum' in field and value not in field['enum']:raise ValueError('invalid enum')
            if actual=='string' and 'pattern' in field and not re.fullmatch(field['pattern'],value):raise ValueError('invalid identifier')
            if 'const' in field and value!=field['const']:raise ValueError('invalid confirmation')
            if actual=='string' and len(value)>field.get('maxLength',65536):raise ValueError('argument too large')
            if actual=='string' and len(value)<field.get('minLength',0):raise ValueError('argument too short')
            if actual=='integer' and not field.get('minimum',-2**53+1)<=value<=field.get('maximum',2**53-1):raise ValueError('integer out of bounds')
            if actual=='number' and not field.get('minimum',-1e308)<=value<=field.get('maximum',1e308):raise ValueError('number out of bounds')

    def permitted(self,principal,tool):
        return tool['scope'] in principal['scopes'] and (not tool['annotations']['destructiveHint'] or self.config.get('writes_enabled') is True)

    def call(self,principal,name,args,key=None):
        if principal.get('expires',2**63)<=time.time():raise McpError(-32001,'token expired',401)
        tool=self.tools.get(name)
        if tool is None:raise McpError(-32602,'unknown tool')
        if not self.permitted(principal,tool):raise McpError(-32001,'insufficient scope',403,{'scope':tool['scope']})
        if isinstance(args,dict):
            args=dict(args)
            if tool['annotations']['destructiveHint'] and key:args.setdefault('idempotency_key',key)
        self.validate(args,tool['inputSchema'])
        if tool['annotations']['destructiveHint']:key=args.pop('idempotency_key',key)
        if tool['annotations']['destructiveHint']:self.guard(principal)
        write=tool['annotations']['destructiveHint'];digest=hashlib.sha256(encoded({'name':name,'arguments':args})).hexdigest()
        if write and (not isinstance(key,str) or not re.fullmatch('[A-Za-z0-9_-]{16,128}',key)):raise ValueError('write requires _meta.ziokt/idempotencyKey (16..128 safe characters)')
        with self.lock:
            if write:
                with database(self.db) as db:
                    old=db.execute('SELECT tool,digest,result,state FROM calls WHERE client=? AND key=?',(principal['client'],key)).fetchone()
                    if old:
                        if old[:2]!=(name,digest):raise ValueError('idempotency conflict')
                        if old[3]!='complete':raise ValueError('operation outcome requires reconciliation; never blindly replay')
                        return json.loads(old[2])
                    db.execute('INSERT INTO calls VALUES (?,?,?,?,NULL,?)',(principal['client'],key,name,digest,'pending'))
            try:
                if principal.get('expires',2**63)<=time.time():raise McpError(-32001,'access token expired',401)
                result=self.execute(principal,name,args)
                if len(encoded(result))>512000:raise ValueError('result budget exceeded; use pagination or content references')
                output={'resultType':'complete','content':[{'type':'text','text':encoded(result).decode()}],'structuredContent':result if isinstance(result,dict) else {'items':result},'isError':False}
            except Exception as exc:
                # Secrets and application payloads never appear in error/audit text.
                output={'resultType':'complete','content':[{'type':'text','text':str(getattr(exc,'code','EXECUTION_REJECTED'))+': operation rejected; inspect native state before retry'}],'isError':True}
            with database(self.db) as db:
                db.execute('INSERT INTO audit(at,client,tool,digest,outcome) VALUES (?,?,?,?,?)',(int(time.time()),principal['client'],name,digest,'error' if output['isError'] else 'complete'))
                if write:db.execute('UPDATE calls SET result=?,state=? WHERE client=? AND key=?',(encoded(output),'complete',principal['client'],key))
            return output

    def execute(self,principal,name,args):
        route=self.dispatch[name];kind=route[0]
        if kind=='content-fabric':
            from .content_fabric import Fabric
            from .content_api import invoke,required_scopes
            settings=self.current()['content_fabric']
            native_etp=self.native_content_etp(settings)
            if settings.get('enabled') is not True:raise PermissionError('content applications disabled')
            if not required_scopes(route[1])<=set(principal['scopes']):raise PermissionError('content operation scopes')
            owner=settings.get('accounts',{}).get(principal['client'])
            if not owner:raise PermissionError('explicit content account mapping required')
            fabric=Fabric(settings['root'],quota=settings.get('quota',2*1024**3),peers={p['public_key']:{'groups':p.get('groups',[])} for p in settings.get('peers',{}).values()})
            fabric.remote_peers=settings.get('peers',{})
            fabric.community_config=settings.get('community',{})
            fabric.native_etp=native_etp
            try:return invoke(fabric,owner,route[1],args)
            finally:fabric.close()
        if kind=='tracker-status':
            return {'schema':'ziokt.tracker-capability.v1','configured':sorted(self.config.get('trackers',{})),
                    'optional':True,'replaces_dht':False,'registration_opt_in':True,'maximum_lease_seconds':600,
                    'anonymous_real_ip_registration_allowed':False,'discovery_confers_membership':False}
        if kind=='tracker':
            from .peer_directory import load_directory
            from .tracker import TrackerClient
            from .remote import load_remote,tls_context
            material=self.config['trackers'][route[1]]
            if not isinstance(material,dict) or set(material)!={'discovery_config','tls_config'}:raise ValueError('fixed tracker and discovery configurations required')
            directory,discovery=load_directory(material['discovery_config'])
            endpoint=load_remote(material['tls_config'])
            context=tls_context(endpoint['certificate'],endpoint['private_key'],endpoint['ca'])
            client=TrackerClient(directory,secure_read(discovery['signing_key'],32),endpoint,context)
            return client.call('tracker.'+route[2],args)
        if kind in {'naming-status','name-resolve','name-service'}:
            from .naming import SUFFIXES
            from .dns_server import load as load_dns
            networks=None
            if self.config.get('dns_config'):
                _,networks=load_dns(self.config['dns_config'])
            if kind=='naming-status':
                return {'suffix_authorities':SUFFIXES,'realms':{} if networks is None else {key:{'network_id':view.network_id,'sources':sorted(view.sources)} for key,view in networks.realms.items()},'public_dns_fallback':False,'dns_confers_authorization':False,'nns_default_publication':False,'ech_tls_termination_verified':False}
            if networks is None:raise ValueError('DNS node configuration unavailable')
            return networks.resolve(args['name'],realm=args.get('realm'),component=args.get('component'),public=kind=='name-resolve')
        if kind=='components':return {'components':sorted(self.config.get('bridges',{})),'native_providers':sorted({r[1] for r in self.dispatch.values() if r[0]=='native'}),'etp_nodes':sorted(self.config.get('etp',{})),'protocols':VERSIONS,'tools':len(self.tools),'writes_enabled':self.current().get('writes_enabled',False),'build':self.build_info,'source_features':{'openci':{'worker_receipt_schema':'openci.worker-receipt.v1','signature_domain':'OpenCI/worker-receipt/v1','result_bindings':['pipeline','task','attempt','source','task_digest','lease_digest','worker','result'],'native_delivery':'signed-dcpm-provenance','controller_running':'not_assessed','remote_workers':'not_assessed','hardware_attestation':False,'native_consensus_settlement':'testnet_implementation_acceptance_pending','native_claim_plan':'openci.native-contribution-plan.v1','native_work_consensus':'testnet_implementation_acceptance_pending','mainnet_consensus_changed':False}}}
        if kind=='registry':
            from .registry import Registry
            from .gateway import Gateway
            gateway=Gateway(strict_json(secure_read(self.config['gateway'])))
            registry=Registry(gateway.config.get('registry_db',self.root/'registry.db'),gateway.config['network'])
            if route[1]=='submit':return registry.submit(principal['client'],args['entry'])
            if route[1]=='list':return registry.list(args['status'],None if 'ziokt:admin' in principal['scopes'] or args['status']=='approved' else principal['client'])
            return registry.decide(principal['client'],args['registration_id'],args['digest'],args['decision'],gateway.native_text)
        if kind=='admin':
            with database(self.db) as db:
                if route[1]=='audit':
                    rows=db.execute('SELECT at,client,tool,digest,outcome FROM audit ORDER BY id DESC LIMIT ?',(args['limit'],)).fetchall()
                    return {'audit':[dict(zip(('at','client','tool','request_digest','outcome'),row)) for row in rows]}
                if route[1]=='revoke':
                    db.execute('INSERT OR REPLACE INTO revoked_clients VALUES (?,?)',(args['client_id'],int(time.time())))
                    db.execute('DELETE FROM tokens WHERE client=?',(args['client_id'],))
                    db.execute('DELETE FROM codes WHERE client=?',(args['client_id'],))
                else:db.execute('DELETE FROM revoked_clients WHERE client=?',(args['client_id'],))
            return {'client':args['client_id'],'state':'revoked' if route[1]=='revoke' else 'restored'}
        if kind in {'native','native-health','plan','workflow-status','workflow-apply'}:
            from .config import load
            from .client import NativeClient
            from .workflow import WorkflowJournal as Journal
            federation=load(self.config['federation']);providers={p['provider_id']:p for p in federation['providers']}
            if kind=='native':return NativeClient(federation['federation_id'],providers[route[1]]).call(route[2],args['params'])
            if kind=='native-health':return NativeClient(federation['federation_id'],providers[route[1]]).health()
            # Caller ownership is encoded in the workflow ID; no cross-client plan access.
            prefix=hashlib.sha256(principal['client'].encode()).hexdigest()[:12]+'-'
            with Journal(self.root/'workflows.db') as journal:
                if kind=='plan':
                    workflow=prefix+args['operation_id'][:48]
                    manifest={'schema':'ziokt.workflow.v1','workflow_id':workflow,'steps':[{'step_id':'apply','provider_id':route[1],'action':route[2],'resource':args['resource'],'arguments':args['arguments'],'expected_revision':args['expected_revision'],'depends_on':[]}]}
                    return journal.plan(manifest,federation)
                if not args['workflow_id'].startswith(prefix):raise ValueError('workflow belongs to another client')
                if kind=='workflow-status':return journal.status(args['workflow_id'])
                row=journal.db.execute('SELECT manifest FROM workflows WHERE id=?',(args['workflow_id'],)).fetchone()
                if not row:raise ValueError('unknown workflow')
                manifest=json.loads(row[0])['manifest']
                for step in manifest['steps']:
                    project=providers[step['provider_id']]['native_project']
                    if project+':'+step['action']+':plan' not in principal['scopes']:raise ValueError('native write scope revoked')
                return journal.apply(args['workflow_id'],federation,args['plan_digest'],confirmed=args['confirm'],guard=lambda: self.guard(principal))
        if kind in {'corium-protocol','corium-cbb'}:
            from .config import load
            from .mcp_corium import CoriumProtocol
            federation=load(self.config['federation'])
            provider=next(p for p in federation['providers'] if p['provider_id']==route[1])
            if not federation['enabled']:raise ValueError('federation disabled')
            protocol=CoriumProtocol(provider)
            if kind=='corium-cbb':
                from .gateway import Gateway
                gateway=Gateway(strict_json(secure_read(self.config['gateway'])))
                gateway.native('cbb-post',args['message'])
                return {'published':True,'native_identity':protocol.identity,'expires_after_seconds':86400,'consensus_confirmed':False}
            payload=args.get('payload','')
            if isinstance(payload,dict):payload=json.dumps(payload)
            result=protocol.call(route[2],payload)
            if name=='corium_cbb_games':result['data']=[row for row in result['data'] if row.get('message','').startswith('GAME:TICTACTOE|')]
            return result
        if kind in {'corium-cbb-sync','corium-cbb-game','corium-cbb-game-state'}:
            from .gateway import Gateway
            gateway=Gateway(strict_json(secure_read(self.config['gateway'])))
            if kind=='corium-cbb-sync':gateway.native('cbb-sync');return {'synchronized':True}
            if kind=='corium-cbb-game-state':
                text=gateway.native_text('cbb-state',args['game_id'])
                values=text.strip().split('|')
                if len(values)!=5:raise ValueError('invalid native game state')
                return dict(zip(('player_x','player_o','board','turn','state'),values))
            action=route[1]
            values=[args.get('game_id','')]
            if action=='move':values.append(str(args['position']))
            if action=='new':values=['--invite',args['invite']] if args['invite'] else []
            text=gateway.native_text('cbb-game',action,*values)
            return {'action':action,'native_result':text,'consensus_confirmed':False}
        if kind=='privacy-status':
            return {'transport_encryption':True,'fresh_receiver_keys':True,'sealed_receipts':True,
                    'authenticated_receiver_can_identify_caller':True,'ledger_ownership_transitions_observable':True,
                    'shielded_ownership_supported':False,'shielded_testnet_implementation':True,'shielded_proof_version':'zkn-rct-experimental-v1','independently_audited':False,
                    'review_request_consensus_implemented':True,'universal_decryption_key':False,'review_approval_decrypts_data':False,'holder_disclosure_consent_required':True,
                    'anonymous_against_global_observer':False,
                    'required_for_shielded_ownership':['independent cryptographic audit of experimental ring protocol','versioned whole-network consensus rollout','production wallet recovery and operational audit','production migration and consensus acceptance tests']}
        if kind=='native-admission':
            from .package_handoff import approve_native_admission
            return approve_native_admission(self.current().get('native_package_handoff'),args['receipt_digest'],args['selector'])
        if kind=='native-signers':
            from .package_handoff import update_native_signer
            settings=self.current().get('native_package_handoff')
            if route[1]=='list':return update_native_signer(settings)
            return update_native_signer(settings,args['signer'],args.get('public_key'),args['decision'])
        if kind=='native-package-stage':
            from .companion_bridge import CompanionBridge
            from .package_handoff import stage_bridge_package
            bridge=CompanionBridge(self.config['bridges'][route[1]])
            try:return stage_bridge_package(self.current().get('native_package_handoff'),bridge,args['digest'],args['authority'])
            finally:bridge.close()
        if kind=='bridge':
            from .companion_bridge import CompanionBridge
            bridge=CompanionBridge(self.config.get('exchanges',{}).get(route[1],self.config['bridges'][route[1]]) if route[2] in {'component.send','component.receive'} else self.config['bridges'][route[1]])
            try:return bridge.call(route[2],args['params'])
            finally:bridge.close()
        if kind=='gateway':
            from .gateway import Gateway
            gateway=Gateway(strict_json(secure_read(self.config['gateway'])))
            method=route[1]
            if method=='status':return {'network':gateway.config['network'],'authenticated_writes':True}
            if method=='forum_publish':return {'id':gateway.submit(args['payload'],'mcp:'+principal['client'])}
            if method=='forum_list':
                with database(gateway.config['forum_db']) as db:
                    rows=db.execute('SELECT id,title,author,timestamp,content_hash FROM topics ORDER BY timestamp DESC LIMIT ?',(args['limit'],)).fetchall()
                return {'topics':[dict(zip(('id','title','author','timestamp','content_hash'),r)) for r in rows]}
            if method=='manifest':return gateway.store.manifest(args['root'])
            if method=='file_publish':
                import io
                data=base64.b64decode(args['data_base64'],validate=True)
                if len(data)>32768:raise ValueError('use local publish-file CLI for larger payloads')
                return {'root':gateway.store.publish(io.BytesIO(data),args['name'])}
        if kind=='etp':
            settings=self.current()['etp'][route[1]]
            return self.etp_backend(settings).call(route[2],args['params'])
        if kind=='telegram':
            from .telegram import TelegramBot
            bot=TelegramBot(self.current()['telegram'])
            if route[1]=='status':return bot.status()
            if route[1]=='updates':
                if self.current().get('telegram',{}).get('worker_enabled') is True:
                    with database(self.db) as db:
                        offset=args.get('offset',0)
                        now_ms=time.time_ns()//1_000_000
                        rows=db.execute('''SELECT update_id,payload,status,received_at_ms,finished_at_ms,reply_duration_ms,processing_duration_ms
                          FROM telegram_inbox WHERE update_id>=? ORDER BY update_id LIMIT 100''',(offset,)).fetchall()
                        db.executemany('UPDATE telegram_inbox SET last_accessed_at_ms=? WHERE update_id=?',((now_ms,row[0]) for row in rows))
                    return {'updates':[json.loads(row[1]) for row in rows],'count':len(rows),'source':'durable worker inbox',
                            'reply_metrics':[{'update_id':row[0],'status':row[2],'received_at_ms':row[3],
                              'finished_at_ms':row[4],'reply_duration_ms':row[5],
                              'processing_duration_ms':row[6]} for row in rows]}
                return bot.updates(args.get('offset'))
            if route[1]=='send':return bot.send(args['chat_id'],args['text'])
            if route[1]=='get-chat':return bot.chat(args['chat_id'])
            if route[1]=='get-member':return bot.member(args['chat_id'],args['user_id'])
            if route[1]=='edit':return bot.call('editMessageText',{'chat_id':bot.chat_id(args['chat_id']),'message_id':args['message_id'],'text':args['text']})
            if route[1]=='delete':return bot.call('deleteMessage',{'chat_id':bot.chat_id(args['chat_id']),'message_id':args['message_id']})
            if route[1] in {'forward','copy'}:
                values={'chat_id':bot.chat_id(args['chat_id']),'from_chat_id':bot.chat_id(args['from_chat_id']),'message_id':args['message_id']}
                return bot.call('forwardMessage' if route[1]=='forward' else 'copyMessage',values)
            if route[1] in {'photo','document'}:
                values={'chat_id':bot.chat_id(args['chat_id']), 'photo' if route[1]=='photo' else 'document':args['file_id']}
                if args.get('caption'):values['caption']=args['caption']
                return bot.call('sendPhoto' if route[1]=='photo' else 'sendDocument',values)
            if route[1]=='location':return bot.call('sendLocation',{**{key:args[key] for key in ('latitude','longitude')},'chat_id':bot.chat_id(args['chat_id'])})
            if route[1]=='poll':
                values={key:args[key] for key in ('question','options')};values.update({'chat_id':bot.chat_id(args['chat_id']),'is_anonymous':args.get('is_anonymous',True)})
                return bot.call('sendPoll',values)
            if route[1]=='callback':return bot.call('answerCallbackQuery',{key:args[key] for key in ('callback_query_id','text') if key in args})
            if route[1] in {'pin','unpin'}:
                values={'chat_id':bot.chat_id(args['chat_id'])}
                if route[1]=='pin':values['message_id']=args['message_id']
                return bot.call('pinChatMessage' if route[1]=='pin' else 'unpinChatMessage',values)
            if route[1] in {'title','description'}:
                values={'chat_id':bot.chat_id(args['chat_id']),'title' if route[1]=='title' else 'description':args[route[1]]}
                return bot.call('setChatTitle' if route[1]=='title' else 'setChatDescription',values)
        if kind=='shadow6-control':
            tool_name=route[1]
            adapter=getattr(self,'shadow6_control',None)
            if adapter is None:raise McpError(-32603,'shadow6-control adapter not configured')
            result=adapter.call_tool(tool_name,args)
            if result.get('isError'):
                content=result.get('content',[{}])
                msg=content[0].get('text','operation rejected') if content else 'operation rejected'
                raise McpError(-32603,msg)
            if 'structuredContent' in result:return result['structuredContent']
            if 'content' in result and result['content']:
                try:return json.loads(result['content'][0].get('text','{}'))
                except Exception:return {'text':result['content'][0].get('text','')}
            return {}
        raise ValueError('unsupported component')

    def guard(self,principal):
        if time.time()>=principal.get('expires',2**63):raise ValueError('access token expired')
        current=strict_json(secure_read(self.config['config_path'])) if self.config.get('config_path') else self.config
        if not current.get('writes_enabled') or not self.client(principal['client']):raise ValueError('grant revoked')
        if not principal['scopes']<=set(self.client(principal['client'])['scopes']):raise ValueError('scopes revoked')

    def rpc(self,request,principal,headers=None):
        result=self._rpc(request,principal,headers)
        version=headers.get('MCP-Protocol-Version') if headers is not None else request.get('params',{}).get('_meta',{}).get('io.modelcontextprotocol/protocolVersion',LATEST)
        if isinstance(result,dict) and version==LATEST:result.setdefault('resultType','complete')
        return result

    def _rpc(self,request,principal,headers=None):
        if not isinstance(request,dict) or request.get('jsonrpc')!='2.0' or set(request)-{'jsonrpc','id','method','params'}:raise McpError(-32600,'invalid JSON-RPC request')
        if 'id' in request and (type(request['id']) not in (str,int) or isinstance(request['id'],str) and len(request['id'])>256):raise McpError(-32600,'invalid request id')
        method=request.get('method');params=request.get('params',{})
        if not isinstance(method,str) or not isinstance(params,dict):raise McpError(-32600,'invalid method/params')
        meta=params.get('_meta',{})
        if not isinstance(meta,dict):raise McpError(-32602,'invalid metadata')
        version=(headers.get('MCP-Protocol-Version') or (params.get('protocolVersion','2025-03-26') if method=='initialize' else '2025-03-26')) if headers is not None else meta.get('io.modelcontextprotocol/protocolVersion',params.get('protocolVersion',LATEST))
        if version not in VERSIONS:raise McpError(-32022,'Unsupported protocol version',data={'supported':list(VERSIONS),'requested':version})
        if headers is not None and version==LATEST:
            expected={'MCP-Protocol-Version':meta.get('io.modelcontextprotocol/protocolVersion'),'Mcp-Method':method}
            if method in {'tools/call','resources/read','prompts/get'}:expected['Mcp-Name']=params.get('name',params.get('uri'))
            for field,value in expected.items():
                actual=headers.get(field)
                if isinstance(actual,str) and actual.startswith('=?base64?') and actual.endswith('?='):
                    try:actual=base64.b64decode(actual[9:-2],validate=True).decode()
                    except Exception:raise McpError(-32020,'Malformed mirrored header')
                if actual is None or actual!=value:raise McpError(-32020,'Header mismatch')
            if not isinstance(meta.get('io.modelcontextprotocol/clientCapabilities'),dict):raise McpError(-32602,'clientCapabilities metadata required')
        if principal.get('expires',2**63)<=time.time():raise McpError(-32001,'token expired',401)
        if method=='initialize':
            if version==LATEST:raise McpError(-32601,'initialize is retired in 2026-07-28',404)
            return {'protocolVersion':version,'capabilities':{'tools':{},'resources':{}},'serverInfo':{'name':'ziokt-native','version':'2.0.0'}}
        if method=='notifications/initialized' and version!=LATEST:return None
        if method=='server/discover':
            from .build_info import registry_digest
            return {'supportedVersions':list(VERSIONS),'capabilities':{'tools':{},'resources':{}},'instructions':'Scoped native tools. Writes deduplicate automatically; review native plan digests before apply. Administrator-approved tools retain native identity and consensus checks.',
                    'serverInfo':{'name':'ziokt-native','version':'2.0.0','build':self.build_info},'tool_count':len(self.tools),'registry_sha256':registry_digest(self.tools.values())}
        if method=='ping':return {}
        if method=='tools/list':
            if principal.get('public'):
                tools=[{k:v for k,v in tool.items() if k!='scope'} for tool in self.tools.values()]
            else:
                client=self.client(principal['client'])
                if not client:raise McpError(-32001,'client revoked',401)
                tools=[{k:v for k,v in tool.items() if k!='scope'} for tool in self.tools.values() if self.permitted({'scopes':set(client['scopes'])},tool)]
            return {'tools':tools}
        if method=='tools/call':
            try:
                args=params.get('arguments',{})
                key=meta.get('ziokt/idempotencyKey')
                if not key and isinstance(args,dict):key=args.get('idempotency_key')
                if not key:
                    key=hashlib.sha256(encoded({'client':principal['client'],'token':principal.get('token_id','stdio'),'request':request.get('id'),'tool':params.get('name'),'arguments':args})).hexdigest()
                result=self.call(principal,params.get('name'),args,key)
            except ValueError:result={'resultType':'complete','content':[{'type':'text','text':'Invalid tool arguments or idempotency key'}],'isError':True}
            if version!=LATEST:result.pop('resultType',None)
            return result
        if method=='resources/list':
            return {'resources':[{'uri':'ziokt://components','name':'Configured native components','mimeType':'application/json'},{'uri':'ziokt://tools','name':'Scoped function catalog','mimeType':'application/json'}]}
        if method=='resources/read':
            if params.get('uri')=='ziokt://tools':
                if 'ziokt:read' not in principal['scopes']:raise McpError(-32602,'resource unavailable')
                tools=[{k:v for k,v in tool.items() if k!='scope'} for tool in self.tools.values() if self.permitted({'scopes':set(self.client(principal['client'])['scopes'])},tool)]
                return {'contents':[{'uri':'ziokt://tools','mimeType':'application/json','text':encoded({'tools':tools}).decode()}]}
            if params.get('uri')!='ziokt://components' or 'ziokt:read' not in principal['scopes']:raise McpError(-32602,'resource unavailable')
            return {'contents':[{'uri':'ziokt://components','mimeType':'application/json','text':encoded(self.execute(principal,'ziokt_components',{})).decode()}]}
        raise McpError(-32601,'method not found',404)


def http_handler(service):
    from http.server import BaseHTTPRequestHandler
    import html
    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def setup(self):super().setup();self.connection.settimeout(15)
        def log_message(self,*args):pass
        def reply(self,status,value,extra=None,mime='application/json'):
            raw=value if isinstance(value,bytes) else encoded(value)
            self.send_response(status)
            if self.headers.get('Origin') in service.config.get('origins',[]):
                self.send_header('Access-Control-Allow-Origin',self.headers['Origin']);self.send_header('Vary','Origin')
                self.send_header('Access-Control-Expose-Headers','WWW-Authenticate')
            self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(raw)))
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer')
            for key,val in (extra or {}).items():self.send_header(key,val)
            self.end_headers();self.wfile.write(raw)
        def error(self,error,request_id=None):
            body={'jsonrpc':'2.0','id':request_id,'error':{'code':error.code,'message':error.message}}
            if error.data is not None:body['error']['data']=error.data
            extra={}
            if error.status in (401,403):
                challenge='Bearer resource_metadata="'+service.config['issuer']+'/.well-known/oauth-protected-resource", scope="'+(error.data or {}).get('scope','ziokt:read')+'"'
                if error.status==403:challenge+=', error="insufficient_scope"'
                extra['WWW-Authenticate']=challenge
            self.reply(error.status,body,extra)
        def validate_origin(self):
            origin=self.headers.get('Origin')
            if origin is not None and origin not in service.config.get('origins',[]):raise McpError(-32001,'origin rejected',403)
            host=self.headers.get('Host','')
            bind_host=self.server.server_address[0];bind_host='['+bind_host+']' if ':' in bind_host else bind_host
            allowed=service.config.get('hosts',[urlsplit(service.config['issuer']).netloc,bind_host+':'+str(self.server.server_port)])
            if host not in allowed:raise McpError(-32001,'host rejected',403)
        def body(self):
            lengths=self.headers.get_all('Content-Length',[])
            if len(lengths)!=1 or not lengths[0].isdigit() or not 0<int(lengths[0])<=262144 or self.headers.get('Transfer-Encoding'):
                self.close_connection=True;raise McpError(-32600,'invalid framing',413)
            data=self.rfile.read(int(lengths[0]))
            if len(data)!=int(lengths[0]):raise McpError(-32600,'truncated body')
            return data
        def do_GET(self):
            try:
                self.validate_origin();path=urlsplit(self.path).path;issuer=service.config['issuer']
                if path in {'/.well-known/oauth-protected-resource','/.well-known/oauth-protected-resource/mcp'}:return self.reply(200,{'resource':issuer+'/mcp','authorization_servers':[issuer],'scopes_supported':service.scopes,'bearer_methods_supported':['header']})
                if path=='/.well-known/oauth-authorization-server':return self.reply(200,{'issuer':issuer,'authorization_endpoint':issuer+'/oauth/authorize','token_endpoint':issuer+'/oauth/token','revocation_endpoint':issuer+'/oauth/revoke','response_types_supported':['code'],'grant_types_supported':['authorization_code','refresh_token'],'token_endpoint_auth_methods_supported':['none'],'code_challenge_methods_supported':['S256'],'scopes_supported':service.scopes,'authorization_response_iss_parameter_supported':True,'client_id_metadata_document_supported':service.config.get('cimd_enabled',False)})
                if path=='/oauth/authorize':
                    q=parse_qs(urlsplit(self.path).query,strict_parsing=True)
                    if any(len(v)!=1 for v in q.values()):raise ValueError('duplicate OAuth field')
                    params={k:v[0] for k,v in q.items()};self.check_authorization(params)
                    # Explicit operator consent grants only the registered client's scopes.
                    auth_fields={'client_id','redirect_uri','response_type','code_challenge','code_challenge_method','scope','state','resource'}
                    fields=''.join('<input type="hidden" name="'+html.escape(k,quote=True)+'" value="'+html.escape(v,quote=True)+'">' for k,v in params.items() if k in auth_fields)
                    page='<html lang="en"><meta name="referrer" content="same-origin"><meta name="viewport" content="width=device-width"><title>Ziokt authorization</title><h1>Authorize '+html.escape(params['client_id'])+'</h1><p>Requested scopes: '+html.escape(params['scope'])+'</p><form method="post" action="/oauth/authorize">'+fields+'<label>Node administrator token <input type="password" name="admin_token" required autocomplete="off"></label><button type="submit">Approve scopes</button></form></html>'
                    # Chromium applies form-action to the 303 callback as well as the POST.
                    callback=quote(params['redirect_uri'].split('?',1)[0],safe=':/.-_~%[]')
                    return self.reply(200,page.encode(),{'Content-Security-Policy':"default-src 'none'; form-action 'self' "+callback+"; frame-ancestors 'none'; base-uri 'none'"},'text/html; charset=utf-8')
                if path=='/mcp':return self.reply(405,{'error':'POST required'},{'Allow':'POST'})
                return self.reply(404,{'error':'not found'})
            except McpError as exc:
                log.warning('MCP HTTP GET rejected path=%s code=%s',path if 'path' in locals() else 'unparsed',exc.code)
                self.error(exc)
            except (ValueError,KeyError) as exc:
                log.warning('MCP HTTP GET invalid_request path=%s error_type=%s query_field_count=%d',path if 'path' in locals() else 'unparsed',type(exc).__name__,len(parse_qs(urlsplit(self.path).query)))
                self.reply(400,{'error':'invalid_request'})
        def check_authorization(self,params):
            required={'client_id','redirect_uri','response_type','code_challenge','code_challenge_method','scope','state','resource'}
            # OAuth clients may send extension parameters; ignore unknown fields per RFC 6749.
            if not required<=set(params):raise ValueError('required authorization parameter missing')
            if 'id_token_hint' in params and len(params['id_token_hint'])>16384:raise ValueError('id_token_hint exceeds limit')
            if params['response_type']!='code' or params['code_challenge_method']!='S256' or not re.fullmatch('[A-Za-z0-9_-]{43}',params['code_challenge']):raise ValueError('PKCE S256 required')
            client=service.client(params['client_id'])
            if not client or params['redirect_uri'] not in client['redirect_uris'] or not params['state'] or len(params['state'])>512:raise ValueError('unregistered client')
            if params['resource']!=service.config['issuer']+'/mcp':raise ValueError('wrong resource audience')
            scopes=set(params['scope'].split())
            if not scopes or not scopes<=set(client['scopes']):raise ValueError('scope not granted')
            return scopes
        def do_POST(self):
            request_id=None
            path='unparsed';phase='request'
            try:
                self.validate_origin();path=urlsplit(self.path).path;raw=self.body()
                if path.startswith('/oauth/'):
                    phase='oauth_form'
                    if self.headers.get_content_type()!='application/x-www-form-urlencoded':raise ValueError('form encoding required')
                    form=parse_qs(raw.decode(),strict_parsing=True)
                    if any(len(v)!=1 for v in form.values()):raise ValueError('duplicate OAuth field')
                    params={k:v[0] for k,v in form.items()}
                    if path=='/oauth/authorize':
                        phase='oauth_authorize'
                        token=params.pop('admin_token','');scopes=self.check_authorization(params)
                        if not hmac.compare_digest(token,read_token(service.config['admin_token'])):raise McpError(-32001,'administrator authentication required',403)
                        code=secrets.token_urlsafe(48)
                        with database(service.db) as db:
                            db.execute('DELETE FROM codes WHERE expires<?',(int(time.time()),))
                            db.execute('INSERT INTO codes VALUES (?,?,?,?,?,?)',(hashlib.sha256(code.encode()).hexdigest(),params['client_id'],params['redirect_uri'],params['code_challenge'],json.dumps(sorted(scopes)),int(time.time())+120))
                        location=params['redirect_uri']+('&' if '?' in params['redirect_uri'] else '?')+urlencode({'code':code,'state':params['state'],'iss':service.config['issuer']})
                        return self.reply(303,b'',{'Location':location})
                    if path=='/oauth/token':
                        phase='oauth_token'
                        if params.get('resource')!=service.config['issuer']+'/mcp':return self.reply(400,{'error':'invalid_target'})
                        client_id=params.get('client_id');client=service.client(client_id)
                        if not client:return self.reply(400,{'error':'invalid_client'})
                        with service.lock, database(service.db) as db:
                            if params.get('grant_type')=='authorization_code':
                                verifier=params.get('code_verifier','')
                                if not re.fullmatch('[A-Za-z0-9._~-]{43,128}',verifier):raise ValueError('invalid verifier')
                                digest=hashlib.sha256(params.get('code','').encode()).hexdigest()
                                row=db.execute('SELECT client,redirect,challenge,scopes,expires FROM codes WHERE hash=?',(digest,)).fetchone()
                                challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
                                if not row or row[0]!=client_id or row[1]!=params.get('redirect_uri') or not hmac.compare_digest(row[2],challenge) or row[4]<=time.time():return self.reply(400,{'error':'invalid_grant'})
                                scopes=set(json.loads(row[3]));db.execute('DELETE FROM codes WHERE hash=?',(digest,))
                            elif params.get('grant_type')=='refresh_token':
                                digest=service.token_digest(params.get('refresh_token',''))
                                row=db.execute('SELECT client,scopes,expires FROM tokens WHERE hash=? AND refresh=1',(digest,)).fetchone()
                                if not row or row[0]!=client_id or row[2]<=time.time():return self.reply(400,{'error':'invalid_grant'})
                                scopes=set(json.loads(row[1]));db.execute('DELETE FROM tokens WHERE hash=?',(digest,))
                                if 'scope' in params:
                                    if not set(params['scope'].split())<=scopes:raise ValueError('cannot expand scopes')
                                    scopes=set(params['scope'].split())
                            else:return self.reply(400,{'error':'unsupported_grant_type'})
                        return self.reply(200,service.issue(client_id,scopes&set(client['scopes'])))
                    if path=='/oauth/revoke':
                        phase='oauth_revoke'
                        principal=service.auth(self.headers.get('Authorization'))
                        with database(service.db) as db:db.execute('DELETE FROM tokens WHERE hash=? AND client=?',(service.token_digest(params.get('token','')),principal['client']))
                        return self.reply(200,b'')
                    return self.reply(404,{'error':'not found'})
                if path!='/mcp':return self.reply(404,{'error':'not found'})
                phase='mcp_rpc'
                if self.headers.get_content_type()!='application/json':raise McpError(-32600,'JSON required',415)
                accept=self.headers.get('Accept','')
                if accept and not all(t in accept for t in ('application/json','text/event-stream')):raise McpError(-32600,'Accept must list JSON and SSE',406)
                request=json.loads(raw,object_pairs_hook=unique);request_id=request.get('id') if isinstance(request,dict) else None
                # ChatGPT deliberately bootstraps MCP without credentials, then applies
                # per-tool OAuth schemes from tools/list before authenticating tool calls.
                unauthenticated_bootstrap=isinstance(request,dict) and request.get('method') in {'initialize','tools/list','server/discover','notifications/initialized','ping'}
                principal=({'client':'__public_bootstrap__','scopes':set(),'expires':2**63,'public':True} if unauthenticated_bootstrap and not self.headers.get('Authorization') else service.auth(self.headers.get('Authorization')))
                result=service.rpc(request,principal,self.headers)
                if 'id' not in request:return self.reply(202,b'')
                return self.reply(200,{'jsonrpc':'2.0','id':request_id,'result':result})
            except McpError as exc:
                log.warning('MCP HTTP POST rejected path=%s phase=%s code=%s',path,phase,exc.code)
                self.error(exc,request_id)
            except (ValueError,KeyError,UnicodeError) as exc:
                log.warning('MCP HTTP POST invalid_request path=%s phase=%s error_type=%s',path,phase,type(exc).__name__)
                self.reply(400,{'error':'invalid_request'})
            except Exception as exc:
                log.error('MCP HTTP POST unavailable path=%s phase=%s error_type=%s',path,phase,type(exc).__name__)
                self.reply(503,{'error':'component_unavailable'})
        def do_OPTIONS(self):
            try:
                self.validate_origin()
                self.reply(204,b'',{'Access-Control-Allow-Methods':'POST, GET, OPTIONS','Access-Control-Allow-Headers':'Authorization, Content-Type, Accept, MCP-Protocol-Version, Mcp-Method, Mcp-Name','Access-Control-Max-Age':'600'})
            except McpError as exc:self.error(exc)
        def do_DELETE(self):self.reply(405,b'',{'Allow':'POST'})
    return Handler


def register(sub):
    parser=sub.add_parser('mcp',help='authenticated native MCP tools and resources')
    actions=parser.add_subparsers(dest='mcp_action',required=True)
    for name in ('serve','stdio','catalog','telegram-worker'):
        action=actions.add_parser(name);action.add_argument('--config',type=Path,required=True)
    token=actions.add_parser('issue-token');token.add_argument('--config',type=Path,required=True);token.add_argument('--client',required=True)


def execute(args):
    config=strict_json(secure_read(args.config));config['config_path']=str(args.config.resolve())
    if config.get('schema')!='ziokt.mcp.v1':raise ValueError('invalid MCP configuration')
    from .endpoint_config import https_origin,local_listener
    https_origin(config['issuer'])
    if args.mcp_action=='telegram-worker':
        from .telegram_worker import TelegramWorker
        TelegramWorker(args.config).run();return {}
    service=Service(config)
    if args.mcp_action=='catalog':return {'tools':list(service.tools.values()),'scopes':service.scopes,'protocols':VERSIONS}
    if args.mcp_action=='issue-token':
        client=config['clients'][args.client]
        # Local owner-only administration command; credentials must go into a 0600 file.
        return service.issue(args.client,set(client['scopes']))
    if args.mcp_action=='serve':
        server=Server((local_listener(config.get('listen','127.0.0.1')),config.get('port',8186)),http_handler(service))
        try:server.serve_forever()
        finally:server.server_close();service.close()
        return {}
    client=os.environ.get('ZIOKT_MCP_CLIENT')
    if client not in config['clients']:raise ValueError('explicit ZIOKT_MCP_CLIENT required')
    principal=service.auth('Bearer '+os.environ.get('ZIOKT_MCP_TOKEN',''))
    if principal['client']!=client:raise ValueError('MCP client token mismatch')
    for _ in range(4096):
        line=sys.stdin.buffer.readline(262145)
        if not line:break
        principal=service.auth('Bearer '+os.environ.get('ZIOKT_MCP_TOKEN',''))
        if len(line)>262144:raise ValueError('message budget exceeded')
        request_id=None
        try:
            request=json.loads(line,object_pairs_hook=unique);request_id=request.get('id')
            result=service.rpc(request,principal)
            if 'id' not in request:continue
            response={'jsonrpc':'2.0','id':request_id,'result':result}
        except McpError as exc:response={'jsonrpc':'2.0','id':request_id,'error':{'code':exc.code,'message':exc.message}}
        except Exception:response={'jsonrpc':'2.0','id':request_id,'error':{'code':-32600,'message':'invalid request'}}
        sys.stdout.buffer.write(encoded(response)+b'\n');sys.stdout.buffer.flush()
    service.close()
    return None
