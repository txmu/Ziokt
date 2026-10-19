import hashlib,tempfile,threading,unittest
from pathlib import Path
from ziokt.content_fabric import Fabric
from ziokt.content_server import server
from ziokt.content_download import download_file

class RangeDownloadTests(unittest.TestCase):
 def test_real_range_resume_and_local_corruption_detection(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);fabric=Fabric(root/'state');data=b'Original CC0 range sample '*3000;fabric.begin('alice','upload',len(data),'sha256:'+hashlib.sha256(data).hexdigest(),'text/plain')
   for pos,start in enumerate(range(0,len(data),16384)):fabric.put('alice','upload',pos,data[start:start+16384])
   obj=fabric.finish('alice','upload');fabric.create_book('alice',{'id':'book','title':'Original','work_id':'work','edition_id':'edition','file_id':obj['id'],'license':'CC0','visibility':'public'})
   http=server(fabric,{'port':0,'public_read':True,'tokens':[]});thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start();peer={'url':'http://127.0.0.1:'+str(http.server_port),'token':''};output=root/'download.txt'
   try:
    first=download_file(peer,obj['id'],output,max_segments=1,segment_bytes=16384);self.assertFalse(first['complete']);self.assertFalse(output.exists());part=root/'download.txt.ziokt-part'
    with part.open('ab') as stream:stream.write(b'uncheckpointed crash tail')
    result=download_file(peer,obj['id'],output,max_segments=1,segment_bytes=16384);self.assertEqual(result['received_bytes'],32768)
    correct=part.read_bytes();part.write_bytes(b'CORRUPT'+correct[7:])
    with self.assertRaisesRegex(ValueError,'integrity'):download_file(peer,obj['id'],output)
    part.write_bytes(correct);result=download_file(peer,obj['id'],output);self.assertTrue(result['verified']);self.assertEqual(output.read_bytes(),data);self.assertFalse(part.exists());self.assertTrue(download_file(peer,obj['id'],output)['duplicate'])
   finally:http.shutdown();http.server_close();thread.join();fabric.close()

if __name__=='__main__':unittest.main()
