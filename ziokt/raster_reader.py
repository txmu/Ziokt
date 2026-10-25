"""PDF/CBZ pages decoded only after the document worker enters seccomp."""
import base64
import encodings.utf_16_le
import io
import math
import re
import warnings
import zipfile
from pathlib import PurePosixPath
import pypdfium2 as pdfium
from PIL import Image, PngImagePlugin, JpegImagePlugin, WebPImagePlugin, GifImagePlugin

MIMES={'application/pdf','application/vnd.comicbook+zip','application/x-cbz','application/zip','application/x-zip-compressed'}
IMAGE_FORMATS=['PNG','JPEG','WEBP','GIF']
IMAGE_EXTENSIONS={'.png','.jpg','.jpeg','.webp','.gif'}
IGNORED_CBZ_MEMBERS={'comicinfo.xml','thumbs.db','.ds_store','desktop.ini','metadata.json','info.txt'}
MAX_PIXELS=8_000_000
Image.init()  # Import trusted codecs before the worker denies filesystem access.
Image.MAX_IMAGE_PIXELS=MAX_PIXELS
warnings.simplefilter('error',Image.DecompressionBombWarning)


def encoded_image(image):
    image.thumbnail((1200,1200))
    if image.mode!='RGB':image=image.convert('RGB')
    for quality in (85,70,50,30):
        output=io.BytesIO();image.save(output,format='JPEG',quality=quality)
        raw=output.getvalue()
        if len(raw)<=100000:
            return {'mime':'image/jpeg','data':base64.b64encode(raw).decode('ascii'),'width':image.width,'height':image.height}
    raise ValueError('rendered page response budget')


def cover_image(raw):
    if not isinstance(raw,bytes) or not 0<len(raw)<=4*1024*1024:raise ValueError('cover image byte budget')
    with Image.open(io.BytesIO(raw),formats=IMAGE_FORMATS) as image:
        if image.width*image.height>MAX_PIXELS:raise ValueError('cover image pixel budget')
        image.load();thumb=image.copy();thumb.thumbnail((360,540))
    return {'image':encoded_image(thumb),'rendered_in_sandbox':True,'external_resources_loaded':False}


def read(source,mime,mode,*,chapter=0,offset=0,limit=64,fragment=''):
    if mode not in {'manifest','chapter','preview'}:raise ValueError('page index')
    if mode=='preview':
        if mime=='application/pdf':
            if not source.startswith(b'%PDF-'):raise ValueError('PDF signature')
            doc=pdfium.PdfDocument(source)
            try:
                count=len(doc);chapters=[];total=0;truncated=False
                for p in range(min(count,16)):
                    page=doc[p]
                    try:
                        textpage=page.get_textpage()
                        try:
                            nchars=textpage.count_chars();room=16000-total
                            txt=textpage.get_text_range(0,min(room,nchars)) if room>0 else ''
                            chapters.append({'title':'Page '+str(p+1),'text':txt});total+=len(txt)
                            if total>=16000:truncated=True;break
                        finally:textpage.close()
                    finally:page.close()
                return {'format':mime,'chapters':chapters,'truncated':truncated or count>16,'scripts_executed':False}
            finally:doc.close()
        else:
            return {'format':mime,'chapters':[{'title':'Page 1','text':''}],'truncated':False,'scripts_executed':False}
    if type(chapter) is not int or not 0<=chapter<1024:raise ValueError('page index')
    if type(offset) is not int or not 0<=offset<=16*1024*1024 or type(limit) is not int or not 1<=limit<=(128 if mode=='manifest' else 16384) or fragment:raise ValueError('page bounds')
    if mime=='application/pdf':
        if not source.startswith(b'%PDF-'):raise ValueError('PDF signature')
        doc=pdfium.PdfDocument(source)
        try:
            count=len(doc)
            if not 1<=count<=1024:raise ValueError('PDF page count')
            if mode=='manifest':return manifest(mime,count,offset,limit)
            if chapter>=count:raise ValueError('page unavailable')
            page=doc[chapter]
            try:
                width,height=page.get_size()
                if not all(math.isfinite(v) and 0<v<=100000 for v in (width,height)):raise ValueError('PDF page dimensions')
                scale=min(2,1200/max(width,height))
                bitmap=page.render(scale=scale,draw_annots=False)
                try:image=bitmap.to_pil().copy()
                finally:bitmap.close()
                # Bounded text is selectable through the existing reader paging API.
                textpage=page.get_textpage()
                try:
                    total=textpage.count_chars()
                    if total>1_000_000:raise ValueError('PDF text budget')
                    text=textpage.get_text_range(offset,min(limit,max(0,total-offset))) if offset<total else ''
                finally:textpage.close()
            finally:page.close()
        finally:doc.close()
    else:
        if mime not in MIMES:raise ValueError('unsupported raster format')
        with zipfile.ZipFile(io.BytesIO(source)) as archive:
            entries=archive.infolist();names=set();pages=[]
            if not 1<=len(entries)<=2048 or sum(e.file_size for e in entries)>32*1024*1024:raise ValueError('CBZ expansion budget')
            for e in entries:
                path=PurePosixPath(e.filename)
                if len(e.filename.encode())>1024 or e.filename in names or path.is_absolute() or '..' in path.parts or '\\' in e.filename or '\0' in e.filename or e.flag_bits&1:raise ValueError('CBZ path or encryption')
                names.add(e.filename)
                if e.file_size>4*1024*1024 or e.file_size>max(1024,e.compress_size*200):raise ValueError('CBZ member budget')
                if not e.is_dir():
                    name_lower=path.name.lower()
                    if name_lower in IGNORED_CBZ_MEMBERS or name_lower.endswith(('.nfo','.txt')) or name_lower.startswith('.') or any(p.startswith('__MACOSX') for p in path.parts):continue
                    if path.suffix.lower() not in IMAGE_EXTENSIONS:continue
                    pages.append(e.filename)
            pages.sort(key=lambda name:[int(value) if value.isascii() and value.isdigit() else value.casefold() for value in re.split(r'([0-9]+)',name)]);count=len(pages)
            if not 1<=count<=1024:raise ValueError('CBZ page count')
            if mode=='manifest':return manifest(mime,count,offset,limit)
            if chapter>=count:raise ValueError('page unavailable')
            raw=archive.read(pages[chapter])
            with Image.open(io.BytesIO(raw),formats=IMAGE_FORMATS) as candidate:
                if candidate.width*candidate.height>MAX_PIXELS:raise ValueError('CBZ image pixels')
                candidate.load();image=candidate.copy()
        text='';total=0
    return {'chapter':chapter,'title':'Page '+str(chapter+1),'image':encoded_image(image),'text':text,'offset':offset,'next_offset':offset+limit if offset+limit<total else None,'total_characters':total,'scripts_executed':False,'external_resources_loaded':False,'rendered_in_sandbox':True}


def manifest(mime,count,offset,limit):
    return {'format':mime,'chapter_count':count,'chapters':[{'index':i,'title':'Page '+str(i+1)} for i in range(offset,min(count,offset+limit))],'next_offset':offset+limit if offset+limit<count else None,'navigation':[],'navigation_next_offset':None,'scripts_executed':False,'external_resources_loaded':False,'rendered_in_sandbox':True}
