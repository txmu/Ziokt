"""Full bounded text pages and actual OS isolation, not in-process preview claims."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

from ziokt.content_api import invoke
from ziokt.content_fabric import Fabric
from ziokt.document_sandbox import parse_document,PARSERS
from ziokt.library_formats import inert_text,reader


def publication():
    raw='<html><body><h1>Long chapter</h1>'+''.join('<p>Section '+str(i)+' — original text.</p>' for i in range(2000))+'<script>privateScript()</script></body></html>'
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w') as archive:
        archive.writestr('mimetype','application/epub+zip')
        archive.writestr('META-INF/container.xml','<container><rootfiles><rootfile full-path="OPS/book.opf"/></rootfiles></container>')
        archive.writestr('OPS/book.opf','<package><manifest><item id="one" href="one.xhtml" media-type="application/xhtml+xml"/><item id="two" href="two.xhtml" media-type="application/xhtml+xml"/><item id="nav" href="nav.xhtml" properties="nav" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="one"/><itemref idref="two"/></spine></package>')
        archive.writestr('OPS/one.xhtml',raw)
        archive.writestr('OPS/two.xhtml','<p>Last chapter.</p>')
        archive.writestr('OPS/nav.xhtml','<html><body><nav><a href="one.xhtml#start">Long chapter</a><a href="two.xhtml">Last chapter</a><a href="https://forbidden.test/">External</a></nav></body></html>')
    return output.getvalue(),inert_text(raw.encode())


class DocumentReaderTests(unittest.TestCase):
    def test_spine_navigation_and_complete_long_chapter_pages(self):
        source,expected=publication()
        if sys.platform!='linux':
            with self.assertRaisesRegex(ValueError,'sandbox unavailable'):parse_document(source,'application/epub+zip','manifest')
            return
        manifest=parse_document(source,'application/epub+zip','manifest',limit=1)
        self.assertEqual(manifest['chapter_count'],2);self.assertEqual(manifest['next_offset'],1)
        self.assertEqual(manifest['chapters'][0]['title'],'Long chapter')
        self.assertEqual(manifest['navigation_count'],2)
        pieces=[];offset=0
        while offset is not None:
            part=parse_document(source,'application/epub+zip','chapter',chapter=0,offset=offset,limit=16384)
            self.assertFalse(part['scripts_executed']);pieces.append(part['text']);offset=part['next_offset']
        self.assertEqual(''.join(pieces),expected);self.assertGreater(len(expected),16000)
        self.assertNotIn('privateScript',''.join(pieces))

    def test_actual_seccomp_blocks_files_network_processes_and_memory_exhaustion(self):
        if sys.platform!='linux':
            with self.assertRaisesRegex(ValueError,'sandbox unavailable'):parse_document(b'hello','text/plain')
            return
        from ziokt import document_sandbox
        with tempfile.TemporaryDirectory() as temp:
            secret=Path(temp)/'private';secret.write_text('never expose')
            code="""import importlib.util,json,os,socket,sys
spec=importlib.util.spec_from_file_location('parser',sys.argv[1]);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
module.confine()
denied=[]
for action in (lambda:open(sys.argv[2]).read(),lambda:socket.socket(),lambda:os.fork()):
 try:action();denied.append(False)
 except PermissionError:denied.append(True)
try:bytearray(256*1024*1024);denied.append(False)
except MemoryError:denied.append(True)
print(json.dumps(denied))
"""
            result=subprocess.run([sys.executable,'-I','-S','-c',code,document_sandbox.__file__,str(secret)],capture_output=True,text=True,timeout=8)
            self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(json.loads(result.stdout),[True]*4)

    def test_private_resource_checks_apply_to_both_reader_endpoints(self):
        with tempfile.TemporaryDirectory() as temp:
            fabric=Fabric(Path(temp)/'node')
            try:
                source,_=publication();fabric.begin('alice','book-upload',len(source),'sha256:'+hashlib.sha256(source).hexdigest(),'application/epub+zip')
                for index,start in enumerate(range(0,len(source),16384)):fabric.put('alice','book-upload',index,source[start:start+16384])
                obj=fabric.finish('alice','book-upload')
                fabric.create_book('alice',{'id':'private','title':'Private EPUB','work_id':'work','edition_id':'edition','file_id':obj['id'],'license':'CC0-1.0'})
                for operation,args in [('library.reader.manifest',{}),('library.reader.chapter',{'chapter':0})]:
                    with self.assertRaises(PermissionError):invoke(fabric,'bob',operation,{'id':'private',**args})
                    if sys.platform=='linux':self.assertTrue(invoke(fabric,'alice',operation,{'id':'private',**args}))
                    else:
                        with self.assertRaisesRegex(ValueError,'sandbox unavailable'):invoke(fabric,'alice',operation,{'id':'private',**args})
                fabric.withdraw('alice','private')
                with self.assertRaises(PermissionError):invoke(fabric,'alice','library.reader.chapter',{'id':'private','chapter':0})
            finally:fabric.close()

    def test_invalid_zip_xml_and_parser_concurrency_fail_closed(self):
        for arguments in ({'chapter':True},{'limit':0},{'offset':-1}):
            with self.assertRaises(ValueError):reader(b'hello','text/plain','chapter',**arguments)
        if sys.platform=='linux':
            with self.assertRaises(ValueError):parse_document(b'not a zip','application/epub+zip','manifest')
        self.assertTrue(PARSERS.acquire(blocking=False));self.assertTrue(PARSERS.acquire(blocking=False))
        try:
            with self.assertRaisesRegex(ValueError,'concurrency budget'):parse_document(b'hello','text/plain')
        finally:PARSERS.release();PARSERS.release()


if __name__=='__main__':unittest.main()
