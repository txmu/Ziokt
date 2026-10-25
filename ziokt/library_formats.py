"""Bounded, inert text extraction. Never renders publication HTML or fetches URLs."""
import io
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit

MAX_SOURCE=16*1024*1024
MAX_EXPANDED=32*1024*1024
MAX_MEMBER=4*1024*1024

IMAGE_EXTENSIONS={'.png','.jpg','.jpeg','.webp','.gif'}
TEXT_EXTENSIONS={'.txt','.md','.markdown','.rst','.html','.xhtml','.htm','.text'}
IGNORED_METADATA={'comicinfo.xml','thumbs.db','.ds_store','desktop.ini','metadata.json','info.txt'}


def sniff_format(source, declared_mime=None, filename=None):
    if not source:
        return declared_mime or 'application/octet-stream'
    if declared_mime in {'application/pdf', 'application/epub+zip', 'application/vnd.comicbook+zip', 'application/x-cbz'}:
        return declared_mime
    if source.startswith(b'%PDF-'):
        return 'application/pdf'
    if source.startswith((b'PK\x03\x04', b'PK\x05\x06', b'PK\x07\x08')):
        try:
            with zipfile.ZipFile(io.BytesIO(source)) as archive:
                names = archive.namelist()
                name_set = set(names)
                if 'META-INF/container.xml' in name_set:
                    return 'application/epub+zip'
                if 'mimetype' in name_set:
                    try:
                        if archive.read('mimetype').strip() == b'application/epub+zip':
                            return 'application/epub+zip'
                    except Exception:
                        pass
                ext = posixpath.splitext((filename or '').lower())[1]
                if ext in {'.cbz', '.cbr'}:
                    return 'application/vnd.comicbook+zip'
                if ext == '.epub':
                    return 'application/epub+zip'
                files = [n for n in names if not n.endswith('/')]
                image_files = []
                text_files = []
                for f in files:
                    base = posixpath.basename(f).lower()
                    if base in IGNORED_METADATA or base.startswith('.') or any(p.startswith('__MACOSX') for p in f.split('/')):
                        continue
                    suffix = posixpath.splitext(base)[1]
                    if suffix in IMAGE_EXTENSIONS:
                        image_files.append(f)
                    elif suffix in TEXT_EXTENSIONS:
                        text_files.append(f)
                if image_files and len(image_files) >= len(text_files):
                    return 'application/vnd.comicbook+zip'
                if text_files:
                    return 'application/zip+text'
        except Exception:
            pass
    if declared_mime in {'application/zip+text', 'text/plain', 'text/markdown', 'text/html'}:
        return declared_mime
    ext = posixpath.splitext((filename or '').lower())[1]
    if ext == '.pdf': return 'application/pdf'
    if ext == '.epub': return 'application/epub+zip'
    if ext in {'.cbz', '.cbr'}: return 'application/vnd.comicbook+zip'
    if ext in {'.txt', '.text'}: return 'text/plain'
    if ext in {'.md', '.markdown'}: return 'text/markdown'
    if ext in {'.html', '.htm'}: return 'text/html'
    return declared_mime or 'application/octet-stream'


def safe_archive(source):
    if len(source)>MAX_SOURCE:raise ValueError('reader source limit')
    archive=zipfile.ZipFile(io.BytesIO(source))
    try:
        entries=archive.infolist();names=set()
        if len(entries)>2048 or sum(e.file_size for e in entries)>MAX_EXPANDED:raise ValueError('archive expansion limit')
        for entry in entries:
            if entry.filename in names:raise ValueError('duplicate archive member')
            names.add(entry.filename)
            if entry.flag_bits&1 or entry.file_size>MAX_MEMBER or entry.file_size>max(1024,entry.compress_size*200):raise ValueError('archive member limit')
            if entry.filename.startswith('/') or '..' in entry.filename.split('/') or '\\' in entry.filename or '\0' in entry.filename:raise ValueError('unsafe archive path')
        return archive,names
    except BaseException:
        archive.close();raise


def local_member(base,href):
    if not isinstance(href,str) or len(href)>2048:raise ValueError('EPUB reference limit')
    parsed=urlsplit(href)
    if parsed.scheme or parsed.netloc or parsed.query:raise ValueError('EPUB external reference')
    path=unquote(parsed.path,errors='strict')
    if '\\' in path or '\0' in path or path.startswith('/'):raise ValueError('EPUB unsafe reference')
    path=posixpath.normpath(posixpath.join(posixpath.dirname(base),path))
    if path.startswith('../') or path in {'..','.'}:raise ValueError('EPUB traversal')
    return path,parsed.fragment


def epub_cover(source):
    archive,names=safe_archive(source)
    with archive:
        if 'META-INF/container.xml' not in names:return None
        container=xml(archive.read('META-INF/container.xml'))
        roots=[entry.get('full-path') for entry in container.iter() if entry.tag.rsplit('}',1)[-1]=='rootfile']
        if not roots or roots[0] not in names:return None
        package_path=roots[0];package=xml(archive.read(package_path));items={}
        cover_id=None
        for entry in package.iter():
            tag=entry.tag.rsplit('}',1)[-1]
            if tag=='item':items[entry.get('id')]=entry
            if tag=='meta' and entry.get('name')=='cover':cover_id=entry.get('content')
        candidates=[item for item in items.values() if 'cover-image' in item.get('properties','').split()]
        if cover_id in items:candidates.append(items[cover_id])
        for item in candidates:
            if item.get('media-type') not in {'image/png','image/jpeg','image/webp','image/gif'}:continue
            path,_=local_member(package_path,item.get('href',''))
            if path in names:return archive.read(path)
    return None


def reader(source,mime,mode,*,chapter=0,offset=0,limit=64,fragment=''):
    """Complete supported spine with bounded manifest/text pages; no silent truncation."""
    if mode not in {'manifest','chapter'}:raise ValueError('reader mode')
    if type(offset) is not int or not 0<=offset<=MAX_SOURCE:raise ValueError('reader offset')
    if type(chapter) is not int or not 0<=chapter<1024:raise ValueError('reader chapter')
    if not isinstance(fragment,str) or len(fragment)>128:raise ValueError('reader fragment')
    if type(limit) is not int or not 1<=limit<=(128 if mode=='manifest' else 16384):raise ValueError('reader page limit')
    if len(source)>MAX_SOURCE:raise ValueError('reader source limit')
    mime=sniff_format(source,mime)
    if mime in {'text/plain','text/markdown','text/html'}:
        if mode=='manifest':return {'format':mime,'chapters':[{'index':0,'title':'Text'}] if offset==0 else [],'chapter_count':1,'next_offset':None,'scripts_executed':False}
        if chapter!=0:raise ValueError('reader chapter unavailable')
        if fragment:raise ValueError('fragment requires an EPUB chapter')
        value=inert_text(source) if mime=='text/html' else source.decode('utf-8','replace')
        return {'chapter':0,'title':'Text','text':value[offset:offset+limit],'offset':offset,'next_offset':offset+limit if offset+limit<len(value) else None,'total_characters':len(value),'scripts_executed':False}
    if mime=='application/zip+text':
        archive,names=safe_archive(source)
        with archive:
            text_members=[]
            for n in names:
                if n.endswith('/'):continue
                base=posixpath.basename(n).lower()
                if base in IGNORED_METADATA or base.startswith('.') or any(p.startswith('__MACOSX') for p in n.split('/')):continue
                if posixpath.splitext(base)[1] in TEXT_EXTENSIONS:text_members.append(n)
            text_members.sort(key=lambda s:[int(t) if t.isdigit() else t.casefold() for t in re.split(r'([0-9]+)',s)])
            if not text_members:raise ValueError('archive has no readable text members')
            if mode=='manifest':
                return {'format':mime,'chapters':[{'index':i,'title':posixpath.basename(p)} for i,p in enumerate(text_members) if offset<=i<offset+limit],
                        'chapter_count':len(text_members),'next_offset':offset+limit if offset+limit<len(text_members) else None,
                        'navigation':[],'navigation_next_offset':None,'scripts_executed':False,'external_resources_loaded':False}
            if chapter>=len(text_members):raise ValueError('reader chapter unavailable')
            path=text_members[chapter];raw=archive.read(path)
            value=inert_text(raw) if posixpath.splitext(path.lower())[1] in {'.html','.htm','.xhtml'} else raw.decode('utf-8','replace')
            return {'chapter':chapter,'title':posixpath.basename(path),'text':value[offset:offset+limit],
                    'offset':offset,'next_offset':offset+limit if offset+limit<len(value) else None,'total_characters':len(value),
                    'scripts_executed':False,'external_resources_loaded':False}
    if mime!='application/epub+zip':raise ValueError('format requires an external reader')
    archive,names=safe_archive(source)
    with archive:
        def read(name):
            if name not in names:raise ValueError('missing EPUB member')
            return archive.read(name)
        mimetype_data=read('mimetype').strip() if 'mimetype' in names else b''
        if mimetype_data!=b'application/epub+zip' and 'META-INF/container.xml' not in names:raise ValueError('EPUB mimetype')
        container=xml(read('META-INF/container.xml'))
        roots=[item for item in container.iter() if item.tag.rsplit('}',1)[-1]=='rootfile']
        if not roots:raise ValueError('EPUB rootfile')
        package_path=roots[0].get('full-path','');package=xml(read(package_path))
        items={};nav=None
        for item in package.iter():
            if item.tag.rsplit('}',1)[-1]!='item':continue
            id=item.get('id')
            if not id or id in items:raise ValueError('EPUB manifest identity')
            items[id]=item
            if 'nav' in item.get('properties','').split():nav=item
        spine=[]
        for item in package.iter():
            if item.tag.rsplit('}',1)[-1]!='itemref':continue
            resource=items.get(item.get('idref'))
            if resource is None:raise ValueError('EPUB spine reference')
            media_type=(resource.get('media-type') or '').split(';')[0].strip().lower()
            if media_type not in {'application/xhtml+xml','text/html','text/plain','text/xml','application/xml'}:continue
            path,_=local_member(package_path,resource.get('href',''))
            if path not in names:raise ValueError('missing EPUB spine member')
            spine.append(path)
            if len(spine)>1024:raise ValueError('EPUB spine budget')
        if not spine:raise ValueError('EPUB has no readable spine')
        titles={};navigation=[]
        if nav is None:
            ncx=next((item for item in items.values() if item.get('media-type')=='application/x-dtbncx+xml'),None)
            if ncx is not None:
                try:
                    nav_path,_=local_member(package_path,ncx.get('href',''))
                    if nav_path in names:
                        for point in xml(read(nav_path)).iter():
                            if point.tag.rsplit('}',1)[-1]!='navPoint':continue
                            label=next((item for item in point if item.tag.rsplit('}',1)[-1]=='navLabel'),None)
                            content=next((item for item in point if item.tag.rsplit('}',1)[-1]=='content'),None)
                            if content is None:continue
                            try:path,fragment=local_member(nav_path,content.get('src',''))
                            except ValueError:continue
                            if path not in spine:continue
                            title=''.join(label.itertext()).strip()[:128] if label is not None else path.rsplit('/',1)[-1]
                            titles.setdefault(path,title);navigation.append({'chapter':spine.index(path),'title':title,'fragment':fragment[:128]})
                            if len(navigation)>1024:raise ValueError('EPUB navigation budget')
                except Exception:
                    pass
        if nav is not None:
            try:
                nav_path,_=local_member(package_path,nav.get('href',''))
                if nav_path in names:
                    navigation_root=xml(read(nav_path))
                    for entry in navigation_root.iter():
                        if entry.tag.rsplit('}',1)[-1]!='a':continue
                        try:path,fragment=local_member(nav_path,entry.get('href',''))
                        except ValueError:continue
                        if path not in spine:continue
                        title=''.join(entry.itertext()).strip()[:128]
                        titles.setdefault(path,title)
                        navigation.append({'chapter':spine.index(path), 'title':title, 'fragment':fragment[:128]})
                        if len(navigation)>1024:raise ValueError('EPUB navigation budget')
            except Exception:
                pass
        def get_title(path):
            if path in titles:return titles[path]
            try:
                content=read(path)
                m=re.search(r'<(?:title|h1)[^>]*>(.*?)</(?:title|h1)>',content.decode('utf-8','replace'),re.IGNORECASE|re.DOTALL)
                if m:
                    t=re.sub(r'<[^>]+>','',m.group(1)).strip()
                    if t:return t[:128]
            except Exception:
                pass
            return path.rsplit('/',1)[-1]
        if mode=='manifest':
            return {'format':mime,'chapters':[{'index':i,'title':get_title(path)} for i,path in enumerate(spine) if offset<=i<offset+limit],
                    'chapter_count':len(spine),'next_offset':offset+limit if offset+limit<len(spine) else None,
                    'navigation':navigation[offset:offset+limit],'navigation_count':len(navigation),
                    'navigation_next_offset':offset+limit if offset+limit<len(navigation) else None,
                    'scripts_executed':False,'external_resources_loaded':False}
        if chapter>=len(spine):raise ValueError('reader chapter unavailable')
        path=spine[chapter];parser=PlainText();parser.feed(read(path).decode('utf-8','replace'))
        untrimmed=''.join(parser.parts);leading=len(untrimmed)-len(untrimmed.lstrip());value=untrimmed.strip()
        if fragment:
            if fragment not in parser.anchors:raise ValueError('EPUB fragment unavailable')
            offset=max(0,parser.anchors[fragment]-leading)
        return {'chapter':chapter,'title':get_title(path),'text':value[offset:offset+limit],
                'offset':offset,'next_offset':offset+limit if offset+limit<len(value) else None,'total_characters':len(value),
                'scripts_executed':False,'external_resources_loaded':False}


class PlainText(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.parts=[];self.skip=0;self.length=0;self.anchors={}
    def add(self,value):self.parts.append(value);self.length+=len(value)
    def handle_starttag(self,tag,attrs):
        if tag in {'script','style','iframe','object'}:self.skip+=1
        if tag in {'p','div','br','h1','h2','h3','li'} and not self.skip:self.add('\n')
        if not self.skip:
            for key,value in attrs:
                if key=='id' and isinstance(value,str) and len(value)<=128:
                    if len(self.anchors)>=1024:raise ValueError('EPUB fragment budget')
                    self.anchors.setdefault(value,self.length)
    def handle_endtag(self,tag):
        if tag in {'script','style','iframe','object'}:self.skip=max(0,self.skip-1)
    def handle_data(self,data):
        if not self.skip:self.add(data)


def inert_text(raw):
    parser=PlainText();parser.feed(raw.decode('utf-8','replace'));return ''.join(parser.parts).strip()


def xml(raw):
    if b'\0' in raw or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise ValueError('XML declarations or unsupported encoding forbidden')
    return ET.fromstring(raw)


def extract(source,mime):
    if len(source)>MAX_SOURCE:raise ValueError('reader source limit')
    mime=sniff_format(source,mime)
    if mime in {'text/plain','text/markdown','text/html'}:
        value=inert_text(source) if mime=='text/html' else source.decode('utf-8','replace')
        return {'format':mime,'chapters':[{'title':'Text','text':value[:16000]}],'truncated':len(value)>16000,'scripts_executed':False}
    if mime=='application/zip+text':
        archive,names=safe_archive(source)
        chapters=[];total=0;truncated=False
        with archive:
            text_members=[n for n in names if not n.endswith('/') and posixpath.splitext(posixpath.basename(n).lower())[1] in TEXT_EXTENSIONS]
            text_members.sort(key=lambda s:[int(t) if t.isdigit() else t.casefold() for t in re.split(r'([0-9]+)',s)])
            for path in text_members:
                raw=archive.read(path)
                value=inert_text(raw) if posixpath.splitext(path.lower())[1] in {'.html','.htm','.xhtml'} else raw.decode('utf-8','replace')
                room=16000-total
                if room<=0 or len(chapters)>=64:truncated=True;break
                chapters.append({'title':posixpath.basename(path),'text':value[:room]});total+=min(room,len(value))
                if len(value)>room:truncated=True
        return {'format':mime,'chapters':chapters,'truncated':truncated,'scripts_executed':False,'external_resources_loaded':False}
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
        mimetype_data=read('mimetype').strip() if 'mimetype' in names else b''
        if mimetype_data!=b'application/epub+zip' and 'META-INF/container.xml' not in names:raise ValueError('EPUB mimetype')
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
            media_type=(member.get('media-type') or '').split(';')[0].strip().lower()
            if media_type not in {'application/xhtml+xml','text/html','text/plain','text/xml','application/xml'}:continue
            raw=read(path);value=inert_text(raw);room=16000-total
            if room<=0 or len(chapters)>=64:truncated=True;break
            title=path.rsplit('/',1)[-1]
            chapters.append({'title':title,'text':value[:room]});total+=min(room,len(value))
            if len(value)>room:truncated=True
        if not chapters:raise ValueError('EPUB has no readable spine')
    return {'format':mime,'chapters':chapters,'truncated':truncated,'scripts_executed':False,'external_resources_loaded':False}
