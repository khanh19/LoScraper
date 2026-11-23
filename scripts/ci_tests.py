"""Offline CI suite; fail on unexpected skips instead of hiding missing setup."""
import argparse
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--postgres', action='store_true')
args = parser.parse_args()
suite = unittest.TestSuite()
for path in sorted((ROOT / 'tests').glob('test_*.py')):
    if not args.postgres and path.name in {'test_postgres.py', 'test_zz_engine_postgres.py'}:
        continue
    suite.addTests(unittest.defaultTestLoader.discover(str(ROOT / 'tests'), pattern=path.name))
result = unittest.TextTestRunner(verbosity=2).run(suite)
if not result.testsRun or result.skipped:
    print('CI requires nonempty tests and zero unexpected skips.', file=sys.stderr)
sys.exit(0 if result.wasSuccessful() and result.testsRun and not result.skipped else 1)
