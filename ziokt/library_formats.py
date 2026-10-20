"""Bounded, inert text extraction. Never renders publication HTML or fetches URLs."""
import io
import posixpath
import zipfile
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

MAX_SOURCE=16*1024*1024
MAX_EXPANDED=32*1024*1024
MAX_MEMBER=2*1024*1024

class PlainText(HTMLParser):
 def __init__(self):super().__init__(convert_charrefs=True);self.parts=[];self.skip=0
 def handle_starttag(self,tag,attrs):
  if tag in {'script','style','iframe','object'}:self.skip+=1
  if tag in {'p','div','br','h1','h2','h3','li'} and not self.skip:self.parts.append('\n')
 def handle_endtag(self,tag):
  if tag in {'script','style','iframe','object'}:self.skip=max(0,self.skip-1)
 def handle_data(self,data):
  if not self.skip:self.parts.append(data)

def inert_text(raw):
 parser=PlainText();parser.feed(raw.decode('utf-8','replace'));return ''.join(parser.parts).strip()

def xml(raw):
 if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise ValueError('XML declarations forbidden')
 return ET.fromstring(raw)

def extract(source,mime):
 if len(source)>MAX_SOURCE:raise ValueError('reader source limit')
 if mime in {'text/plain','text/markdown','text/html'}:
  value=inert_text(source) if mime=='text/html' else source.decode('utf-8','replace')
  return {'format':mime,'chapters':[{'title':'Text','text':value[:16000]}],'truncated':len(value)>16000,'scripts_executed':False}
 if mime!='application/epub+zip':raise ValueError('format requires an external reader')
 chapters=[];total=0;truncated=False
 with zipfile.ZipFile(io.BytesIO(source)) as archive:
  entries=archive.infolist()
  if len(entries)>2048 or sum(e.file_size for e in entries)>MAX_EXPANDED:raise ValueError('archive expansion limit')
  names=set()
  for entry in entries:
   if entry.filename in names:raise ValueError('duplicate archive member')
   names.add(entry.filename)
   if entry.flag_bits&1 or entry.file_size>MAX_MEMBER or entry.file_size>max(1024,entry.compress_size*200):raise ValueError('archive member limit')
   if entry.filename.startswith('/') or '..' in entry.filename.split('/') or '\\' in entry.filename:raise ValueError('unsafe archive path')
  def read(name):
   if name not in names:raise ValueError('missing EPUB member')
   return archive.read(name)
  if read('mimetype')!=b'application/epub+zip':raise ValueError('EPUB mimetype')
  container=xml(read('META-INF/container.xml'));rootfiles=[e for e in container.iter() if e.tag.rsplit('}',1)[-1]=='rootfile']
  if not rootfiles:raise ValueError('EPUB rootfile')
  package_path=rootfiles[0].get('full-path','');package=xml(read(package_path));manifest={}
  for entry in package.iter():
   if entry.tag.rsplit('}',1)[-1]=='item':manifest[entry.get('id')]=entry
  for item in package.iter():
   if item.tag.rsplit('}',1)[-1]!='itemref':continue
   member=manifest.get(item.get('idref'))
   if member is None:raise ValueError('EPUB spine reference')
   href=member.get('href','')
   if ':' in href or href.startswith('/') or '?' in href or '#' in href:raise ValueError('EPUB external reference')
   path=posixpath.normpath(posixpath.join(posixpath.dirname(package_path),href))
   if path.startswith('../'):raise ValueError('EPUB traversal')
   if member.get('media-type') not in {'application/xhtml+xml','text/html'}:continue
   raw=read(path);value=inert_text(raw);room=16000-total
   if room<=0 or len(chapters)>=64:truncated=True;break
   title=path.rsplit('/',1)[-1]
   chapters.append({'title':title,'text':value[:room]});total+=min(room,len(value))
   if len(value)>room:truncated=True
  if not chapters:raise ValueError('EPUB has no readable spine')
 return {'format':mime,'chapters':chapters,'truncated':truncated,'scripts_executed':False,'external_resources_loaded':False}
