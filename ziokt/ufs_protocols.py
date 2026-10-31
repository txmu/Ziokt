"""UFS protocol hub: native HTTP/WebDAV, FTP/FTPS, Gopher, Telnet, SFTP and NNTP.

Protocols share authenticated accounts and descriptor-confined home directories.
Gopher serves a separate public directory unless an encrypted capability selector
is used. Telnet exposes the UFS command set, never an operating-system shell.
"""
import argparse,asyncio,base64,hashlib,hmac,importlib,io,ipaddress,json,os,posixpath,secrets,shlex,signal,socket,socketserver,ssl,stat,sys,threading,time
from pathlib import Path
from urllib.parse import quote


def native():
    directory=Path(__file__).resolve().parents[1]/'companions/ufsdcpm/src'
    if directory.is_dir() and str(directory) not in sys.path:sys.path.insert(0,str(directory))
    return importlib.import_module('ufsultra'),importlib.import_module('ufs_http_security')


class Files:
    def __init__(self,confined,maximum):self.store=confined;self.maximum=maximum
    def parts(self,path):
        if not isinstance(path,str) or '\\' in path or any(ord(c)<32 for c in path) or '..' in path.split('/'):raise PermissionError('UFS_PATH')
        return self.store.parts('/'+'/'.join(quote(p,safe='') for p in path.strip('/').split('/') if p))
    def open(self,path,flags=os.O_RDONLY):
        parts=self.parts(path)
        if not parts:raise IsADirectoryError(path)
        with self.store.lock,self.store.directory(parts[:-1]) as parent:
            fd=os.open(parts[-1],flags|os.O_NOFOLLOW|os.O_NONBLOCK,0o600,dir_fd=parent)
        if not stat.S_ISREG(os.fstat(fd).st_mode):os.close(fd);raise PermissionError('UFS_REGULAR_FILE')
        return fd
    def info(self,path):return self.store.info(self.parts(path))
    def entries(self,path):return [(name,info) for name,info in self.store.entries(self.parts(path),4096) if not any(ord(c)<32 for c in name)]
    def remove(self,path):self.store.delete(self.parts(path))
    def mkdir(self,path):self.store.mkdir(self.parts(path))
    def rename(self,old,new):
        left,right=self.parts(old),self.parts(new)
        if not left or not right:raise PermissionError('UFS_ROOT_IMMUTABLE')
        self.store.info(left)
        with self.store.lock,self.store.directory(left[:-1]) as src,self.store.directory(right[:-1]) as dst:
            try:self.store.info(right)
            except FileNotFoundError:pass
            os.rename(left[-1],right[-1],src_dir_fd=src,dst_dir_fd=dst)
    def chmod(self,path,mode):
        fd=self.open(path)
        try:os.fchmod(fd,mode&0o600)
        finally:os.close(fd)
    def utime(self,path,times):
        fd=self.open(path)
        try:os.utime(fd,times)
        finally:os.close(fd)


class LimitedFile:
    def __init__(self,stream,maximum,append=False):self.stream=stream;self.maximum=maximum;self.append=append
    def write(self,data):
        size=os.fstat(self.stream.fileno()).st_size
        if max(size,(size if self.append else self.stream.tell())+len(data))>self.maximum:raise OSError('UFS_UPLOAD_LIMIT')
        return self.stream.write(data)
    def __getattr__(self,key):return getattr(self.stream,key)
    def __enter__(self):return self
    def __exit__(self,*args):self.close()


class Hub:
    def __init__(self,config,*,http_handler=None,include_http=True):
        config=dict(config)
        if 'protocols' not in config:
            config['protocols']={name:dict(config[name]) for name in ('ftp','ftps','gopher','telnet','sftp','nntp') if isinstance(config.get(name),dict)}
        if not isinstance(config['protocols'],dict) or any(not isinstance(item,dict) for item in config['protocols'].values()):raise ValueError('typed UFS protocol configuration required')
        for item in config['protocols'].values():
            if 'tls_cert' in item:item.setdefault('cert',item['tls_cert'])
            if 'tls_key' in item:item.setdefault('key',item['tls_key'])
            if isinstance(item.get('passive_ports'),str):
                low,high=map(int,item['passive_ports'].split('-'));item['passive_ports']=[low,high+1]
        self.ufs,self.security=native();self.config=self.ufs.validated_config(config)
        self.accounts=self.ufs.auth_accounts(self.config);root=Path(self.config['root_dir'])
        roots=self.config.get('account_roots') or {user:str(root/'accounts'/user) for user in self.accounts}
        if set(roots)!=set(self.accounts):raise ValueError('UFS_EXACT_ACCOUNT_ROOTS')
        if any(not Path(path).is_absolute() for path in roots.values()):raise ValueError('absolute account roots required')
        served=[Path(path).resolve() for path in [*roots.values(),self.config.get('public_root',str(root/'public'))]]
        private=[self.config['log_file'],self.config['ssl_cert']]
        for item in self.config['protocols'].values():private.extend(item[key] for key in ('key','host_key','cert') if item.get(key))
        if any(Path(path).resolve().is_relative_to(directory) for path in private for directory in served):raise ValueError('UFS private keys, certificates and logs must remain outside served roots')
        self.config['account_roots']=roots
        self.files={user:Files(self.security.ConfinedFiles(path),self.config['max_upload']) for user,path in roots.items()}
        self.public=Files(self.security.ConfinedFiles(self.config.get('public_root',str(root/'public'))),self.config['max_upload'])
        self.host=self.config.get('protocol_host',self.config.get('host','127.0.0.1'));self.include_http=include_http;self.http_handler=http_handler or self.ufs.UltraHandler
        self.servers=[];self.threads=[];self.transports=set();self.lock=threading.RLock();self.stopping=asyncio.Event();self.inventory={};self.handles={};self.monitor=None;self.news=None
        self.protocols=self.config.get('protocols',{})
        if not isinstance(self.protocols,dict) or set(self.protocols)-{'ftp','ftps','gopher','telnet','sftp','nntp'}:raise ValueError('UFS_PROTOCOLS')
        self.async_slots=threading.BoundedSemaphore(self.config['max_conn'])
    def writable(self,user):return self.accounts[user]['role'] in {'user','admin'} and self.config['upload']
    def authenticate(self,user,password):
        account=self.accounts.get(user)
        return bool(account and hmac.compare_digest(account['password'].encode(),password.encode()))
    def permitted_ip(self,host):
        import ipaddress
        value=ipaddress.ip_address(host)
        return host not in self.config['blacklist'] and any(value in ipaddress.ip_network(n) for n in self.config.get('protocol_ip_whitelist',self.config['ip_whitelist']))
    def tls(self,item,protocol):
        enabled=item.get('tls',protocol in {'ftps','telnet','nntp'})
        if not enabled:return None
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.minimum_version=ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(item.get('cert',self.config['ssl_cert']),item.get('key'));return context
    def start_thread(self,label,server,target=None):
        self.servers.append(server);thread=threading.Thread(target=target or server.serve_forever,name='ufs-'+label,daemon=True);thread.start();self.threads.append(thread)
        self.inventory[label]={'host':server.socket.getsockname()[0],'port':server.socket.getsockname()[1]}
        self.handles[label]=(server,thread)
    def ftp(self,label,item):
        from pyftpdlib.authorizers import DummyAuthorizer,AuthenticationFailed
        from pyftpdlib.handlers import FTPHandler,TLS_FTPHandler
        from pyftpdlib.filesystems import AbstractedFS
        from pyftpdlib.servers import FTPServer
        from pyftpdlib.ioloop import IOLoop
        hub=self;encrypted=label=='ftps' or item.get('tls',False)
        if not encrypted and not ipaddress.ip_address(self.host).is_loopback and not item.get('allow_plaintext',False):raise ValueError('use FTP explicit TLS on public listeners, or terminate encryption in an owner-configured tunnel')
        class Auth(DummyAuthorizer):
            def validate_authentication(self,username,password,handler):
                if username=='anonymous' and hub.config.get('allow_anonymous',False):return
                if not hub.authenticate(username,password):raise AuthenticationFailed('Authentication failed')
        auth=Auth()
        for user,files in self.files.items():auth.add_user(user,'unused-authenticator',str(files.store.root),perm='elradfmwMT' if self.writable(user) else 'elr')
        if self.config.get('allow_anonymous',False):auth.add_anonymous(str(self.public.store.root),perm='elr')
        class FS(AbstractedFS):
            def __init__(self,root,channel):super().__init__(root,channel);self.io=hub.public if channel.username=='anonymous' else hub.files[channel.username]
            def relative(self,path):return '/'+str(Path(path).absolute().relative_to(self.root)).replace(os.sep,'/').removeprefix('./') if Path(path).absolute()!=Path(self.root) else '/'
            def realpath(self,path):self.io.parts(self.relative(path));return os.path.normpath(path)
            def open(self,path,mode):
                flags=os.O_RDONLY if mode.startswith('r') and '+' not in mode else os.O_RDWR
                if 'w' in mode:flags|=os.O_CREAT|os.O_TRUNC
                if 'a' in mode:flags|=os.O_CREAT|os.O_APPEND
                result=os.fdopen(self.io.open(self.relative(path),flags),mode)
                return LimitedFile(result,self.io.maximum,'a' in mode)
            def listdir(self,path):return [name for name,_ in self.io.entries(self.relative(path))]
            def stat(self,path):return self.io.info(self.relative(path))
            lstat=stat
            def isfile(self,path):
                try:return stat.S_ISREG(self.stat(path).st_mode)
                except (OSError,ValueError,PermissionError):return False
            def isdir(self,path):
                try:return stat.S_ISDIR(self.stat(path).st_mode)
                except (OSError,ValueError,PermissionError):return False
            def lexists(self,path):return self.isfile(path) or self.isdir(path)
            def islink(self,path):return False
            def chdir(self,path):
                if not self.isdir(path):raise NotADirectoryError(path)
                self._cwd=self.fs2ftp(path)
            def remove(self,path):self.io.remove(self.relative(path))
            rmdir=remove
            def mkdir(self,path):self.io.mkdir(self.relative(path))
            def rename(self,src,dst):self.io.rename(self.relative(src),self.relative(dst))
            def chmod(self,path,mode):self.io.chmod(self.relative(path),mode)
            def utime(self,path,timeval):self.io.utime(self.relative(path),(timeval,timeval))
            def getsize(self,path):return self.stat(path).st_size
            def getmtime(self,path):return self.stat(path).st_mtime
        class Handler(TLS_FTPHandler if encrypted else FTPHandler):
            authorizer=auth;abstracted_fs=FS;timeout=30;auth_failed_timeout=1;max_login_attempts=3;permit_foreign_addresses=False
            def on_connect(self):
                if not hub.permitted_ip(self.remote_ip):self.respond('421 Address denied');self.close_when_done()
        if encrypted:
            Handler.certfile=item.get('cert',self.config['ssl_cert']);Handler.keyfile=item.get('key');Handler.tls_control_required=True;Handler.tls_data_required=True
        if 'passive_ports' in item:Handler.passive_ports=range(*item['passive_ports'])
        Handler.masquerade_address=item.get('masquerade_address')
        server=FTPServer((self.host,item['port']),Handler,ioloop=IOLoop());server.max_cons=self.config['max_conn'];server.max_cons_per_ip=min(16,self.config['max_conn'])
        self.start_thread(label,server,lambda:server.serve_forever(timeout=.1,blocking=True,handle_exit=False))
    async def gopher(self,item):
        context=self.tls(item,'gopher');hub=self
        async def serve(reader,writer):
            admitted=hub.async_slots.acquire(False)
            try:
                if not admitted:return
                if not hub.permitted_ip(writer.get_extra_info('peername')[0]):return
                line=await asyncio.wait_for(reader.readline(),10)
                if len(line)>2048 or not line.endswith(b'\n'):raise ValueError('selector budget')
                selector=line.decode('utf-8').rstrip('\r\n');query=''
                if '\t' in selector:selector,query=selector.split('\t',1)
                files=hub.public;prefix=''
                if selector.startswith('/auth/'):
                    if context is None:raise PermissionError('private Gopher selectors require TLS')
                    _,_,token,selector=selector.split('/',3);matched=None
                    for user,value in item.get('tokens',{}).items():
                        if user in hub.files and len(value)>=32 and hmac.compare_digest(value,token):matched=user
                    if matched is None:raise PermissionError('capability')
                    files=hub.files[matched];selector='/'+selector;prefix='/auth/'+token
                path='/'+selector.lstrip('/') if selector else '/';search=path=='/search'
                if search or stat.S_ISDIR(files.info(path).st_mode):
                    directory='/' if search else path
                    if path=='/' and files is hub.public:
                        for entry in item.get('menu_items',[]):
                            values=[entry['type']+entry['display'],entry['selector'],entry['host'],str(entry['port'])]
                            if any(any(ord(c)<32 for c in value) for value in values):raise ValueError('Gopher menu fields')
                            writer.write(('\t'.join(values)+'\r\n').encode())
                    for name,info in files.entries(directory):
                        if any(ord(c)<32 for c in name) or (search and query.casefold() not in name.casefold()):continue
                        kind='1' if stat.S_ISDIR(info.st_mode) else '0' if name.endswith(('.txt','.md')) else '9'
                        selected=prefix+posixpath.join(directory,name)
                        writer.write((kind+name+'\t'+selected+'\t'+item.get('hostname',hub.host)+'\t'+str(hub.inventory['gopher']['port'])+'\r\n').encode())
                    writer.write(b'.\r\n')
                else:
                    with files.store.open(files.parts(path)) as source:
                        sent=0
                        if path.endswith(('.txt','.md')):
                            beginning=True;pending=b''
                            while raw:=source.readline(65536):
                                sent+=len(raw)
                                if sent>files.maximum:raise ValueError('transfer budget')
                                data=pending+raw;pending=b''
                                if data.endswith(b'\r'):data=data[:-1];pending=b'\r'
                                if not data:continue
                                if beginning and data.startswith(b'.'):writer.write(b'.')
                                if data.endswith(b'\n'):writer.write(data[:-1].removesuffix(b'\r')+b'\r\n');beginning=True
                                else:writer.write(data);beginning=False
                                await asyncio.wait_for(writer.drain(),10)
                            if pending or not beginning:writer.write(b'\r\n')
                            writer.write(b'.\r\n')
                        else:
                            while data:=source.read(65536):
                                sent+=len(data)
                                if sent>files.maximum:raise ValueError('transfer budget')
                                writer.write(data);await asyncio.wait_for(writer.drain(),10)
                await writer.drain()
            except (OSError,ValueError,PermissionError,UnicodeError,asyncio.TimeoutError):writer.write(b'3Request rejected\terror\tlocalhost\t1\r\n.\r\n')
            finally:
                if admitted:hub.async_slots.release()
                writer.close();await writer.wait_closed()
        server=await asyncio.start_server(serve,self.host,item['port'],ssl=context,limit=4096);self.servers.append(server);self.inventory['gopher']={'host':self.host,'port':server.sockets[0].getsockname()[1]}
        self.handles['gopher']=(server,None)
    async def telnet(self,item):
        import telnetlib3
        hub=self
        if not item.get('tls',True) and not ipaddress.ip_address(self.host).is_loopback and not item.get('allow_plaintext',False):raise ValueError('use Telnet over TLS for a public authenticated listener')
        async def shell(reader,writer):
            admitted=hub.async_slots.acquire(False)
            async def line(prompt):
                writer.write(prompt);await writer.drain();value=await asyncio.wait_for(reader.readline(),30)
                if not value or len(value)>2048:raise ValueError('line budget')
                return value.rstrip('\r\n')
            try:
                if not admitted:return
                if not hub.permitted_ip(writer.get_extra_info('peername')[0]):return
                writer.write(item.get('banner','UltraFileServer Telnet')+'\r\n');user=None
                for _ in range(3):
                    username=await line('Username: ');password=await line('Password: ')
                    if hub.authenticate(username,password):user=username;break
                    writer.write('Authentication failed\r\n')
                if user is None:return
                files=hub.files[user];writer.write('Authenticated\r\n')
                while True:
                    command=await line('ufs> ');args=shlex.split(command);op=args[0].lower() if args else ''
                    if op in {'exit','quit'}:writer.write('Bye\r\n');break
                    if op=='help':result='help stats files ls get put mkdir rm mv exit'
                    elif op=='stats':result=json.dumps({'files':len(files.entries('/')),'protocols':list(hub.inventory)})
                    elif op in {'files','ls'}:result='\r\n'.join(name for name,_ in files.entries(args[1] if len(args)>1 else '/'))
                    elif op=='get' and len(args)==2:
                        with files.store.open(files.parts(args[1])) as source:data=source.read(min(files.maximum,65536)+1)
                        if len(data)>min(files.maximum,65536):raise ValueError('terminal transfer budget')
                        result=base64.b64encode(data).decode()
                    elif op in {'put','mkdir','rm','mv'}:
                        if not hub.writable(user):raise PermissionError('read-only account')
                        if op=='put' and len(args)==3:
                            data=base64.b64decode(args[2],validate=True)
                            if len(data)>min(files.maximum,65536):raise ValueError('terminal transfer budget')
                            files.store.put(files.parts(args[1]),io.BytesIO(data),len(data))
                        elif op=='mkdir' and len(args)==2:files.mkdir(args[1])
                        elif op=='rm' and len(args)==2:files.remove(args[1])
                        elif op=='mv' and len(args)==3:files.rename(args[1],args[2])
                        else:raise ValueError('command arguments')
                        result='OK'
                    else:result='Unknown command'
                    writer.write(result+'\r\n')
            except (OSError,ValueError,PermissionError,asyncio.TimeoutError):writer.write('Request rejected\r\n')
            finally:
                if admitted:hub.async_slots.release()
                writer.close()
        server=await telnetlib3.create_server(host=self.host,port=item['port'],shell=shell,encoding='utf8',limit=4096,timeout=60,connect_maxwait=1,ssl=self.tls(item,'telnet'));self.servers.append(server);self.inventory['telnet']={'host':self.host,'port':server.sockets[0].getsockname()[1]}
        self.handles['telnet']=(server,None)
    def sftp(self,item):
        import paramiko
        hub=self;keypath=Path(item.get('host_key',str(Path(self.config['log_file']).parent/'sftp-host.key')))
        if any(keypath.resolve().is_relative_to(files.store.root.resolve()) for files in [self.public,*self.files.values()]):raise ValueError('private SSH host key must be outside served roots')
        if not keypath.exists():
            keypath.parent.mkdir(parents=True,exist_ok=True,mode=0o700);key=paramiko.RSAKey.generate(3072);key.write_private_key_file(str(keypath));keypath.chmod(0o600)
        if keypath.is_symlink() or keypath.stat().st_mode&0o077:raise ValueError('private stable SSH host key required')
        key=paramiko.RSAKey(filename=str(keypath))
        class Auth(paramiko.ServerInterface):
            user=None
            def check_auth_password(self,user,password):
                if hub.authenticate(user,password):self.user=user;return paramiko.AUTH_SUCCESSFUL
                return paramiko.AUTH_FAILED
            def get_allowed_auths(self,user):return 'password'
            def check_channel_request(self,kind,channel):return paramiko.OPEN_SUCCEEDED if kind=='session' and self.user else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED
        class Handle(paramiko.SFTPHandle):
            def stat(self):return paramiko.SFTPAttributes.from_stat(os.fstat((getattr(self,'readfile',None) or self.writefile).fileno()))
        class SFTP(paramiko.SFTPServerInterface):
            def __init__(self,server,*args,**kwargs):super().__init__(server,*args,**kwargs);self.user=server.user;self.files=hub.files[self.user]
            def error(self,call,*args):
                try:return call(*args)
                except (OSError,ValueError,PermissionError) as error:return paramiko.SFTPServer.convert_errno(getattr(error,'errno',None) or 13)
            def stat(self,path):return self.error(lambda:paramiko.SFTPAttributes.from_stat(self.files.info(path)))
            lstat=stat
            def list_folder(self,path):
                def listing():
                    rows=[]
                    for name,info in self.files.entries(path):
                        row=paramiko.SFTPAttributes.from_stat(info);row.filename=name;rows.append(row)
                    return rows
                return self.error(listing)
            def open(self,path,flags,attr):
                def opened():
                    writing=flags&os.O_ACCMODE!=os.O_RDONLY or flags&(os.O_CREAT|os.O_TRUNC|os.O_APPEND)
                    if writing and not hub.writable(self.user):raise PermissionError('read-only account')
                    mode='r+b' if flags&os.O_ACCMODE==os.O_RDWR else 'wb' if writing else 'rb'
                    stream=LimitedFile(os.fdopen(self.files.open(path,flags),mode),self.files.maximum,bool(flags&os.O_APPEND));handle=Handle(flags)
                    if flags&os.O_ACCMODE!=os.O_WRONLY:handle.readfile=stream
                    if writing:handle.writefile=stream
                    return handle
                return self.error(opened)
            def mutate(self,call,*args):
                if not hub.writable(self.user):return paramiko.SFTP_PERMISSION_DENIED
                result=self.error(call,*args);return paramiko.SFTP_OK if result is None else result
            def remove(self,path):return self.mutate(self.files.remove,path)
            rmdir=remove
            def mkdir(self,path,attr):return self.mutate(self.files.mkdir,path)
            def rename(self,old,new):return self.mutate(self.files.rename,old,new)
            def chattr(self,path,attr):
                def change():
                    if attr.st_uid is not None or attr.st_gid is not None:raise PermissionError('host ownership is outside UFS')
                    if attr.st_mode is not None:self.files.chmod(path,attr.st_mode)
                    if attr.st_atime is not None and attr.st_mtime is not None:self.files.utime(path,(attr.st_atime,attr.st_mtime))
                    if attr.st_size is not None:
                        if not 0<=attr.st_size<=self.files.maximum:raise ValueError('file size budget')
                        fd=self.files.open(path,os.O_WRONLY)
                        try:os.ftruncate(fd,attr.st_size)
                        finally:os.close(fd)
                return self.mutate(change)
        class Request(socketserver.BaseRequestHandler):
            def handle(self):
                if not hub.permitted_ip(self.client_address[0]):return
                transport=paramiko.Transport(self.request);transport.banner_timeout=10;transport.auth_timeout=15
                with hub.lock:hub.transports.add(transport)
                try:
                    transport.add_server_key(key);transport.set_subsystem_handler('sftp',paramiko.SFTPServer,SFTP);transport.start_server(server=Auth())
                    while transport.is_active() and not hub.stopping.is_set():time.sleep(.1)
                except (OSError,paramiko.SSHException):pass
                finally:
                    transport.close()
                    with hub.lock:hub.transports.discard(transport)
        server=BoundedTCP((self.host,item['port']),Request,self.config['max_conn']);self.start_thread('sftp',server)
        self.inventory['sftp']['host_key_sha256']=base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip('=')
    def nntp(self,item):
        from .content_fabric import Fabric
        from .netnews_nntp import server
        self.news=Fabric(Path(self.config['log_file']).parent/'news')
        tokens=[]
        for user,account in self.accounts.items():
            owner=user;scopes=['netnews:read']+(['netnews:write'] if self.writable(user) else [])
            tokens.append({'account':owner,'token':account['password'],'scopes':scopes})
            existing={row['name'] for row in self.news.groups(owner)['items']}
            for group in item.get('groups',['ufs.announce','ufs.discuss']):
                if group not in existing:self.news.create_group(owner,group,visibility='public')
        settings={'listen':self.host,'port':item['port'],'allow_loopback_auth':True,'anonymous_read':item.get('anonymous_read',False)}
        if item.get('tls',True):settings['tls']={'cert':item.get('cert',self.config['ssl_cert']),'key':item.get('key')}
        self.start_thread('nntp',server(self.news,settings,tokens))
    async def start(self):
        try:
            if self.include_http:
                server=self.ufs.UltraServer((self.config.get('host','127.0.0.1'),self.config['port']),self.http_handler,config=self.config);server.protocol_hub=self;self.start_thread('https' if self.config['ssl'] else 'http',server)
            for label,item in self.protocols.items():
                if item.get('enabled',True) is not True:continue
                if type(item.get('port')) is not int or not 0<=item['port']<=65535:raise ValueError('bounded protocol port required')
                if label in {'ftp','ftps'}:self.ftp(label,item)
                elif label=='gopher':await self.gopher(item)
                elif label=='telnet':await self.telnet(item)
                elif label=='sftp':self.sftp(item)
                elif label=='nntp':self.nntp(item)
            self.monitor=asyncio.create_task(self.watch())
            return self.snapshot()
        except BaseException:await self.close();raise
    def snapshot(self):
        result={}
        for name,value in self.inventory.items():
            server,thread=self.handles[name]
            try:
                active=server.is_serving() if thread is None else thread.is_alive() and bool(server.socket.getsockopt(socket.SOL_SOCKET,socket.SO_ACCEPTCONN))
            except (OSError,AttributeError):active=False
            result[name]={**value,'is_listening':bool(active)}
        return result
    async def watch(self):
        while not self.stopping.is_set():
            await asyncio.sleep(1)
            if not self.stopping.is_set() and any(not value['is_listening'] for value in self.snapshot().values()):self.stopping.set()
    async def close(self):
        self.stopping.set()
        if self.monitor is not None:
            self.monitor.cancel()
            try:await self.monitor
            except asyncio.CancelledError:pass
            self.monitor=None
        with self.lock:
            for transport in list(self.transports):transport.close()
        for server in reversed(self.servers):
            if hasattr(server,'close_all'):await asyncio.to_thread(server.close_all)
            elif hasattr(server,'wait_closed'):server.close();await server.wait_closed()
            else:await asyncio.to_thread(server.shutdown);server.server_close()
        for thread in self.threads:thread.join(5)
        for files in [self.public,*self.files.values()]:files.store.close()
        if self.news:self.news.close()
        self.servers=[]


class BoundedTCP(socketserver.ThreadingMixIn,socketserver.TCPServer):
    allow_reuse_address=True;daemon_threads=True
    def __init__(self,address,handler,maximum):self.slots=threading.BoundedSemaphore(maximum);super().__init__(address,handler)
    def process_request(self,request,address):
        if not self.slots.acquire(False):request.close();return
        try:super().process_request(request,address)
        except BaseException:self.slots.release();raise
    def process_request_thread(self,request,address):
        try:super().process_request_thread(request,address)
        finally:self.slots.release()


async def run(config):
    from .protocol import secure_read,strict_json
    hub=Hub(strict_json(secure_read(config,256*1024),256*1024))
    loop=asyncio.get_running_loop()
    for name in ('SIGINT','SIGTERM'):
        try:loop.add_signal_handler(getattr(signal,name),hub.stopping.set)
        except NotImplementedError:pass
    print(json.dumps({'schema':'ziokt.ufs-protocols.v1','listeners':await hub.start()}),flush=True)
    try:await hub.stopping.wait()
    finally:await hub.close()


def status(path):
    """Query the owner-configured native server using its Digest credentials."""
    import urllib.request
    from .protocol import secure_read,strict_json
    config=strict_json(secure_read(path,256*1024),256*1024)
    settings=config.get('ufs',config);auth=settings['auth'];user=auth.get('user') or next(iter(auth['users']));password=auth.get('pass') or auth['users'][user]['password']
    host=settings.get('client_hostname',settings.get('host','127.0.0.1'))
    if host in {'0.0.0.0','::'}:host='localhost'
    if not isinstance(host,str) or not __import__('re').fullmatch('[A-Za-z0-9.:-]+',host):raise ValueError('fixed UFS host required')
    port=settings['port']
    if type(port)is not int or not 1<=port<=65535:raise ValueError('UFS listener port required')
    url=('https' if settings.get('ssl',False) else 'http')+'://'+('['+host+']' if ':' in host else host)+':'+str(port)+'/api/protocols'
    manager=urllib.request.HTTPPasswordMgrWithDefaultRealm();manager.add_password(None,url,user,password)
    class SHA256Digest(urllib.request.HTTPDigestAuthHandler):
        def get_algorithm_impls(self,algorithm):
            if algorithm!='SHA-256':raise ValueError('native UFS SHA-256 Digest required')
            digest=lambda text:hashlib.sha256(text.encode('utf-8')).hexdigest()
            return digest,lambda secret,data:digest(secret+':'+data)
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):return None
    handlers=[urllib.request.ProxyHandler({}),SHA256Digest(manager),NoRedirect()]
    if settings.get('ssl',False):handlers.append(urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=settings['ssl_cert'])))
    with urllib.request.build_opener(*handlers).open(url,timeout=10) as response:
        value=strict_json(response.read(65537),65536)
    if value.get('schema')!='ziokt.ufs-protocols.v1':raise ValueError('native protocol status schema')
    return value


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);args=parser.parse_args();asyncio.run(run(args.config))


if __name__=='__main__':main()
