"""Authorized book covers rendered by the existing isolated document worker."""
from collections import OrderedDict
import hashlib
import json

from .document_sandbox import parse_document
from .library_formats import MAX_SOURCE,sniff_format
from .protocol import encoded


def cover(fabric,owner,book_id):
    with fabric.lock:
        book=fabric._get(owner,book_id,'book')
        explicit=book.get('cover','')
        object_id=explicit if isinstance(explicit,str) and explicit.startswith('cf1-') else book['file_id']
        info=json.loads(fabric.object_info(owner,object_id)['metadata'])
        key=hashlib.sha256(encoded([owner,book_id,object_id,info['digest']])).hexdigest()
        cache=getattr(fabric,'_cover_cache',None)
        if cache is None:fabric._cover_cache=cache=OrderedDict()
        if key in cache:
            result=cache.pop(key);cache[key]=result;return result
    if info['size']>MAX_SOURCE:return {'state':'unavailable','image':None}
    raw=b''.join(fabric.read_chunk(owner,object_id,i) for i in range((info['size']+16383)//16384))
    if 'sha256:'+hashlib.sha256(raw).hexdigest()!=info['digest']:raise ValueError('book cover source digest differs')
    mime=sniff_format(raw,info.get('mime'),info.get('name'))
    if object_id==book['file_id'] and mime not in {'application/epub+zip','application/pdf','application/vnd.comicbook+zip','application/x-cbz'}:
        return {'state':'unavailable','image':None}
    result=parse_document(raw,mime,'cover')
    result={'state':'available' if result.get('image') else 'unavailable',**result}
    with fabric.lock:
        current=fabric._get(owner,book_id,'book')
        if current.get('file_id')!=book['file_id'] or current.get('cover','')!=explicit:raise ValueError('book cover selection changed')
        cache[key]=result
        while len(cache)>64:cache.popitem(last=False)
    return result
