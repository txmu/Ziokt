"""Actual encrypted objects, signed metadata, FTS5 and optimistic updates."""
import tempfile
from pathlib import Path
import unittest
from ziokt.content_fabric import Fabric
from ziokt.content_api import invoke
from ziokt.library_metadata import language,validate
import test_content_fabric as fixture


class MetadataTests(unittest.TestCase):
    def setUp(self):
        fixture.FabricTests.setUp(self);self.addCleanup(self.fabric.close);self.addCleanup(self.temp.cleanup)
        self.upload=fixture.FabricTests.upload.__get__(self);self.book=fixture.FabricTests.book.__get__(self)
        obj=self.upload();self.book(obj,bid='book')

    def current(self,owner='alice',**kwargs):return invoke(self.fabric,owner,'library.get',{'id':'book',**kwargs})

    def update(self,**changes):
        value=self.current();event=value.pop('version_event')
        for key in ('file','updated_at','editable','visibility','origin'):value.pop(key,None)
        event=changes.pop('expected_event',event);value.update(changes);value['expected_event']=event
        return invoke(self.fabric,'alice','library.publish',{'metadata':value})

    def test_language_metadata_fts_author_filter_locale_fallback_and_persistence(self):
        self.update(localized_metadata={'zh-hans':{'title':'内容织网','description':'分布式馆藏','authors':['张作家']},'en':{'title':'Woven knowledge','authors':['English Author']}})
        view=self.current(locale='zh-Hans');self.assertEqual(view['title'],'内容织网');self.assertEqual(view['default_title'],'Open book');self.assertEqual(view['bibliography_version'],2)
        self.assertEqual(self.current(locale='en-US')['title'],'Woven knowledge');self.assertEqual(self.current(locale='fr')['title'],'Open book')
        result=invoke(self.fabric,'alice','library.search',{'query':'Woven','locale':'en-US','filters':{'author':'English Author','language':'en'}})
        self.assertEqual(result['items'][0]['title'],'Woven knowledge')
        self.assertEqual(len(self.fabric.search('alice','内容织网')['items']),1)
        self.fabric.close();self.fabric=Fabric(self.root/'node');self.addCleanup(self.fabric.close)
        self.assertEqual(self.current(locale='zh-Hans')['title'],'内容织网');self.assertFalse(self.fabric.export()['events'])
        with self.assertRaises(PermissionError):self.current('bob',locale='zh-Hans')
        self.assertEqual(self.fabric.search('bob','Woven',locale='en')['items'],[])

    def test_stale_metadata_edit_cannot_overwrite_newer_localized_version(self):
        stale=self.current()['version_event'];self.update(localized_metadata={'en':{'title':'First version'}})
        with self.assertRaisesRegex(ValueError,'version conflict'):self.update(expected_event=stale,localized_metadata={'en':{'title':'Wrong overwrite'}})
        self.assertEqual(self.current(locale='en')['title'],'First version')
        self.update(localized_metadata={'en':{'title':'New searchable title'}})
        self.assertEqual(self.fabric.search('alice','First')['items'],[])
        self.assertEqual(len(self.fabric.search('alice','New searchable')['items']),1)

    def test_signed_remote_metadata_preserves_languages_and_rejects_invalid_projection(self):
        value=self.current()
        for key in ('file','updated_at','editable','origin','version_event'):value.pop(key,None)
        value.update(id='public-book',visibility='public',localized_metadata={'en':{'title':'Remote knowledge'}})
        invoke(self.fabric,'alice','library.publish',{'metadata':value})
        remote=Fabric(self.root/'remote',peers={self.fabric.public:{'groups':[]}});self.addCleanup(remote.close)
        remote.ingest(self.fabric.export()['events'])
        self.assertEqual(remote.search('bob','Remote',locale='en')['items'][0]['title'],'Remote knowledge')
        raw=dict(self.fabric._get('alice','public-book'));raw['localized_metadata']={'en':{'title':'Forged','visibility':'private'}}
        with self.fabric.transaction():self.fabric._event('alice','book','public-book',raw,'public')
        with self.assertRaises(ValueError):remote.ingest(self.fabric.export()['events'])
        self.assertEqual(remote.search('bob','Remote',locale='en')['items'][0]['title'],'Remote knowledge')

    def test_existing_mcp_tools_accept_locale_and_keep_write_scopes(self):
        from ziokt.mcp import Service,McpError
        config={'state':str(self.root/'mcp'),'issuer':'https://test.invalid','clients':{'writer':{'scopes':['library:read','library:write']},'reader':{'scopes':['library:read']}},'bridges':{},'writes_enabled':True,'content_fabric':{'enabled':True,'root':str(self.root/'node'),'accounts':{'writer':'alice','reader':'bob'}}}
        service=Service(config);self.addCleanup(service.close)
        writer={'client':'writer','scopes':{'library:read','library:write'}};reader={'client':'reader','scopes':{'library:read'}}
        self.assertNotIn('locale',service.tools['library_get']['inputSchema']['required'])
        self.assertEqual(service.tools['library_search']['inputSchema']['properties']['locale']['maxLength'],63)
        self.update(localized_metadata={'en':{'title':'Scoped translation'}})
        result=service.call(writer,'library_get',{'id':'book','locale':'en'})
        self.assertFalse(result['isError']);self.assertEqual(result['structuredContent']['title'],'Scoped translation')
        self.assertTrue(service.call(reader,'library_get',{'id':'book','locale':'en'})['isError'])
        with self.assertRaises(McpError):service.call(reader,'library_publish',{'metadata':{}},'not-authorized-00001')

    def test_canonical_tags_invalid_fields_versions_and_metadata_budget(self):
        self.assertEqual(language('sr-latn-rs'),'sr-Latn-RS')
        for value in ({'en':{'title':'One'},'EN':{'title':'Two'}},{'../../x':{'title':'No'}},{'en':{'title':'No','visibility':'public'}},{'en':{'title':''}},{'en':{'title':'Yes','authors':['x\0y']}}):
            with self.subTest(value=value),self.assertRaises(ValueError):validate(value)
        for version in (True,3,1):
            with self.assertRaises(ValueError):self.update(localized_metadata={'en':{'title':'No'}},bibliography_version=version)
        self.assertEqual(self.current()['title'],'Open book')

if __name__=='__main__':unittest.main()
