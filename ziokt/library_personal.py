"""Account-private Library notes, bookmarks and collections.

Bodies use a separately derived AEAD key from the existing account vault key.
IDs, book references, revisions and collection membership remain local metadata.
Nothing in these tables is exported into the public catalogue or search index.
"""
import json
import secrets

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .content_fabric import ident, text
from .protocol import encoded

MAX_ROWS = 10000
MAX_BYTES = 32 * 1024 * 1024
MAX_MEMBERS = 4096


class PersonalLibrary:
    def __init__(self, fabric):
        self.fabric = fabric
        self.db = fabric.db
        with fabric.transaction():
            self.db.execute('''CREATE TABLE IF NOT EXISTS library_personal(
                owner TEXT NOT NULL,kind TEXT NOT NULL,id TEXT NOT NULL,
                book TEXT NOT NULL,revision INTEGER NOT NULL,deleted INTEGER NOT NULL,
                body BLOB NOT NULL,PRIMARY KEY(owner,kind,id))''')
            self.db.execute('''CREATE TABLE IF NOT EXISTS library_collection_members(
                owner TEXT NOT NULL,collection TEXT NOT NULL,book TEXT NOT NULL,
                PRIMARY KEY(owner,collection,book))''')
            self.db.execute('CREATE INDEX IF NOT EXISTS library_personal_book ON library_personal(owner,kind,book,id)')
            self.db.execute('INSERT OR IGNORE INTO migrations VALUES(11,unixepoch())')

    def _key(self, owner):
        with self.fabric.store(owner) as store:
            return HKDF(hashes.SHA256(), 32, None, b'Ziokt/Library/personal/v1').derive(store.vault.key)

    def _aad(self, owner, kind, id, book, revision):
        return encoded(['ziokt.library-personal.v1', owner, kind, id, book, revision])

    def _open(self, row):
        blob = row['body']
        return json.loads(AESGCM(self._key(row['owner'])).decrypt(
            blob[:12], blob[12:], self._aad(row['owner'], row['kind'], row['id'], row['book'], row['revision'])))

    def _row(self, owner, kind, id):
        ident(owner); ident(id)
        return self.db.execute('SELECT * FROM library_personal WHERE owner=? AND kind=? AND id=?', (owner, kind, id)).fetchone()

    def _result(self, row):
        return {'id': row['id'], 'book': row['book'], 'revision': row['revision'], **self._open(row)}

    @staticmethod
    def _revision(revision):
        if type(revision) is not int or not 0 <= revision < 2**63-1:
            raise ValueError('personal revision')

    @staticmethod
    def _page(limit, offset):
        if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or not 0 <= offset <= MAX_ROWS:
            raise ValueError('personal pagination')

    @staticmethod
    def _anchor(anchor):
        if type(anchor) is not dict or set(anchor) - {'chapter', 'offset', 'quote'}:
            raise ValueError('personal anchor')
        for field in ('chapter', 'offset'):
            if field in anchor and (type(anchor[field]) is not int or not 0 <= anchor[field] <= 2**31-1):
                raise ValueError('personal anchor position')
        if 'quote' in anchor:
            text(anchor['quote'], 2048, empty=True)
        return anchor

    def _save(self, owner, kind, id, book, body, revision):
        self._revision(revision)
        old = self._row(owner, kind, id)
        if old and (old['deleted'] or old['book'] != book):
            raise ValueError('personal identity withdrawn or changed')
        current = old['revision'] if old else 0
        if revision != current:
            if old and revision + 1 == current and self._open(old) == body:
                return self._result(old)
            raise ValueError('personal revision conflict')
        plain = encoded(body)
        if len(plain) > 16384:
            raise ValueError('personal body budget')
        count, used = self.db.execute('SELECT count(*),coalesce(sum(length(body)),0) FROM library_personal WHERE owner=?', (owner,)).fetchone()
        if (old is None and count >= MAX_ROWS) or used - (len(old['body']) if old else 0) + len(plain) + 28 > MAX_BYTES:
            raise ValueError('personal quota')
        version = current + 1
        nonce = secrets.token_bytes(12)
        sealed = nonce + AESGCM(self._key(owner)).encrypt(nonce, plain, self._aad(owner, kind, id, book, version))
        self.db.execute('INSERT OR REPLACE INTO library_personal VALUES(?,?,?,?,?,?,?)', (owner, kind, id, book, version, 0, sealed))
        from .content_private import PrivateFabric
        PrivateFabric(self.fabric).record_reading(owner,'personal.'+kind,id,{'book':book,'body':body,'deleted':False})
        self.fabric._audit(owner, 'library.' + kind + '.save', id)
        return {'id': id, 'book': book, 'revision': version, **body}

    def save(self, owner, kind, id, book, value, anchor, revision=0):
        if kind not in {'note', 'bookmark'}:
            raise ValueError('personal kind')
        text(value, 8192 if kind == 'note' else 512, empty=(kind == 'bookmark'))
        self._anchor(anchor)
        with self.fabric.transaction():
            self.fabric._get(owner, book, 'book')
            return self._save(owner, kind, id, book, {'text' if kind == 'note' else 'label': value, 'anchor': anchor}, revision)

    def list(self, owner, kind, book, limit=30, offset=0):
        self._page(limit, offset); ident(owner)
        if kind not in {'note', 'bookmark'}:
            raise ValueError('personal kind')
        with self.fabric.lock:
            self.fabric._get(owner, book, 'book')
            rows = self.db.execute('SELECT * FROM library_personal WHERE owner=? AND kind=? AND book=? AND deleted=0 ORDER BY id LIMIT ? OFFSET ?', (owner, kind, book, limit+1, offset)).fetchall()
            return {'items': [self._result(row) for row in rows[:limit]], 'next_offset': offset+limit if len(rows)>limit else None}

    def delete(self, owner, kind, id, revision):
        self._revision(revision)
        if kind not in {'note', 'bookmark', 'collection'}:
            raise ValueError('personal kind')
        with self.fabric.transaction():
            row = self._row(owner, kind, id)
            if row is None:
                raise PermissionError('personal entry unavailable')
            if row['deleted'] and revision+1 == row['revision']:
                return {'id': id, 'revision': row['revision'], 'deleted': True}
            if revision != row['revision'] or row['deleted']:
                raise ValueError('personal revision conflict')
            # Own notes can be removed even after access to their source is revoked.
            self.db.execute('UPDATE library_personal SET revision=?,deleted=1,body=? WHERE owner=? AND kind=? AND id=?', (revision+1, b'', owner, kind, id))
            from .content_private import PrivateFabric
            PrivateFabric(self.fabric).record_reading(owner,'personal.'+kind,id,{'book':row['book'],'body':{},'deleted':True})
            if kind == 'collection':
                self.db.execute('DELETE FROM library_collection_members WHERE owner=? AND collection=?', (owner,id))
            self.fabric._audit(owner, 'library.' + kind + '.delete', id)
            return {'id': id, 'revision': revision+1, 'deleted': True}

    def collections(self, owner, limit=30, offset=0):
        self._page(limit, offset); ident(owner)
        with self.fabric.lock:
            rows = self.db.execute("SELECT * FROM library_personal WHERE owner=? AND kind='collection' AND deleted=0 ORDER BY id LIMIT ? OFFSET ?", (owner, limit+1, offset)).fetchall()
            return {'items': [self._result(row) for row in rows[:limit]], 'next_offset': offset+limit if len(rows)>limit else None}

    def collection_get(self, owner, id, limit=30, offset=0):
        self._page(limit, offset)
        with self.fabric.lock:
            row = self._row(owner, 'collection', id)
            if row is None or row['deleted']:
                raise PermissionError('collection unavailable')
            members = self.db.execute('SELECT book FROM library_collection_members WHERE owner=? AND collection=? ORDER BY book LIMIT ? OFFSET ?', (owner,id,limit+1,offset)).fetchall()
            items=[]
            for member in members[:limit]:
                try:
                    book=self.fabric._get(owner,member['book'],'book')
                except PermissionError:
                    continue
                items.append({'id':member['book'],**book})
            return {**self._result(row),'items':items,'next_offset':offset+limit if len(members)>limit else None,'pagination':'stored-members; inaccessible books omitted'}

    def collection_manage(self, owner, id, action, revision, name='', book=''):
        self._revision(revision)
        if action == 'delete':
            if name or book:raise ValueError('collection action fields')
            return self.delete(owner, 'collection', id, revision)
        if action not in {'create','rename','add','remove'}:
            raise ValueError('collection action')
        with self.fabric.transaction():
            row=self._row(owner,'collection',id)
            if action == 'create':
                if book or revision != 0:raise ValueError('collection create fields')
                text(name,512)
                return self._save(owner,'collection',id,'',{'name':name},0)
            if row is None or row['deleted']:raise PermissionError('collection unavailable')
            body=self._open(row)
            if action=='rename':
                if book:raise ValueError('collection rename fields')
                text(name,512)
                return self._save(owner,'collection',id,'',{'name':name},revision)
            if name:raise ValueError('collection member fields')
            text(book,300)
            present=self.db.execute('SELECT 1 FROM library_collection_members WHERE owner=? AND collection=? AND book=?',(owner,id,book)).fetchone() is not None
            if action=='add':self.fabric._get(owner,book,'book')
            # Membership retries require a transport idempotency key. A stale
            # revision never silently wins over another device's edit.
            if revision != row['revision']:raise ValueError('personal revision conflict')
            if action=='add' and not present:
                if self.db.execute('SELECT count(*) FROM library_collection_members WHERE owner=? AND collection=?',(owner,id)).fetchone()[0]>=MAX_MEMBERS:raise ValueError('collection member quota')
                self.db.execute('INSERT INTO library_collection_members VALUES(?,?,?)',(owner,id,book))
            elif action=='remove':
                self.db.execute('DELETE FROM library_collection_members WHERE owner=? AND collection=? AND book=?',(owner,id,book))
            from .content_private import PrivateFabric
            import hashlib
            target=hashlib.sha256((id+'\0'+book).encode()).hexdigest()
            PrivateFabric(self.fabric).record_reading(owner,'collection.member',target,{'collection':id,'book':book,'present':action=='add'})
            return self._save(owner,'collection',id,'',body,revision)
