"""Real PDFium/Pillow rendering under the OS filter, not mocked renderer results."""
import base64
import hashlib
import io
import unittest
import zipfile
from PIL import Image
from ziokt.document_sandbox import parse_document


def pdf():
    objects=[b'<< /Type /Catalog /Pages 2 0 R /OpenAction << /S /JavaScript /JS (app.alert(123)) >> >>',
      b'<< /Type /Pages /Count 2 /Kids [3 0 R 4 0 R] >>',
      b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 400] /Resources << /Font << /F1 5 0 R >> >> /Contents 6 0 R >>',
      b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 400] /Resources << /Font << /F1 5 0 R >> >> /Contents 7 0 R >>',
      b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    for text in (b'First PDF page',b'Second PDF page'):
        data=b'BT /F1 20 Tf 20 300 Td ('+text+b') Tj ET'
        objects.append(b'<< /Length '+str(len(data)).encode()+b' >>\nstream\n'+data+b'\nendstream')
    result=b'%PDF-1.7\n';offsets=[0]
    for i,obj in enumerate(objects,1):offsets.append(len(result));result+=str(i).encode()+b' 0 obj\n'+obj+b'\nendobj\n'
    start=len(result);result+=b'xref\n0 8\n0000000000 65535 f \n'
    for offset in offsets[1:]:result+=f'{offset:010d} 00000 n \n'.encode()
    return result+b'trailer\n<< /Root 1 0 R /Size 8 >>\nstartxref\n'+str(start).encode()+b'\n%%EOF\n'


def cbz(names=('002.png','001.png')):
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w') as archive:
        for i,name in enumerate(names):
            image=io.BytesIO();Image.new('RGB',(200,300),'red' if i else 'blue').save(image,'PNG');archive.writestr(name,image.getvalue())
    return output.getvalue()


class RasterTests(unittest.TestCase):
    def test_actual_pdf_pages_text_paging_and_script_inertness(self):
        source=pdf();manifest=parse_document(source,'application/pdf','manifest',limit=1)
        self.assertEqual(manifest['chapter_count'],2);self.assertEqual(manifest['next_offset'],1)
        first=parse_document(source,'application/pdf','chapter',chapter=0,limit=5)
        self.assertEqual(first['text'],'First');self.assertEqual(first['next_offset'],5)
        second=parse_document(source,'application/pdf','chapter',chapter=1,limit=16384)
        self.assertIn('Second PDF page',second['text']);self.assertFalse(second['scripts_executed'])
        self.assertTrue(second['rendered_in_sandbox']);self.check_image(second)
        self.assertNotEqual(first['image']['data'],second['image']['data'])

    def check_image(self,result):
        raw=base64.b64decode(result['image']['data'],validate=True)
        with Image.open(io.BytesIO(raw)) as image:
            self.assertEqual(image.format,'JPEG');self.assertLessEqual(max(image.size),1200)
        self.assertLessEqual(len(raw),140000)

    def test_cbz_all_pages_and_navigation(self):
        source=cbz();manifest=parse_document(source,'application/vnd.comicbook+zip','manifest')
        self.assertEqual(manifest['chapter_count'],2)
        for page in (0,1):self.check_image(parse_document(source,'application/vnd.comicbook+zip','chapter',chapter=page))
        with self.assertRaises(ValueError):parse_document(source,'application/vnd.comicbook+zip','chapter',chapter=2)

    def test_active_archive_members_traversal_duplicates_and_invalid_pdf_rejected(self):
        for names in [('001.svg',),('../001.png',),('001.png','001.png')]:
            with self.subTest(names=names),self.assertRaises(ValueError):parse_document(cbz(names),'application/vnd.comicbook+zip','manifest')
        with self.assertRaises(ValueError):parse_document(b'%PDF-1.7 invalid','application/pdf','manifest')

    def test_cbz_expansion_budget_and_format_confusion(self):
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as archive:archive.writestr('001.png',b'0'*3_000_000)
        with self.assertRaises(ValueError):parse_document(output.getvalue(),'application/vnd.comicbook+zip','manifest')
        with self.assertRaises(ValueError):parse_document(pdf(),'application/vnd.comicbook+zip','manifest')

    def test_worker_stdout_and_stderr_are_bounded_before_buffering(self):
        import sys
        from ziokt.document_sandbox import bounded_process,MAX_OUTPUT
        for channel in ('stdout','stderr'):
            with self.subTest(channel=channel),self.assertRaisesRegex(ValueError,'pipe output limit'):
                bounded_process([sys.executable,'-I','-c','import sys;sys.'+channel+'.buffer.write(b"x"*'+str(MAX_OUTPUT+10000)+')'],b'')

    def test_cbz_with_metadata_files_and_webp(self):
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w') as archive:
            archive.writestr('ComicInfo.xml','<ComicInfo><Title>Sample</Title></ComicInfo>')
            archive.writestr('read_me.txt','Scanlation info')
            archive.writestr('.DS_Store',b'\0'*10)
            img1=io.BytesIO();Image.new('RGB',(100,150),'green').save(img1,'PNG');archive.writestr('page_01.png',img1.getvalue())
            img2=io.BytesIO();Image.new('RGB',(100,150),'yellow').save(img2,'WEBP');archive.writestr('page_02.webp',img2.getvalue())
        source=output.getvalue()
        manifest=parse_document(source,'application/vnd.comicbook+zip','manifest')
        self.assertEqual(manifest['chapter_count'],2)
        p1=parse_document(source,'application/vnd.comicbook+zip','chapter',chapter=0)
        self.check_image(p1)
        p2=parse_document(source,'application/vnd.comicbook+zip','chapter',chapter=1)
        self.check_image(p2)

    def test_api_checks_private_book_before_and_after_render(self):
        from ziokt.content_fabric import Fabric
        from ziokt.content_api import invoke
        import tempfile
        with tempfile.TemporaryDirectory() as area:
            fabric=Fabric(area)
            try:
                source=pdf();fabric.begin('alice','upload',len(source),'sha256:'+hashlib.sha256(source).hexdigest(),'application/pdf')
                fabric.put('alice','upload',0,source);obj=fabric.finish('alice','upload')
                fabric.create_book('alice',{'id':'pdf-book','work_id':'pdf-work','edition_id':'pdf-edition','file_id':obj['id'],'title':'PDF book','authors':['Author'],'license':'test-owned','visibility':'private'})
                with self.assertRaises(PermissionError):invoke(fabric,'bob','library.reader.chapter',{'id':'pdf-book','chapter':0,'offset':0,'limit':16384,'fragment':''})
                self.check_image(invoke(fabric,'alice','library.reader.chapter',{'id':'pdf-book','chapter':0,'offset':0,'limit':16384,'fragment':''}))
                self.assertFalse(fabric.export()['events'])
            finally:fabric.close()

if __name__=='__main__':unittest.main()
