"""Bounded multilingual bibliography; localized display never rewrites signed metadata."""
import re

LANGUAGE=re.compile(r'[A-Za-z]{2,8}(?:-[A-Za-z]{4})?(?:-(?:[A-Za-z]{2}|[0-9]{3}))?(?:-(?:[A-Za-z0-9]{5,8}|[0-9][A-Za-z0-9]{3}))*\Z')
FIELDS={'title','subtitle','description','publisher','authors','translators'}


def language(value):
    if not isinstance(value,str) or len(value)>63 or not LANGUAGE.fullmatch(value):raise ValueError('bounded language tag required')
    parts=value.split('-');canonical=[parts[0].lower()]
    for part in parts[1:]:canonical.append(part.title() if len(part)==4 and part.isalpha() else part.upper() if len(part)==2 and part.isalpha() else part.lower())
    return '-'.join(canonical)


def validate(value):
    if not isinstance(value,dict) or not 1<=len(value)<=16:raise ValueError('one to sixteen localized editions required')
    output={}
    for tag,entry in value.items():
        tag=language(tag)
        if tag in output:raise ValueError('duplicate canonical language')
        if not isinstance(entry,dict) or set(entry)-FIELDS or 'title' not in entry:raise ValueError('localized bibliography fields')
        localized={}
        for field,text in entry.items():
            if field in {'authors','translators'}:
                if not isinstance(text,list) or len(text)>64:raise ValueError('localized contributor list')
                if any(not isinstance(item,str) or not item or len(item.encode())>512 or '\0' in item for item in text):raise ValueError('localized contributor name')
            elif not isinstance(text,str) or len(text.encode())>(4096 if field=='description' else 2048) or '\0' in text or (field=='title' and not text):raise ValueError('localized text budget')
            localized[field]=text
        output[tag]=localized
    return output


def display(value,locale):
    result=dict(value)
    if not locale:return result
    tag=language(locale);entries=result.get('localized_metadata',{})
    if not isinstance(entries,dict):raise ValueError('localized bibliography')
    selected=tag if tag in entries else tag.split('-')[0] if tag.split('-')[0] in entries else None
    result['metadata_locale']=selected or 'default'
    if selected:
        result['default_title']=result.get('title','')
        result.update(entries[selected])
    return result
