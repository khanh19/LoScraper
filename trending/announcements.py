"""Conservative text-only organizer announcements; never infer facts from media."""
from datetime import datetime, timedelta
import re
from .dates import plain
from .model import Candidate, Occurrence, ICT, folded, parse_time, city_from_address
from .providers import post_platform


def social_sessions(text, published_at):
    published=parse_time(published_at)
    if not published:return [],'unknown_publication_time'
    published=published.astimezone(ICT);value=plain(text)
    if re.search(r'\b(recap|da dien ra|nhin lai|throwback)\b',value):return [],'past_recap'
    # Explicit dates override relative language; never assume a missing year.
    dates=[]
    # A fully written range is not a list of two sessions. Without explicit
    # recurrence evidence we cannot infer daily opening hours between endpoints.
    if re.search(r'\b\d{1,2}/\d{1,2}/20\d{2}\s*(?:-|den|toi)\s*\d{1,2}/\d{1,2}/20\d{2}\b',value):
        return [],'unresolved_individual_sessions'
    span=re.search(r'\b(\d{1,2})\s*-\s*(\d{1,2})/(\d{1,2})/(20\d{2})\b',value)
    try:
        if span:
            a,b,m,y=map(int,span.groups())
            if b<a:return [],'ambiguous_schedule'
            dates=[datetime(y,m,d,tzinfo=ICT) for d in range(a,b+1)]
        else:
            dates=[datetime(int(y),int(m),int(d),tzinfo=ICT) for d,m,y in re.findall(r'\b(\d{1,2})/(\d{1,2})/(20\d{2})\b',value)]
        if not dates:
            if re.search(r'\d{1,2}/\d{1,2}',value):return [],'missing_event_year'
            if 'cuoi tuan' in value:return [],'ambiguous_weekend'
            if re.search(r'\b(hom nay|toi nay)\b',value):dates=[published.replace(hour=0,minute=0,second=0,microsecond=0)]
            else:
                daynames={'thu hai':0,'thu ba':1,'thu tu':2,'thu nam':3,'thu sau':4,'thu bay':5,'chu nhat':6}
                matched=[v for k,v in daynames.items() if k in value]
                if len(matched)!=1:return [],'missing_event_date'
                dates=[published.replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=(matched[0]-published.weekday())%7)]
        clocks=re.findall(r'\b(\d{1,2})[:h](\d{2})\s*-\s*(\d{1,2})[:h](\d{2})\b',value)
        if len(clocks)>1:return [],'unresolved_individual_sessions'
        out=[]
        for date in sorted(set(dates)):
            if clocks:
                ah,am,bh,bm=map(int,clocks[0]);start=date.replace(hour=ah,minute=am);end=date.replace(hour=bh,minute=bm)
                if end<=start:end+=timedelta(days=1)
                if end<=published:return [],'past_recap'
                out.append(Occurrence(start.isoformat(),end.isoformat(),'time'))
            else:
                if any(x in value for x in ['toi nay','hom nay','thu ','chu nhat']):return [],'relative_date_without_hours'
                out.append(Occurrence(date.isoformat(),(date+timedelta(days=1)).isoformat(),'date'))
        return out,None
    except ValueError:return [],'invalid_schedule'


def announcement(row, account, venue, now):
    """Inputs account/venue must be fetched from reviewed operator registry, not a post."""
    if account.get('revoked') or venue.get('revoked'):return None,'revoked_authority'
    if account.get('publisher_id')!=venue.get('publisher_id'):return None,'publisher_venue_mismatch'
    platform=post_platform(row.get('url',''))
    if platform!=account.get('platform'):return None,'platform_mismatch'
    owner=str(row.get('profile_url') or row.get('user_url') or row.get('user_posted') or '').rstrip('/')
    if owner!=account['owner_key'].rstrip('/'):return None,'account_mismatch'
    text=str(row.get('description') or row.get('content') or '')
    if folded(venue['name']) not in folded(text) or city_from_address(text)!=venue['city_slug']:
        return None,'unverified_destination'
    title=next((line.strip(' #🍔🎟️🎉🔥📅') for line in text.splitlines() if line.strip()),'')
    if not re.search(r'\b(fest|festival|le hoi|trien lam|workshop|show|concert|dem nhac|giai|pop up|cho phien|dj)\b',folded(title)):
        return None,'missing_event_identity'
    published=row.get('date_posted') or row.get('create_time') or row.get('date')
    date=parse_time(published)
    if not date or not now-timedelta(days=7)<=date<=now:return None,'no_recent_evidence'
    sessions,reason=social_sessions(text,published)
    if reason:return None,reason
    from .adapters import category
    c=Candidate(platform,platform.title(),row['url'],title,'event',venue_name=venue['name'],address=venue['address'],city_slug=venue['city_slug'],category=category(text),original_text=text,published_at=published,verified_at=now.isoformat(),occurrences=sessions,location_evidence=venue['evidence_url'],platform=platform,owner_key=account['owner_key'],authority_type='organizer',verified_venue_id=str(venue['id']))
    reasons=c.validate(now)
    return (None,','.join(reasons)) if reasons else (c,None)
