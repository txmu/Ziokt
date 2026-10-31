#!/usr/bin/env python3
"""Enable every native UFS protocol on an existing DCPM/UFS configuration."""
import argparse,datetime,hashlib,ipaddress,json,os,pathlib,secrets,shutil,sys
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ziokt.protocol import secure_read
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=pathlib.Path,required=True);p.add_argument('--hostname',required=True);p.add_argument('--listen',default='0.0.0.0');p.add_argument('--base-port',type=int,default=22000);p.add_argument('--tls-cert',type=pathlib.Path);p.add_argument('--tls-key',type=pathlib.Path);args=p.parse_args()
 if not 1024<=args.base_port<=55000 or bool(args.tls_cert)!=bool(args.tls_key):raise ValueError('bounded port base and certificate/key pair required')
 ipaddress.ip_address(args.listen)
 path=args.config.resolve();raw=secure_read(path,256*1024);config=json.loads(raw);ufs=config['ufs'];storage=config['storage'];served=pathlib.Path(storage['ufs_root'])
 if not served.is_absolute():served=(path.parent/served).resolve()
 native=ROOT/'companions/ufsdcpm/src';sys.path.insert(0,str(native));from ufsultra import auth_accounts
 accounts=auth_accounts(ufs)
 if args.tls_cert:cert,key=args.tls_cert.resolve(),args.tls_key.resolve()
 else:
  directory=path.parent/'ufs-protocols-tls';directory.mkdir(exist_ok=True,mode=0o700);cert,key=directory/'server.crt',directory/'server.key'
  if not cert.exists() and not key.exists():
   private=rsa.generate_private_key(public_exponent=65537,key_size=3072);now=datetime.datetime.now(datetime.timezone.utc);name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,args.hostname)])
   try:alternative=x509.IPAddress(ipaddress.ip_address(args.hostname))
   except ValueError:alternative=x509.DNSName(args.hostname)
   public=x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(private.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=1)).not_valid_after(now+datetime.timedelta(days=365)).add_extension(x509.BasicConstraints(ca=True,path_length=None),True).add_extension(x509.SubjectAlternativeName([alternative,x509.DNSName('localhost')]),False).sign(private,hashes.SHA256())
   for target,data in [(key,private.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())),(cert,public.public_bytes(serialization.Encoding.PEM))]:
    fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as output:output.write(data)
  if not cert.is_file() or not key.is_file():raise ValueError('complete persistent TLS pair required')
 import ssl
 context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(cert,key)
 cache=pathlib.Path(storage['cache']);cache=cache if cache.is_absolute() else (path.parent/cache).resolve()
 ufs.setdefault('account_roots',{user:str(served) if len(accounts)==1 else str(served/'accounts'/user) for user in accounts})
 ufs.update(protocol_host=args.listen,protocol_ip_whitelist=['0.0.0.0/0','::/0'],public_root=str(served/'public'))
 ports={'ftp':args.base_port+21,'ftps':args.base_port+22,'telnet':args.base_port+23,'sftp':args.base_port+24,'gopher':args.base_port+70,'nntp':args.base_port+19}
 ufs['protocols']={name:{'enabled':True,'port':port,'tls':name not in {'gopher','sftp'},'cert':str(cert),'key':str(key),**({'passive_ports':[args.base_port+800,args.base_port+832]} if name in {'ftp','ftps'} else {}),**({'hostname':args.hostname} if name=='gopher' else {}),**({'host_key':str(cache/'sftp-host.key')} if name=='sftp' else {})} for name,port in ports.items()}
 backups=path.parent/'private-protocol-backups';backups.mkdir(exist_ok=True,mode=0o700);backup=backups/('config-'+str(__import__('time').time_ns())+'.json');backup.write_bytes(raw);backup.chmod(0o600)
 pending=path.with_name('.'+path.name+'.'+secrets.token_hex(6));pending.write_text(json.dumps(config,indent=2)+'\n');pending.chmod(0o600);os.replace(pending,path)
 public=served/'public';public.mkdir(parents=True,exist_ok=True,mode=0o700);welcome=public/'README.txt'
 if not welcome.exists():welcome.write_text('Ziokt open mainnet\nhttps://app.ziokt.com/mainnet/\n');welcome.chmod(0o600)
 print(json.dumps({'schema':'ziokt.ufs-protocol-configuration.v1','config':str(path),'protocols':ports,'tls_certificate_sha256':hashlib.sha256(cert.read_bytes()).hexdigest(),'identity_credentials_rotated':False}))


if __name__=='__main__':main()
