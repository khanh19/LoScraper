"""Deterministic degradation: no implicit provider routing or paid retries."""
import re
import psycopg
from .providers import ProviderDisabled
from .model import folded
from .announcements import social_sessions


def safe_reason(exc):
    value=str(exc)
    return value if re.fullmatch(r'[a-z][a-z0-9_]{0,95}',value) else type(exc).__name__


class ProviderCircuit:
    """One run's stop flags; persistent reservations remain the budget authority."""
    def __init__(self):self.blocked={}

    def call(self, provider, fn):
        if provider in self.blocked:
            raise ProviderDisabled('provider_circuit_open')
        try:return fn()
        except ProviderDisabled as exc:
            reason=safe_reason(exc)
            if (any(token in reason for token in ('budget','quota','allowance','not_configured','unavailable','accounting','receipt','free_credit','cost_exceeded'))
                or re.fullmatch(r'provider_http_(401|402|403|429|5\d\d)',reason)):
                self.blocked[provider]=reason
            raise ProviderDisabled(reason) from None
        except psycopg.Error:
            self.blocked[provider]='accounting_unavailable'
            raise ProviderDisabled('accounting_unavailable') from None
        except (ValueError,TypeError,KeyError,AttributeError):
            self.blocked[provider]='invalid_provider_response'
            raise ProviderDisabled('invalid_provider_response') from None

    def wrap(self, provider, client):
        circuit=self
        class Guarded:
            def __getattr__(self,name):
                value=getattr(client,name)
                if not callable(value):return value
                return lambda *args,**kwargs:circuit.call(provider,lambda:value(*args,**kwargs))
        return Guarded()


def deterministic_evidence(package):
    """Text evidence for review, never an LLM judgment or publication approval.

    Match complete reviewed venue name/address strings; no fuzzy matching,
    inferred prices, invented timestamps, or claims about unseen media.
    """
    sources=[s for s in package.get('sources',[]) if s.get('type') in {'text','subtitle','transcript'}]
    venues=sorted(package.get('verified_venues') or [],key=lambda v:(v.get('city_slug',''),v.get('name',''),v.get('address','')))
    matches=[]
    for venue in venues:
        if venue.get('revoked') or not venue.get('name') or not venue.get('address'):continue
        for source in sources:
            text=str(source.get('text',''))[:12000];flat=' '+folded(text)+' '
            if all(' '+folded(venue[k])+' ' in flat for k in ('name','address')):
                matches.append({'venue_name':venue['name'],'address':venue['address'],'city_slug':venue['city_slug'],
                    'location_evidence':venue.get('evidence_url'),'source_id':source['id'],'quote':text[:12000]})
                break
    caption=next((s.get('text','') for s in sources if s.get('id')=='caption'),'')
    sessions,reason=social_sessions(caption,package.get('published_at'))
    return {'method':'deterministic_text_v1','published':False,'validation_status':'needs_review',
        'published_at':package.get('published_at'),'source_verified_at':str(package.get('fetched_at','')),
        'matched_destinations':matches,'session_candidates':[vars(s) for s in sessions],
        'reasons':sorted(set(['human_fact_review_required']+([] if matches else ['independent_destination_unresolved'])+
            ([reason] if reason else [])+([] if package.get('verification_known') else ['snapshot_verification_time_unknown']))),
        'media_analyzed':False,'price_text':None}
