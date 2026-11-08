"""Bootstrap an EMPTY teammate database on a dedicated loopback Postgres cluster.

Run from LoScraper with its virtualenv. This is not a production migration runner.
It deliberately omits historical demo venues and remote city cover images.
"""
import argparse
from pathlib import Path

import psycopg
from psycopg import sql


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=55440)
    parser.add_argument('--user', required=True)
    parser.add_argument('--database', default='lo_teammate_preview')
    parser.add_argument('--backend', type=Path, default=Path('../LoAppBackend'))
    args = parser.parse_args()
    if args.database != 'lo_teammate_preview' and not args.database.startswith('lo_setup_check_'):
        parser.error('Use lo_teammate_preview or a disposable lo_setup_check_* database')
    migrations = args.backend / 'supabase/migrations'
    numbered = sorted(migrations.glob('[0-9]*.sql'))
    if not numbered or numbered[0].name != '20260422000001_init_auth.sql':
        parser.error('Expected the sibling LoAppBackend migration history')
    seed = migrations / '20260523000002_onboarding_seed.sql'
    seed_prefix, marker, _ = seed.read_text().partition('WITH city_ids AS (')
    if not marker:
        parser.error('Seed format changed: review bootstrap before continuing')
    with psycopg.connect(host='127.0.0.1', port=args.port, user=args.user,
                         dbname=args.database, connect_timeout=5, autocommit=True) as db:
        if db.execute("SELECT count(*) FROM pg_tables WHERE schemaname='public'").fetchone()[0]:
            parser.error('Database is not empty; refusing to alter an existing preview')
        # These NOLOGIN roles satisfy legacy GRANTs on a dedicated local cluster.
        for role in ('postgres', 'service_role'):
            if not db.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (role,)).fetchone():
                db.execute(sql.SQL('CREATE ROLE {} NOLOGIN').format(sql.Identifier(role)))
        ordered = [numbered[0], migrations / 'create_user_profile_table.sql',
                   migrations / 'create_users_follow_table.sql', *numbered[1:]]
        for path in ordered:
            statement = seed_prefix + '\nCOMMIT;\n' if path == seed else path.read_text()
            db.execute(statement)
            print('Applied', path.name)
        db.execute('UPDATE public.cities SET cover_image_url=NULL')
        cities = db.execute('SELECT slug FROM public.cities ORDER BY slug').fetchall()
        places = db.execute('SELECT count(*) FROM public.places').fetchone()[0]
        if cities != [('danang',), ('hanoi',), ('hcmc',)] or places != 0:
            raise RuntimeError('Unexpected seed contents; inspect this local database')
        print('Ready: 3 cities, 0 demo places. Collect fresh website records next.')


if __name__ == '__main__':
    main()
