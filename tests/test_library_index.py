"""Actual sandbox extraction, encrypted derived data and revision-safe index jobs."""
import hashlib
from pathlib import Path
import unittest
import test_content_fabric as fixture
from ziokt.content_fabric import Fabric
from ziokt.content_api import invoke


class DocumentIndexTests(unittest.TestCase):
    def setUp(self):
        fixture.FabricTests.setUp(self);self.addCleanup(self.temp.cleanup);self.addCleanup(self.fabric.close)
        self.upload=fixture.FabricTests.upload.__get__(self);self.book=fixture.FabricTests.book.__get__(self)

    def call(self,operation,arguments,owner='alice'):return invoke(self.fabric,owner,operation,arguments)

    def start(self,data=b'NebularSaffron document body; only encrypted bytes contain this.',visibility='private',bid='book'):
        obj=self.upload(data,name='upload-'+bid);self.book(obj,visibility,bid=bid)
        return self.call('library.index.start',{'id':bid})

    def finish(self,job):
        for _ in range(1024):
            if job['state']=='complete':return job
            job=self.call('library.index.step',{'job':job['id'],'revision':job['revision']})
        self.fail('Index did not finish in bounded fixture steps')

    def test_complete_content_search_private_storage_and_cross_account_denial(self):
        job=self.start();self.assertEqual(self.fabric.search('alice','NebularSaffron')['items'],[])
        done=self.finish(job);self.assertEqual(done['state'],'complete')
        self.assertEqual(len(self.fabric.search('alice','NebularSaffron')['items']),1)
        self.assertEqual(self.fabric.search('bob','NebularSaffron')['items'],[])
        with self.assertRaises(PermissionError):self.call('library.index.status',{'job':job['id']},'bob')
        for row in self.fabric.db.execute('SELECT body FROM library_index_pages'):
            self.assertNotIn(b'NebularSaffron',row['body'])
        self.fabric.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        self.assertNotIn(b'NebularSaffron',(self.root/'node/content.sqlite').read_bytes())
        self.assertFalse(self.fabric.export()['events'])

    def test_revision_retries_do_not_advance_twice_and_restart_resumes(self):
        job=self.start(b'Alpha '*4000+b'NebularSaffron completion')
        advanced=self.call('library.index.step',{'job':job['id'],'revision':job['revision']})
        duplicate=self.call('library.index.step',{'job':job['id'],'revision':job['revision']})
        self.assertTrue(duplicate['duplicate']);self.assertEqual(advanced['revision'],duplicate['revision'])
        self.assertEqual(self.fabric.search('alice','Alpha')['items'],[])  # partial indexes are not exposed
        self.fabric.close();self.fabric=Fabric(self.root/'node');self.addCleanup(self.fabric.close)
        done=self.finish(self.call('library.index.status',{'job':job['id']}));self.assertEqual(done['state'],'complete')
        self.assertEqual(len(self.fabric.search('alice','NebularSaffron')['items']),1)

    def test_word_split_at_reader_boundary_and_accent_normalization(self):
        prefix=b'padding '*(16380//8)+b' '*(16380%8)
        self.finish(self.start(prefix+b'NebularSaffron caf\xc3\xa9 final'))
        self.assertEqual(len(self.fabric.search('alice','NebularSaffron cafe')['items']),1)
        self.assertEqual(self.fabric.search('alice','Nebu')['items'],[])

    def test_content_replacement_withdrawal_and_cancel_remove_searchability(self):
        job=self.finish(self.start());obj=self.upload(b'Replacement text','replacement')
        old=self.call('library.get',{'id':'book'});metadata={key:value for key,value in old.items() if key not in {'file','updated_at','version_event','editable','origin'}}
        metadata.update(file_id=obj['id'],expected_event=old['version_event']);self.call('library.publish',{'metadata':metadata})
        self.assertEqual(self.fabric.search('alice','NebularSaffron')['items'],[])
        cancelled=self.call('library.index.cancel',{'job':job['id']});self.assertEqual(cancelled['state'],'cancelled')
        self.assertEqual(self.fabric.db.execute('SELECT count(*) FROM library_index_pages').fetchone()[0],0)
        self.assertEqual(self.call('library.index.cancel',{'job':job['id']})['revision'],cancelled['revision'])

    def test_cancelled_lease_and_live_lease_do_not_admit_duplicate_workers(self):
        job=self.start()
        with self.fabric.transaction():self.fabric.db.execute("UPDATE library_index_jobs SET lease='other',lease_until=9999999999 WHERE id=?",(job['id'],))
        response=self.call('library.index.step',{'job':job['id'],'revision':job['revision']});self.assertTrue(response['busy'])
        cancelled=self.call('library.index.cancel',{'job':job['id']});self.assertEqual(cancelled['state'],'cancelled')
        restarted=self.call('library.index.start',{'id':'book'});self.assertGreater(restarted['revision'],job['revision']);self.finish(restarted)

    def test_public_objects_do_not_share_personal_index_and_tombstones_hide_results(self):
        job=self.finish(self.start(visibility='public'))
        self.assertEqual(self.fabric.search('bob','NebularSaffron')['items'],[])
        self.fabric.withdraw('alice','book');self.assertEqual(self.fabric.search('alice','NebularSaffron')['items'],[])
        self.assertEqual(self.call('library.index.cancel',{'job':job['id']})['state'],'cancelled')

    def test_quota_failure_rolls_back_pages_and_terms(self):
        from unittest.mock import patch
        job=self.start()
        with patch('ziokt.library_index.MAX_CHARACTERS',1):
            with self.assertRaisesRegex(ValueError,'quota'):self.call('library.index.step',{'job':job['id'],'revision':job['revision']})
        self.assertEqual(self.call('library.index.status',{'job':job['id']})['state'],'failed')
        self.assertEqual(self.fabric.db.execute('SELECT count(*) FROM library_index_pages').fetchone()[0],0)
        self.assertEqual(self.fabric.db.execute('SELECT count(*) FROM library_index_terms').fetchone()[0],0)
        self.assertEqual(self.fabric.search('alice','NebularSaffron')['items'],[])

    def test_tampered_carry_fails_closed_and_expired_lease_recovers(self):
        job=self.start(b'Alpha '*4000+b'NebularSaffron completion')
        with self.fabric.transaction():self.fabric.db.execute("UPDATE library_index_jobs SET lease='crashed',lease_until=1 WHERE id=?",(job['id'],))
        job=self.call('library.index.step',{'job':job['id'],'revision':job['revision']})
        with self.fabric.transaction():self.fabric.db.execute("UPDATE library_index_tails SET body=? WHERE job=?",(b'x'*64,job['id']))
        with self.assertRaisesRegex(ValueError,'integrity'):self.call('library.index.step',{'job':job['id'],'revision':job['revision']})
        self.assertEqual(self.call('library.index.status',{'job':job['id']})['state'],'failed')
        self.assertEqual(self.fabric.search('alice','Alpha')['items'],[])

    def test_search_rechecks_final_object_existence(self):
        self.start(visibility='public')
        foreign=self.call('library.index.start',{'id':'book'},'bob')
        for _ in range(10):
            if foreign['state']=='complete':break
            foreign=self.call('library.index.step',{'job':foreign['id'],'revision':foreign['revision']},'bob')
        self.assertEqual(len(self.fabric.search('bob','NebularSaffron')['items']),1)
        with self.fabric.transaction():self.fabric.db.execute('DELETE FROM objects')
        self.assertEqual(self.fabric.search('bob','NebularSaffron')['items'],[])

    def test_mcp_scopes_schema_and_revision_retry(self):
        from ziokt.mcp import Service,McpError
        self.start()
        config={'state':str(self.root/'mcp'),'issuer':'https://test.invalid','clients':{'writer':{'scopes':['library:read','library:write']},'reader':{'scopes':['library:read']}},'bridges':{},'writes_enabled':True,'content_fabric':{'enabled':True,'root':str(self.root/'node'),'accounts':{'writer':'alice','reader':'bob'}}}
        service=Service(config);self.addCleanup(service.close)
        writer={'client':'writer','scopes':{'library:read','library:write'}};reader={'client':'reader','scopes':{'library:read'}}
        with self.assertRaises(McpError):service.call(reader,'library_index_start',{'id':'book'},'index-denied-0001')
        result=service.call(writer,'library_index_start',{'id':'book'},'index-start-0001');self.assertFalse(result['isError'])
        job=result['structuredContent'];args={'job':job['id'],'revision':job['revision']}
        advanced=service.call(writer,'library_index_step',args,'index-step-00001');self.assertFalse(advanced['isError'])
        self.assertTrue(service.call(reader,'library_index_status',{'job':job['id']})['isError'])
        schema=service.tools['library_index_step']['inputSchema'];self.assertFalse(schema['additionalProperties']);self.assertEqual(schema['properties']['job']['maxLength'],64)

    def test_actual_pdf_all_pages_indexed(self):
        from test_raster_reader import pdf
        data=pdf();self.fabric.begin('alice','pdf',len(data),'sha256:'+hashlib.sha256(data).hexdigest(),'application/pdf')
        self.fabric.put('alice','pdf',0,data);obj=self.fabric.finish('alice','pdf');self.book(obj,'private',bid='pdf-book')
        self.finish(self.call('library.index.start',{'id':'pdf-book'}))
        self.assertEqual(len(self.fabric.search('alice','Second')['items']),1)
        self.assertEqual(self.fabric.search('bob','Second')['items'],[])

if __name__=='__main__':unittest.main()
