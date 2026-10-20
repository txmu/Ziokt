import io,unittest,zipfile,tempfile,hashlib
from ziokt.content_fabric import Fabric
from ziokt.content_api import invoke
from ziokt.library_formats import extract

def epub(chapter='<html><body><h1>Chapter One</h1><p>Original CC0 prose.</p><script>bad()</script></body></html>'):
 output=io.BytesIO()
 with zipfile.ZipFile(output,'w') as archive:
  archive.writestr('mimetype','application/epub+zip')
  archive.writestr('META-INF/container.xml','<container><rootfiles><rootfile full-path="OPS/book.opf"/></rootfiles></container>')
  archive.writestr('OPS/book.opf','<package><manifest><item id="one" href="one.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="one"/></spine></package>')
  archive.writestr('OPS/one.xhtml',chapter)
 return output.getvalue()

class FormatTests(unittest.TestCase):
 def test_epub_spine_order_inert_text(self):
  result=extract(epub(),'application/epub+zip');self.assertIn('Original CC0 prose.',result['chapters'][0]['text']);self.assertNotIn('bad()',result['chapters'][0]['text']);self.assertFalse(result['scripts_executed']);self.assertFalse(result['truncated'])
 def test_truncation_is_explicit(self):
  result=extract(epub('<p>'+('x'*18000)+'</p>'),'application/epub+zip');self.assertTrue(result['truncated']);self.assertEqual(len(result['chapters'][0]['text']),16000)
 def test_expansion_and_traversal_rejected(self):
  for name,data in [('../evil',b'x'),('huge',b'x'*(3*1024*1024))]:
   output=io.BytesIO(epub())
   with zipfile.ZipFile(output,'a') as archive:archive.writestr(name,data)
   with self.assertRaises(ValueError):extract(output.getvalue(),'application/epub+zip')
 def test_persistent_object_api_and_private_permissions(self):
  with tempfile.TemporaryDirectory() as root:
   fabric=Fabric(root)
   try:
    data=epub();fabric.begin('alice','epub',len(data),'sha256:'+hashlib.sha256(data).hexdigest(),'application/epub+zip')
    for pos,start in enumerate(range(0,len(data),16384)):fabric.put('alice','epub',pos,data[start:start+16384])
    obj=fabric.finish('alice','epub');fabric.create_book('alice',{'id':'epubbook','work_id':'work','edition_id':'edition','file_id':obj['id'],'title':'Original','license':'CC0-1.0'})
    result=invoke(fabric,'alice','library.extract',{'id':'epubbook'});self.assertIn('Original CC0 prose.',result['chapters'][0]['text'])
    with self.assertRaises(PermissionError):invoke(fabric,'bob','library.extract',{'id':'epubbook'})
   finally:fabric.close()
 def test_html_is_inert(self):self.assertEqual(extract(b'<p>Hello</p><script>alert(1)</script>','text/html')['chapters'][0]['text'],'Hello')

if __name__=='__main__':unittest.main()
