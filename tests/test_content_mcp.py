import base64,hashlib,json,tempfile,unittest
from pathlib import Path
from ziokt.mcp import Service,McpError
from ziokt.content_checkpoint import checkpoint,restore
from ziokt.content_fabric import Fabric

class ContentMcpTests(unittest.TestCase):
 def test_news_readstate_registered_scopes_and_durable_idempotency(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp)
   config={'state':str(root/'mcp'),'issuer':'https://test.invalid','clients':{'writer':{'scopes':['netnews:read','netnews:write']},'reader':{'scopes':['netnews:read']}},'bridges':{},'writes_enabled':True,'content_fabric':{'enabled':True,'root':str(root/'fabric'),'accounts':{'writer':'alice','reader':'bob'}}}
   service=Service(config)
   try:
    writer={'client':'writer','scopes':{'netnews:read','netnews:write'}}
    group=service.call(writer,'netnews_group_create',{'name':'news.public','visibility':'public'},'group-create-00001')
    self.assertFalse(group['isError'],group)
    article=service.call(writer,'netnews_post',{'groups':['news.public'],'subject':'Subject','body':'Body'},'article-post-00001')['structuredContent']['id']
    args={'article':article,'is_read':True,'revision':0}
    first=service.call(writer,'netnews_readstate_update',args,'readstate-update-01')
    self.assertFalse(first['isError'],first)
    self.assertEqual(first,service.call(writer,'netnews_readstate_update',args,'readstate-update-01'))
    reader={'client':'reader','scopes':{'netnews:read'}}
    self.assertFalse(service.call(reader,'netnews_readstate_get',{'article':article})['structuredContent']['is_read'])
    with self.assertRaises(McpError):service.call(reader,'netnews_readstate_update',args,'readstate-denied-01')
   finally:service.close()
 def test_opt_in_scopes_audit_and_real_store(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp)
   config={'state':str(root/'mcp'),'issuer':'https://test.invalid','clients':{'writer':{'scopes':['library:read','library:write','content:read','content:write']},'reader':{'scopes':['library:read']}},'bridges':{},'writes_enabled':True,'content_fabric':{'enabled':True,'root':str(root/'fabric'),'accounts':{'writer':'alice','reader':'bob'}}}
   service=Service(config)
   self.assertIn('library_search',service.tools)
   writer={'client':'writer','scopes':{'library:read','library:write','content:read','content:write'}}
   def call(name,args,key=None):
    result=service.call(writer,name,args,key)
    self.assertFalse(result['isError'],result)
    return result['structuredContent']
   data=b'Test original CC0 content';digest='sha256:'+hashlib.sha256(data).hexdigest()
   call('content_upload_begin',{'upload':'test-upload','size':len(data),'digest':digest,'mime':'text/plain'},'operation-begin-0001')
   call('content_upload_put',{'upload':'test-upload','position':0,'data':base64.b64encode(data).decode()},'operation-chunk-0001')
   obj=call('content_upload_finish',{'upload':'test-upload'},'operation-finish-001')
   call('library_publish',{'metadata':{'id':'book','work_id':'w','edition_id':'e','file_id':obj['id'],'title':'MCP book','license':'CC0-1.0'}},'operation-book-0001')
   self.assertEqual(len(call('library_search',{})['items']),1)
   note_args={'id':'mcp-note','book':'book','text':'Private MCP note','anchor':{'offset':4}}
   note=call('library_note_create',note_args,'operation-note-0001')
   self.assertEqual(note,call('library_note_create',note_args,'operation-note-0001'))
   self.assertEqual(call('library_note_list',{'book':'book'})['items'],[note])
   shelf=call('library_collection_manage',{'id':'mcp-shelf','action':'create','name':'Private MCP collection','revision':0},'operation-shelf-0001')
   call('library_collection_manage',{'id':shelf['id'],'action':'add','book':'book','revision':shelf['revision']},'operation-add-00001')
   self.assertEqual(call('library_collection_get',{'id':shelf['id']})['items'][0]['id'],'book')
   reader={'client':'reader','scopes':{'library:read'}}
   self.assertEqual(service.call(reader,'library_search',{})['structuredContent']['items'],[])
   self.assertEqual(service.call(reader,'library_collection_list',{})['structuredContent']['items'],[])
   denied=service.call(reader,'library_note_list',{'book':'book'})
   self.assertTrue(denied['isError'])
   with self.assertRaises(McpError):service.call(reader,'content_upload_finish',{'upload':'test-upload'},'rejected-operation-01')
   service.close()
 def test_cold_checkpoint_and_tamper_rejection(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);fabric=Fabric(root/'original');public=fabric.public
   fabric.create_group('alice','books.open');fabric.post('alice',['books.open'],'Cold recovery','Durable article')
   fabric.close();checkpoint(root/'original',root/'snapshot')
   restore(root/'snapshot',root/'restored',public)
   restored=Fabric(root/'restored')
   try:self.assertEqual(restored.articles('alice','books.open')['items'][0]['subject'],'Cold recovery')
   finally:restored.close()
   (root/'snapshot'/'node.key').write_bytes(b'x'*32)
   with self.assertRaises(ValueError):restore(root/'snapshot',root/'tampered',public)

if __name__=='__main__':unittest.main()
