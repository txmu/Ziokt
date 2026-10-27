"""Account-isolated internet mail, bounded recurring sync and unified inbox."""
from pathlib import Path
import threading
from .mail_internet import InternetMail
from .protocol import ProtocolError

class InternetAccounts:
    def __init__(self,config,state):
        if not isinstance(config,dict) or set(config)-{'accounts','default_account','sync_interval'}:raise ProtocolError('INVALID_CONFIG','account collection fields')
        accounts=config.get('accounts')
        if not isinstance(accounts,list) or not 1<=len(accounts)<=8:raise ProtocolError('INVALID_CONFIG','1..8 internet accounts required')
        self.accounts={}
        for item in accounts:
            name=item.get('account') if isinstance(item,dict) else None
            if name in self.accounts:raise ProtocolError('INVALID_CONFIG','duplicate internet account')
            channel=InternetMail(item,Path(state)/str(name));self.accounts[name]=channel
        self.default=config.get('default_account',accounts[0]['account'])
        if self.default not in self.accounts:raise ProtocolError('INVALID_CONFIG','default internet account missing')
        self.interval=config.get('sync_interval',60)
        if type(self.interval)is not int or not 30<=self.interval<=3600:raise ProtocolError('INVALID_CONFIG','sync interval 30..3600')
        self.stop=threading.Event();self.worker=None;self.last_sync={};self.sync_lock=threading.Lock()
    def send(self,*args,internet_account=None,**kwargs):
        account=self.accounts.get(internet_account or self.default)
        if account is None:raise ProtocolError('POLICY_DENIED','mail account is not assigned')
        result=account.send(*args,**kwargs);result['account']=account.config['account'];return result
    def status(self):return {'accounts':{k:a.status() for k,a in self.accounts.items()},'default_account':self.default,'automatic_sync':bool(self.worker and self.worker.is_alive()),'last_sync':dict(self.last_sync)}
    def inbox(self,recipient):
        return sorted([{**item,'id':name+':'+item['id']} for name,a in self.accounts.items() for item in a.inbox(recipient)],key=lambda item:item['received_at'],reverse=True)[:50]
    def flush(self,limit=10):return {k:a.flush(limit) for k,a in self.accounts.items() if a.config.get('smtp')}
    def poll(self,limit=10):return {k:a.poll(limit) for k,a in self.accounts.items() if a.config.get('imap')}
    def resolve(self,message_id,decision):
        if ':' not in message_id:raise ProtocolError('INVALID_REQUEST','account:message-id required')
        name,identity=message_id.split(':',1)
        if name not in self.accounts:raise ProtocolError('POLICY_DENIED','unknown account')
        return self.accounts[name].resolve(identity,decision)
    def import_attachment(self,account,identity):
        if account not in self.accounts:raise ProtocolError('POLICY_DENIED','unknown account')
        from .mail_receive import import_attachment
        return import_attachment(self.accounts[account],identity)
    def sync_once(self):
        if not self.sync_lock.acquire(blocking=False):return
        try:
            for name,account in self.accounts.items():
                result={}
                for method,kind in (('flush','smtp'),('poll','imap')):
                    if not account.config.get(kind):continue
                    authorize=getattr(self,'authorization',None)
                    if authorize and not authorize('mail:write' if kind=='smtp' else 'mail:read'):result[method]='authorization_revoked';continue
                    try:getattr(account,method)(5);result[method]='ok'
                    except Exception as exc:result[method]=type(exc).__name__
                self.last_sync[name]=result
        finally:self.sync_lock.release()
    def start(self):
        if self.worker and self.worker.is_alive():return
        def run():
            while not self.stop.is_set():self.sync_once();self.stop.wait(self.interval)
        self.worker=threading.Thread(target=run,name='internet-mail-sync',daemon=True);self.worker.start()
    def close(self):
        self.stop.set()
        if self.worker:self.worker.join(timeout=25)


def configured(config,state):
    if 'accounts' in config:return InternetAccounts(config,state)
    return InternetMail(config,state)
