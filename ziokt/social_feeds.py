"""Explicit operator-selected RSS/Atom sources; no signatures are invented."""
import hashlib
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit
from urllib.request import Request,build_opener
from .content_server import NoRedirect


def read(config,owner,alias):
    url=config.get('rss',{}).get(owner,{}).get(alias)
    if not isinstance(url,str):raise PermissionError('feed not delegated')
    parsed=urlsplit(url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:raise ValueError('explicit HTTPS feed required')
    with build_opener(NoRedirect()).open(Request(url,headers={'Accept':'application/atom+xml,application/rss+xml','User-Agent':'Ziokt/1.0'}),timeout=10) as response:
        raw=response.read(524289)
    if len(raw)>524288 or b'<!doctype' in raw.lower() or b'<!entity' in raw.lower():raise ValueError('bounded entity-free feed required')
    root=ET.fromstring(raw);atom='{http://www.w3.org/2005/Atom}'
    entries=root.findall('./channel/item') if root.tag=='rss' else root.findall(atom+'entry')
    if len(entries)>1000:raise ValueError('feed item quota')
    result=[]
    for entry in entries:
        def text(*names):
            for name in names:
                e=entry.find(name)
                if e is not None:return ''.join(e.itertext())[:32768]
            return ''
        content=text('description',atom+'content',atom+'summary');title=text('title',atom+'title');id=text('guid',atom+'id','link') or hashlib.sha256(ET.tostring(entry)).hexdigest()
        result.append({'id':id,'title':title,'text':content,'origin':url,'author':text('author',atom+'author'),'version':hashlib.sha256(ET.tostring(entry)).hexdigest(),'signature_status':'not_provided','native_entry':ET.tostring(entry,encoding='unicode')})
    return {'items':result}
