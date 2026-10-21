"""Unified local search keeps native Library and Netnews permission indexes."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from ziokt.content_api import invoke,attach,required_scopes
from ziokt.content_fabric import Fabric
from ziokt.protocol import ProtocolError

class UnifiedSearchTests(unittest.TestCase):
    def setUp(self):
        area=tempfile.TemporaryDirectory();self.addCleanup(area.cleanup);self.fabric=Fabric(Path(area.name)/'node');self.addCleanup(self.fabric.close)
        data=b'open source geography book'
        self.fabric.begin('alice','book-upload',len(data),'sha256:'+hashlib.sha256(data).hexdigest(),'text/plain')
        self.fabric.put('alice','book-upload',0,data);obj=self.fabric.finish('alice','book-upload')
        self.fabric.create_book('alice',{'id':'geo-book','work_id':'geo','edition_id':'1','title':'Open geography','authors':['A'],'license':'CC0-1.0','file_id':obj['id'],'visibility':'public'})
        self.fabric.create_group('alice','news.public',visibility='public')
        self.fabric.post('alice',['news.public'],'Open atlas news','Open geography mapping')
        self.fabric.create_book('alice',{'id':'private-book','work_id':'p','edition_id':'1','title':'Open private geography','authors':['A'],'license':'CC0-1.0','file_id':obj['id'],'visibility':'private'})
    def test_search_returns_separate_authorized_native_indexes(self):
        result=invoke(self.fabric,'alice','content.search',{'query':'Open geography','sources':['library','netnews'],'limit':10,'offset':0,'filters':{}})
        self.assertEqual(result['schema'],'ziokt.content-search.v1')
        self.assertEqual({item['id'] for item in result['sources']['library']['items']},{'geo-book','private-book'})
        self.assertEqual(len(result['sources']['netnews']['items']),1)
        public=invoke(self.fabric,'bob','content.search',{'query':'Open geography','sources':['library','netnews'],'limit':10,'offset':0,'filters':{}})
        self.assertEqual([item['id'] for item in public['sources']['library']['items']],['geo-book'])
        self.assertEqual(len(public['sources']['netnews']['items']),1)
    def test_source_selection_is_bounded_and_mcp_tool_is_read_only(self):
        with self.assertRaises(ValueError):invoke(self.fabric,'alice','content.search',{'sources':['ufs'],'query':'','limit':10,'offset':0,'filters':{}})
        with self.assertRaises(ValueError):invoke(self.fabric,'alice','content.search',{'sources':['library','library'],'query':'','limit':10,'offset':0,'filters':{}})
        class Service:
            def __init__(self):self.tools={};self.calls=[]
            def add(self,name,description,input_schema,write,scope,route):
                self.calls.append((name,description,input_schema,write,scope,route));self.tools[name]={'securitySchemes':[{}]}
        service=Service();attach(service,{'enabled':True,'root':'/tmp','accounts':{}})
        tool=next(call for call in service.calls if call[0]=='content_search')
        self.assertFalse(tool[3]);self.assertEqual(tool[4],'content:read')
        self.assertEqual(required_scopes('content.search'),{'content:read'})
