import io,unittest,zipfile,tempfile,hashlib
from ziokt.content_fabric import Fabric
from ziokt.content_api import invoke
from ziokt.library_formats import extract, reader, sniff_format

def epub(chapter='<html><body><h1>Chapter One</h1><p>Original CC0 prose.</p><script>bad()</script></body></html>'):
 output=io.BytesIO()
 with zipfile.ZipFile(output,'w') as archive:
  archive.writestr('mimetype','application/epub+zip')
  archive.writestr('META-INF/container.xml','<container><rootfiles><rootfile full-path="OPS/book.opf"/></rootfiles></container>')
  archive.writestr('OPS/book.opf','<package><manifest><item id="one" href="one.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="one"/></spine></package>')
  archive.writestr('OPS/one.xhtml',chapter)
 return output.getvalue()

def zip_text():
 output=io.BytesIO()
 with zipfile.ZipFile(output,'w') as archive:
  archive.writestr('01-intro.txt','Introduction to the system.')
  archive.writestr('02-chapter.md','# Chapter 2\nDetailed explanation.')
 return output.getvalue()

class FormatTests(unittest.TestCase):
 def test_epub_spine_order_inert_text(self):
  result=extract(epub(),'application/epub+zip');self.assertIn('Original CC0 prose.',result['chapters'][0]['text']);self.assertNotIn('bad()',result['chapters'][0]['text']);self.assertFalse(result['scripts_executed']);self.assertFalse(result['truncated'])
 def test_truncation_is_explicit(self):
  result=extract(epub('<p>'+('x'*18000)+'</p>'),'application/epub+zip');self.assertTrue(result['truncated']);self.assertEqual(len(result['chapters'][0]['text']),16000)
 def test_expansion_and_traversal_rejected(self):
  for name,data in [('../evil',b'x'),('huge',b'x'*(5*1024*1024))]:
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

 def test_epub_missing_ncx_and_title_extraction(self):
  output=io.BytesIO()
  with zipfile.ZipFile(output,'w') as archive:
   archive.writestr('mimetype','application/epub+zip\n')
   archive.writestr('META-INF/container.xml','<container><rootfiles><rootfile full-path="OPS/book.opf"/></rootfiles></container>')
   archive.writestr('OPS/book.opf','<package><manifest><item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/><item id="one" href="one.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="one"/></spine></package>')
   archive.writestr('OPS/one.xhtml','<html><head><title>First Real Chapter</title></head><body><p>Body content</p></body></html>')
  source=output.getvalue()
  m=reader(source,'application/epub+zip','manifest')
  self.assertEqual(m['chapter_count'],1)
  self.assertEqual(m['chapters'][0]['title'],'First Real Chapter')
  c0=reader(source,'application/epub+zip','chapter',chapter=0)
  self.assertIn('Body content',c0['text'])

 def test_sniff_format(self):
  self.assertEqual(sniff_format(b'%PDF-1.7\nsomething'),'application/pdf')
  self.assertEqual(sniff_format(epub()),'application/epub+zip')
  self.assertEqual(sniff_format(zip_text()),'application/zip+text')
  self.assertEqual(sniff_format(b'# Markdown','text/markdown','doc.md'),'text/markdown')
  # CBZ with image
  out=io.BytesIO()
  with zipfile.ZipFile(out,'w') as z:
   z.writestr('001.jpg',b'\xff\xd8\xff')
   z.writestr('ComicInfo.xml',b'<xml></xml>')
  self.assertEqual(sniff_format(out.getvalue()),'application/vnd.comicbook+zip')

 def test_zip_text_reader_manifest_and_chapters(self):
  source=zip_text()
  m=reader(source,'application/zip','manifest')
  self.assertEqual(m['chapter_count'],2)
  self.assertEqual(m['chapters'][0]['title'],'01-intro.txt')
  self.assertEqual(m['chapters'][1]['title'],'02-chapter.md')
  c0=reader(source,'application/zip','chapter',chapter=0)
  self.assertIn('Introduction to the system.',c0['text'])
  c1=reader(source,'application/zip','chapter',chapter=1)
  self.assertIn('Detailed explanation.',c1['text'])
  ex=extract(source,'application/zip')
  self.assertEqual(len(ex['chapters']),2)

if __name__=='__main__':unittest.main()
