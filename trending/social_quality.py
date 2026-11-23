"""Discovery triage, not publication approval or demographic inference."""
import re
from unicodedata import normalize
from .model import folded

ACTIVITY_TERMS=('photobooth','workshop','trien lam','le hoi','caphe','ca phe','cafe','quan an','nha hang','cho phien','pop up','tha dieu','concert','nhac song','di bo','su kien','3d mapping','lop yoga','special class')
WEATHER_TERMS=('thoi tiet','du bao','mua to','mua lanh','gio manh','weather')

def triage(text):
    text=folded(normalize('NFKC', text or ''))
    activity=any(t in text for t in ACTIVITY_TERMS)
    weather=any(t in text for t in WEATHER_TERMS)
    # Mixed posts remain leads; never blacklist an entire publisher by topic.
    return {'priority':2 if activity else 0 if weather else 1,
            'reason':'activity_lead' if activity else 'weather_without_activity' if weather else 'insufficient_text',
            'publishable':False}

def parse_vtt(text,language=None):
    """Bounded original ASR cues; no implied speech relevance or translation."""
    out=[]
    if not isinstance(text,str) or len(text.encode())>200000:return out
    stamp=r'(\d{2}):(\d{2}):(\d{2})[.,](\d{3})'
    def seconds(parts):return int(parts[0])*3600+int(parts[1])*60+int(parts[2])+int(parts[3])/1000
    for block in re.split(r'\n\s*\n',text.replace('\r','')):
        m=re.search(stamp+r'\s*-->\s*'+stamp+ r'[^\n]*\n(.+)',block,re.S)
        if not m:continue
        a,b=seconds(m.groups()[:4]),seconds(m.groups()[4:8]);content=re.sub('<[^>]+>','',m.group(9)).strip()
        if b<=a or not content:continue
        out.append({'id':f'subtitle_{len(out)}','type':'subtitle','text':content[:2000],
                    'start_seconds':a,'end_seconds':b,'language':language,'relevance':'unassessed','origin':'platform_subtitle'})
        if len(out)>=300:break
    return out
