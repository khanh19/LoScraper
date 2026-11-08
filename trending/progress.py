"""Run receipts and bounded recovery; never replay a failed database operation."""
from collections import Counter

import psycopg


class Progress:
    def __init__(self, store, sources, cities):
        self.store = store
        self.cities = list(cities)
        self.sources = list(sources)
        self.available = True
        self.reconnect_attempted = getattr(store,'initial_reconnect',False) is True
        self.errors = Counter()
        self.unassigned_failures = 0
        if self.reconnect_attempted:
            self.errors['initial_connection_recovered'] = 1
            self.unassigned_failures = 1
        self.fatal = False
        self.source_error_start = 0
        self.source = None
        self.run_id = None
        self.source_id = None
        self.stats = {}
        if store:
            ok,self.run_id = self.call('start_run',sources,self.cities)
            if not ok:
                # A missing/ambiguous initial receipt cannot safely anchor any imports.
                self.available = False
                self.fatal = True

    def call(self, method, *args, **kwargs):
        if not self.available:
            return False, None
        try:
            return True, getattr(self.store, method)(*args, **kwargs)
        except Exception as exc:
            if isinstance(exc, ValueError) and str(exc) == 'identity_conflict':
                return False, 'identity_conflict'
            # SQL error details can include row contents, connection strings or secrets.
            self.errors[type(exc).__name__] += 1
            # Candidate failures are counted by the caller; receipt failures have no candidate.
            if method in {'progress','cleanup'}:
                if self.source:
                    self.fail('persistence_' + type(exc).__name__)
                else:
                    self.unassigned_failures += 1
            elif self.source is None:
                self.unassigned_failures += 1
            if isinstance(exc, (psycopg.OperationalError, psycopg.InterfaceError)) or self.store.db.closed:
                if not self.reconnect_attempted:
                    self.reconnect_attempted = True
                    try:
                        self.store.reconnect()
                    except Exception:
                        self.available = False
                        self.errors['reconnect_failed'] += 1
                else:
                    self.available = False
            # The original operation may have committed. Do not replay it.
            return False, None

    def start_source(self, slug):
        self.source_error_start = sum(self.errors.values())
        self.source = slug
        self.stats[slug] = dict(accepted=0,rejected=0,failed=0,reasons={},failures=[],cities={},status='running')
        self.source_id = None
        if self.store:
            ok, self.source_id = self.call('start_run',[slug],self.cities,slug,self.run_id)
            if not ok:
                self.fail('receipt_start_failed')
        self.heartbeat()
        return self.stats[slug]

    def fail(self, reason):
        s = self.stats[self.source]
        s['failed'] += 1
        s['reasons'][reason] = s['reasons'].get(reason,0)+1

    def count(self, outcome, city, reasons=()):
        s = self.stats[self.source]
        s[outcome] += 1
        bucket = s['cities'].setdefault(city if city in self.cities else 'unclassified',
                                       dict(accepted=0,rejected=0,failed=0))
        bucket[outcome] += 1
        for reason in reasons:
            s['reasons'][reason] = s['reasons'].get(reason,0)+1
        self.heartbeat()

    def totals(self):
        return [sum(s[k] for s in self.stats.values()) for k in ('accepted','rejected','failed')]

    def status(self):
        if not self.available or self.fatal:
            return 'failed'
        if self.errors or any(s['failed'] for s in self.stats.values()):
            return 'partial' if any(s['accepted'] or s['status']=='complete' for s in self.stats.values()) else 'failed'
        return 'complete'

    def heartbeat(self, final=False):
        if not self.store or not self.available:
            return
        if self.source_id:
            s = self.stats[self.source]
            self.call('progress',self.source_id,s['accepted'],s['rejected'],s['failed'],
                      dict(parent_id=self.run_id,**s),s['status'])
        a,r,f = self.totals()
        self.call('progress',self.run_id,a,r,f+self.unassigned_failures,
                  {'sources':self.stats,'persistence_errors':dict(self.errors)},self.status() if final else 'running')

    def finish_source(self):
        s = self.stats[self.source]
        error_count = sum(self.errors.values())-self.source_error_start
        s['persistence_errors'] = error_count
        s['status'] = ('partial' if s['accepted'] else 'failed') if s['failed'] or error_count else 'complete'
        self.heartbeat()
