"""Private notes/collections with real encrypted payloads, SQLite and API dispatch."""
import hashlib
from pathlib import Path
import tempfile
import unittest

from cryptography.exceptions import InvalidTag

from ziokt.content_api import invoke
from ziokt.content_fabric import Fabric


class PersonalLibraryTests(unittest.TestCase):
    def setUp(self):
        self.area=tempfile.TemporaryDirectory();self.addCleanup(self.area.cleanup)
        self.root=Path(self.area.name)/'node';self.fabric=Fabric(self.root)
        self.addCleanup(lambda:self.fabric.close())
        data=b'Original private book'
        self.fabric.begin('alice','upload',len(data),'sha256:'+hashlib.sha256(data).hexdigest(),'text/plain')
        self.fabric.put('alice','upload',0,data)
        obj=self.fabric.finish('alice','upload')
        for id,visibility in [('private-book','private'),('public-book','public')]:
            self.fabric.create_book('alice',{'id':id,'work_id':'work','edition_id':'edition','title':id,'license':'CC0-1.0','file_id':obj['id'],'visibility':visibility})

    def call(self,operation,args,owner='alice'):
        return invoke(self.fabric,owner,operation,args)

    def test_note_encryption_restart_idempotency_and_offline_conflict(self):
        args={'id':'note-1','book':'private-book','text':'Private annotation: rare phrase','anchor':{'offset':12,'quote':'Original'}}
        first=self.call('library.note.create',args)
        self.assertEqual(first,self.call('library.note.create',args))
        row=self.fabric.db.execute("SELECT body FROM library_personal WHERE id='note-1'").fetchone()[0]
        self.assertNotIn(args['text'].encode(),row)
        self.assertNotIn(args['text'],str(self.fabric.export()))
        self.fabric.close();self.fabric=Fabric(self.root)
        self.assertEqual(self.call('library.note.list',{'book':'private-book'})['items'],[first])
        changed={**args,'text':'Edited annotation','revision':1}
        updated=self.call('library.note.update',changed)
        self.assertEqual(updated['revision'],2)
        self.assertEqual(updated,self.call('library.note.update',changed))
        with self.assertRaisesRegex(ValueError,'revision conflict'):
            self.call('library.note.update',{**changed,'text':'Conflicting offline edit'})
        with self.assertRaises(PermissionError):self.call('library.note.list',{'book':'private-book'},'bob')

    def test_public_book_never_shares_personal_notes_or_bookmarks(self):
        args={'id':'bookmark-1','book':'public-book','label':'Personal label','anchor':{'chapter':2,'offset':17},'revision':0}
        mark=self.call('library.bookmark.set',args)
        self.assertEqual(self.call('library.bookmark.list',{'book':'public-book'},'bob')['items'],[])
        with self.assertRaises(PermissionError):self.call('library.bookmark.delete',{'id':'bookmark-1','revision':1},'bob')
        self.fabric.withdraw('alice','public-book')
        with self.assertRaises(PermissionError):self.call('library.bookmark.list',{'book':'public-book'})
        removed=self.call('library.bookmark.delete',{'id':mark['id'],'revision':1})
        self.assertTrue(removed['deleted'])
        self.assertEqual(removed,self.call('library.bookmark.delete',{'id':mark['id'],'revision':1}))

    def test_collection_revision_membership_permissions_and_withdrawal(self):
        created=self.call('library.collection.manage',{'id':'shelf','action':'create','name':'Private shelf','revision':0})
        self.assertEqual(created,self.call('library.collection.manage',{'id':'shelf','action':'create','name':'Private shelf','revision':0}))
        added=self.call('library.collection.manage',{'id':'shelf','action':'add','book':'private-book','revision':1})
        self.assertEqual(added['revision'],2)
        self.assertEqual(self.call('library.collection.get',{'id':'shelf'})['items'][0]['id'],'private-book')
        self.assertEqual(self.call('library.collection.list',{},'bob')['items'],[])
        with self.assertRaises(PermissionError):self.call('library.collection.get',{'id':'shelf'},'bob')
        with self.assertRaisesRegex(ValueError,'revision conflict'):
            self.call('library.collection.manage',{'id':'shelf','action':'rename','name':'Old edit','revision':1})
        self.fabric.withdraw('alice','private-book')
        self.assertEqual(self.call('library.collection.get',{'id':'shelf'})['items'],[])
        self.call('library.collection.manage',{'id':'shelf','action':'remove','book':'private-book','revision':2})
        self.call('library.collection.manage',{'id':'shelf','action':'delete','revision':3})
        self.assertEqual(self.call('library.collection.list',{})['items'],[])

    def test_aead_binds_owner_id_book_and_revision(self):
        for id in ('a','b'):
            self.call('library.note.create',{'id':id,'book':'public-book','text':id,'anchor':{}})
        rows=self.fabric.db.execute("SELECT id,body FROM library_personal ORDER BY id").fetchall()
        with self.fabric.db:
            self.fabric.db.execute('UPDATE library_personal SET body=? WHERE id=?',(rows[0]['body'],rows[1]['id']))
        with self.assertRaises(InvalidTag):self.call('library.note.list',{'book':'public-book'})

    def test_strict_anchor_pagination_and_no_identity_resurrection(self):
        args={'id':'n','book':'private-book','text':'text','anchor':{}}
        for anchor in ({'offset':True},{'chapter':-1},{'url':'https://untrusted.test/'}):
            with self.assertRaises(ValueError):self.call('library.note.create',{**args,'anchor':anchor})
        self.call('library.note.create',args)
        self.call('library.note.delete',{'id':'n','revision':1})
        with self.assertRaises(ValueError):self.call('library.note.create',args)
        with self.assertRaises(ValueError):self.call('library.note.list',{'book':'private-book','limit':True})
        self.assertNotIn('library_personal',str(self.fabric.export()))


if __name__=='__main__':unittest.main()
