"""Durable ordinary accounts with no invitation, contribution or admin privilege."""
import hashlib,hmac,re,secrets,sqlite3,threading,time
from pathlib import Path
from contextlib import contextmanager

SCOPES=['applications:read','content:read','content:write','library:read','library:write','netnews:read','netnews:write','feeds:read','feeds:write','optimization:read','optimization:write']

class Accounts:
    def __init__(self,root,reserved=()):
        self.path=Path(root)/'public-accounts.sqlite'
        self.reserved=set(reserved);self.lock=threading.Lock()
        with self.connect() as db:
            db.executescript('CREATE TABLE IF NOT EXISTS accounts(account TEXT PRIMARY KEY,salt BLOB NOT NULL,password BLOB NOT NULL);CREATE TABLE IF NOT EXISTS sessions(digest TEXT PRIMARY KEY,account TEXT NOT NULL,expires INTEGER NOT NULL);CREATE INDEX IF NOT EXISTS session_account ON sessions(account);')
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=5)
        try:
            with db:yield db
        finally:db.close()

    def credentials(self,payload):
        if type(payload)is not dict or set(payload)!={'username','password'} or type(payload['username'])is not str or not re.fullmatch('[a-z0-9][a-z0-9_-]{2,47}',payload['username']) or type(payload['password'])is not str or not 12<=len(payload['password'])<=256:
            raise ValueError('username (3–48 lowercase letters/digits) and password (12–256 characters) required')
        account='user_'+payload['username']
        if account in self.reserved:raise ValueError('account unavailable')
        return account,payload['password'].encode()

    def issue(self,payload,register=False):
        account,password=self.credentials(payload)
        with self.lock,self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            now=int(time.time());db.execute('DELETE FROM sessions WHERE expires<=?',(now,))
            existing=db.execute('SELECT salt,password FROM accounts WHERE account=?',(account,)).fetchone()
            salt=secrets.token_bytes(16) if not existing else existing[0]
            derived=hashlib.scrypt(password,salt=salt,n=16384,r=8,p=1,dklen=32)
            if register:
                if existing:raise ValueError('account unavailable')
                db.execute('INSERT INTO accounts VALUES(?,?,?)',(account,salt,derived))
            elif not existing or not hmac.compare_digest(existing[1],derived):raise PermissionError('account or password rejected')
            token=secrets.token_urlsafe(32);expiry=now+7*86400
            # Bound each account's active sessions without dropping a concurrent login.
            db.execute('DELETE FROM sessions WHERE account=? AND digest NOT IN (SELECT digest FROM sessions WHERE account=? ORDER BY expires DESC LIMIT 7)',(account,account))
            db.execute('INSERT INTO sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),account,expiry))
        return {'schema':'ziokt.public-account.v1','account':account,'token':token,'expires_at':expiry,'scopes':list(SCOPES)}

    def principal(self,authorization):
        if not authorization.startswith('Bearer ') or len(authorization)>256:return None
        digest=hashlib.sha256(authorization[7:].encode()).hexdigest()
        with self.connect() as db:
            row=db.execute('SELECT account FROM sessions WHERE digest=? AND expires>?',(digest,int(time.time()))).fetchone()
        return {'account':row[0],'scopes':list(SCOPES)} if row else None

    def contains(self,account):
        with self.connect() as db:return db.execute('SELECT 1 FROM accounts WHERE account=?',(account,)).fetchone()is not None
