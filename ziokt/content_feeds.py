"""Permission-filtered RSS 2.0, Atom and JSON Feed 1.1 over actual application data."""
import datetime,hashlib,json,time
from email.utils import parsedate_to_datetime,format_datetime
from urllib.parse import urlencode,urlsplit
import xml.etree.ElementTree as ET

ATOM='http://www.w3.org/2005/Atom';DC='http://purl.org/dc/elements/1.1/';ZIOKT='https://ziokt.com/ns/content/1'
ET.register_namespace('atom',ATOM);ET.register_namespace('dc',DC);ET.register_namespace('ziokt',ZIOKT)
FORMATS={'rss':'application/rss+xml; charset=utf-8','atom':'application/atom+xml; charset=utf-8','json':'application/feed+json; charset=utf-8'}
SOURCES=('all','library','netnews','community')


def _date(value):
 try:
  if isinstance(value,str):date=parsedate_to_datetime(value)
  elif type(value) is int:date=datetime.datetime.fromtimestamp(value,datetime.timezone.utc)
  else:return None
  if date.tzinfo is None:return None
  return date.astimezone(datetime.timezone.utc)
 except (ValueError,TypeError,OverflowError,OSError):return None


def collect(fabric,owner,source='all',group='',limit=30,offset=0,*,include_community=True):
 if source not in SOURCES or type(limit) is not int or not 1<=limit<=50 or type(offset) is not int or not 0<=offset<=100000:raise ValueError('feed bounds/source')
 if group and source!='netnews':raise ValueError('group filter requires netnews source')
 items=[];unavailable=[]
 if source in {'all','library','netnews'}:
  kinds=['book','article'] if source=='all' else ['book' if source=='library' else 'article']
  with fabric.lock:
   if group:
    policy=fabric.db.execute('SELECT * FROM groups WHERE name=?',(group,)).fetchone()
    if not policy or (policy['visibility']!='public' and policy['owner']!=owner):raise PermissionError('feed group unavailable')
   query="SELECT r.* FROM records r WHERE r.kind IN ("+','.join('?' for _ in kinds)+") AND r.deleted=0 AND (r.expires=0 OR r.expires>?) AND (r.visibility='public' OR r.owner=?)"
   args=[*kinds,int(time.time()),owner]
   if group:query+=' AND EXISTS(SELECT 1 FROM group_articles g WHERE g.message=r.id AND g.name=?)';args.append(group)
   rows=fabric.db.execute(query+' ORDER BY r.rowid DESC LIMIT ? OFFSET ?',(*args,limit,offset)).fetchall()
   for row in rows:
    body=json.loads(row['body']);is_book=row['kind']=='book';published=_date(body.get('updated_at') if is_book else body.get('date'))
    if published is None:
     event=fabric.db.execute('SELECT envelope FROM events WHERE id=?',(row['event'],)).fetchone();published=_date(json.loads(event[0])['payload']['at']) if event else None
    items.append({'source':'library' if is_book else 'netnews','native_id':row['id'],'origin':row['origin'],'title':body.get('title' if is_book else 'subject',''),'text':body.get('description',body.get('text','')) if is_book else body.get('body',''),'authors':body.get('authors',[]) if is_book else [body.get('from','')],'tags':body.get('tags',[]) if is_book else body.get('newsgroups',[]),'published':published,'date_kind':'node_updated' if is_book else 'publisher_supplied','attachments':([{'id':body['file_id'],'name':body.get('title','book'),**body.get('file',{})}] if is_book and body.get('file_id') else body.get('attachments',[])),'references':body.get('references',[])})
 if source=='community' or (source=='all' and include_community):
  if fabric.community_config.get('accounts',{}).get(owner):
   from .community_application import invoke
   page=invoke(fabric.community_config,owner,'community.forum.list',{'limit':limit,'offset':offset})
   for event in page['items']:
    if event['deleted']:continue
    # Native Community events have no publisher timestamp. Persist the actual
    # first observation instead of inventing a publication time.
    with fabric.transaction():
     existing=fabric.db.execute('SELECT observed FROM feed_observations WHERE owner=? AND source=? AND native=?',(owner,'community',event['native_id'])).fetchone()
     if not existing:
      if fabric.db.execute('SELECT count(*) FROM feed_observations WHERE owner=?',(owner,)).fetchone()[0]>=50000:raise ValueError('feed observation quota')
      observed=int(time.time());fabric.db.execute('INSERT INTO feed_observations VALUES(?,?,?,?)',(owner,'community',event['native_id'],observed))
     else:observed=existing[0]
    body=event['body'];items.append({'source':'community','native_id':event['native_id'],'origin':event['proof']['public_key'],'title':body.get('title',''),'text':body.get('text',''),'authors':[event['author']],'tags':['community'],'published':_date(observed),'date_kind':'first_observed','attachments':[],'references':[body['reply_to']] if body.get('reply_to') else [],'proof':event['proof']})
  elif source=='community':raise PermissionError('native community delegation required')
  else:unavailable.append({'source':'community','reason':'no delegated native account'})
 items.sort(key=lambda item:((item['published'].timestamp() if item['published'] else 0),item['origin'],item['native_id']),reverse=True)
 return {'items':items[:limit],'unavailable':unavailable,'limit':limit,'offset':offset,'source':source}


def render(fabric,owner,base_url,source='all',fmt='atom',group='',limit=30,offset=0,*,include_community=False):
 if fmt not in FORMATS:raise ValueError('feed format')
 parsed=urlsplit(base_url)
 if parsed.scheme not in {'https','http'} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:raise ValueError('feed base URL')
 base_url=base_url.rstrip('/');page=collect(fabric,owner,source,group,limit,offset,include_community=include_community);items=[]
 for value in page['items']:
  item=dict(value)
  def clean(text):return ''.join(char for char in str(text) if char in '\t\n\r' or 32<=ord(char)<=0xD7FF or 0xE000<=ord(char)<=0xFFFD or 0x10000<=ord(char)<=0x10FFFF)
  item['title']=clean(item['title']);item['text']=clean(item['text']);item['authors']=[clean(name) for name in item['authors']];item['tags']=[clean(tag) for tag in item['tags']]
  item['id']='urn:ziokt:'+item['source']+':'+item['origin']+':'+hashlib.sha256(item['native_id'].encode()).hexdigest()
  item['url']=base_url+'/?'+urlencode({'book' if item['source']=='library' else 'article':item['native_id']}) if item['source'] in {'library','netnews'} else None
  item['truncated']=len(item['text'])>2000;item['text']=item['text'][:2000]+('\n[Excerpt: open the original for the complete content.]' if item['truncated'] else '')
  item['available_attachments']=[];item['remote_attachments']=[]
  for attachment in item['attachments']:
   available=False
   try:
    with fabric.lock:metadata=json.loads(fabric.object_info(owner,attachment['id'])['metadata'])
    available=metadata['digest']==attachment.get('digest') and metadata['size']==attachment.get('size')
   except (PermissionError,ValueError,KeyError):pass
   descriptor={'url':base_url+'/objects/'+attachment['id'],'mime_type':attachment.get('mime','application/octet-stream'),'size_in_bytes':attachment.get('size',0),'title':attachment.get('name','attachment')}
   (item['available_attachments'] if available else item['remote_attachments']).append(descriptor)
  items.append(item)
 query={'limit':limit,'offset':offset}
 if group:query['group']=group
 self_url=base_url+'/feeds/'+source+'.'+fmt+'?'+urlencode(query);title='Ziokt '+(group or source)+' feed';epoch=_date(0);updated=max((i['published'] or epoch for i in items),default=epoch)
 def stamp(date):return date.isoformat().replace('+00:00','Z')
 def metadata(item):return {'source':item['source'],'origin':item['origin'],'native_id':item['native_id'],'date_kind':item['date_kind'],'excerpt':item['truncated'],'references':item['references'],'remote_attachments':item['remote_attachments'],**({'proof':item['proof']} if 'proof' in item else {})}
 if fmt=='json':
  result={'version':'https://jsonfeed.org/version/1.1','title':title,'home_page_url':base_url+'/','feed_url':self_url,'items':[],'_ziokt':{'unavailable_sources':page['unavailable']}}
  for item in items:
   entry={'id':item['id'],'title':item['title'],'content_text':item['text'],'authors':[{'name':name} for name in item['authors'] if name],'tags':item['tags'],'_ziokt':metadata(item)}
   if item['url']:entry['url']=item['url']
   if item['published']:entry['date_published']=stamp(item['published'])
   if item['available_attachments']:entry['attachments']=item['available_attachments']
   result['items'].append(entry)
  output=json.dumps(result,ensure_ascii=False,separators=(',',':')).encode()
 elif fmt=='atom':
  root=ET.Element('{'+ATOM+'}feed');ET.SubElement(root,'{'+ATOM+'}id').text=self_url;ET.SubElement(root,'{'+ATOM+'}title').text=title;ET.SubElement(root,'{'+ATOM+'}updated').text=stamp(updated);ET.SubElement(ET.SubElement(root,'{'+ATOM+'}author'),'{'+ATOM+'}name').text='Ziokt';ET.SubElement(root,'{'+ATOM+'}link',href=self_url,rel='self',type=FORMATS[fmt].split(';')[0]);ET.SubElement(root,'{'+ATOM+'}link',href=base_url+'/',rel='alternate')
  for item in items:
   entry=ET.SubElement(root,'{'+ATOM+'}entry');ET.SubElement(entry,'{'+ATOM+'}id').text=item['id'];ET.SubElement(entry,'{'+ATOM+'}title').text=item['title'];ET.SubElement(entry,'{'+ATOM+'}updated').text=stamp(item['published'] or epoch);ET.SubElement(entry,'{'+ATOM+'}content',type='text').text=item['text']
   if item['url']:ET.SubElement(entry,'{'+ATOM+'}link',href=item['url'],rel='alternate')
   for name in item['authors']:ET.SubElement(ET.SubElement(entry,'{'+ATOM+'}author'),'{'+ATOM+'}name').text=name
   for tag in item['tags']:ET.SubElement(entry,'{'+ATOM+'}category',term=tag)
   for attachment in item['available_attachments']:ET.SubElement(entry,'{'+ATOM+'}link',href=attachment['url'],rel='enclosure',type=attachment['mime_type'],length=str(attachment['size_in_bytes']))
   ET.SubElement(entry,'{'+ZIOKT+'}provenance').text=json.dumps(metadata(item),ensure_ascii=False)
  output=ET.tostring(root,encoding='utf-8',xml_declaration=True)
 else:
  root=ET.Element('rss',version='2.0');channel=ET.SubElement(root,'channel');ET.SubElement(channel,'title').text=title;ET.SubElement(channel,'link').text=base_url+'/';ET.SubElement(channel,'description').text='Authorized Ziokt application updates; content remains at its native source.';ET.SubElement(channel,'lastBuildDate').text=format_datetime(updated,usegmt=True);ET.SubElement(channel,'{'+ATOM+'}link',href=self_url,rel='self',type='application/rss+xml')
  for item in items:
   entry=ET.SubElement(channel,'item');ET.SubElement(entry,'guid',isPermaLink='false').text=item['id'];ET.SubElement(entry,'title').text=item['title'];ET.SubElement(entry,'description').text=item['text']
   if item['url']:ET.SubElement(entry,'link').text=item['url']
   if item['published']:ET.SubElement(entry,'pubDate').text=format_datetime(item['published'],usegmt=True)
   for name in item['authors']:ET.SubElement(entry,'{'+DC+'}creator').text=name
   for tag in item['tags']:ET.SubElement(entry,'category').text=tag
   # RSS permits one enclosure per item. Atom/JSON preserve multiple enclosures.
   if item['available_attachments']:
    attachment=item['available_attachments'][0];ET.SubElement(entry,'enclosure',url=attachment['url'],type=attachment['mime_type'],length=str(attachment['size_in_bytes']))
   ET.SubElement(entry,'{'+ZIOKT+'}provenance').text=json.dumps(metadata(item),ensure_ascii=False)
  output=ET.tostring(root,encoding='utf-8',xml_declaration=True)
 if len(output)>1024*1024:raise ValueError('feed output budget')
 return output,FORMATS[fmt],'"'+hashlib.sha256(output).hexdigest()+'"'


def describe(base_url):
 return {'schema':'ziokt.feeds.v1','formats':FORMATS,'sources':['library','netnews','community'],'unified':base_url.rstrip('/')+'/feeds/all.atom','urls':{source:{fmt:base_url.rstrip('/')+'/feeds/'+source+'.'+fmt for fmt in FORMATS} for source in SOURCES},'private_access':'scoped bearer or HTTP Basic credentials over HTTPS; Community requires native delegation','native_adapters_pending':['corium','etp','shadow6','wiki','broadcast']}


def opml(fabric,owner,base_url):
 root=ET.Element('opml',version='2.0');head=ET.SubElement(root,'head');ET.SubElement(head,'title').text='Ziokt authorized subscriptions';body=ET.SubElement(root,'body')
 for source in ('all','library','netnews'):ET.SubElement(body,'outline',text='Ziokt '+source,title='Ziokt '+source,type='rss',xmlUrl=base_url.rstrip('/')+'/feeds/'+source+'.atom',htmlUrl=base_url.rstrip('/')+'/')
 with fabric.lock:
  if owner=='@anonymous':groups=fabric.db.execute("SELECT name FROM groups WHERE visibility='public' ORDER BY name LIMIT 256").fetchall()
  else:groups=fabric.db.execute("SELECT g.name FROM groups g JOIN subscriptions s ON s.target=g.name AND s.kind='newsgroup' AND s.owner=? WHERE g.visibility='public' OR g.owner=? ORDER BY g.name LIMIT 256",(owner,owner)).fetchall()
 for group in groups:ET.SubElement(body,'outline',text=group['name'],title=group['name'],type='rss',xmlUrl=base_url.rstrip('/')+'/feeds/netnews.atom?'+urlencode({'group':group['name']}),htmlUrl=base_url.rstrip('/')+'/')
 return ET.tostring(root,encoding='utf-8',xml_declaration=True)
