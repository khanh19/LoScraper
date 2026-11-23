from contextlib import redirect_stdout
from datetime import datetime, timezone
from io import StringIO
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from trending import pilot, social_collect
from trending.providers import ProviderDisabled
from trending.pilot import validate_manifest

class Manifest(unittest.TestCase):
    def test_budget_and_post_only_inputs(self):
        with self.assertRaisesRegex(ValueError,'budget'):validate_manifest({'queries':['q']*7})
        with self.assertRaisesRegex(ValueError,'platform'):validate_manifest({'posts':[{'url':'https://tiktok.com/discover/cafe'}]})
        with self.assertRaisesRegex(ValueError,'platform'):validate_manifest({'posts':[{'url':f'https://instagram.com/p/{i}'} for i in range(4)]})
        with self.assertRaisesRegex(ValueError,'duplicate'):validate_manifest({'posts':[{'url':'https://instagram.com/p/test'}]*2})


class HistoricalPilot(unittest.TestCase):
    def test_partial_history_cannot_open_the_pilot_even_if_one_reservation_survives(self):
        ledger = Mock()
        ledger.db.execute.return_value.fetchall.return_value = [
            {'provider': 'serpapi', 'platform': None, 'attempts': 6},
            {'provider': 'brightdata', 'platform': 'facebook', 'attempts': 1},
            {'provider': 'brightdata', 'platform': 'instagram', 'attempts': 1},
        ]
        with patch('trending.pilot.Store', return_value=ledger):
            with self.assertRaisesRegex(ProviderDisabled, 'existing_pilot_history_required'):
                pilot.open_pilot_ledger('postgresql://localhost/old-ledger')
        ledger.close.assert_called_once()
        self.assertEqual(ledger.db.execute.call_args.args[1], (pilot.PILOT_ID,))

    def test_empty_history_blocks_all_manual_entrypoints_before_provider_construction(self):
        ledger = Mock()
        ledger.db.execute.return_value.fetchall.return_value = []
        settings = {'DATABASE_URL': 'postgresql://localhost/lo_setup_check_feed',
                    'QUOTA_DATABASE_URL': 'postgresql://localhost/copied_preview'}
        with TemporaryDirectory() as directory:
            manifest = Path(directory) / 'manifest.json'
            manifest.write_text(json.dumps({'queries': ['Hà Nội']}))
            commands = [(pilot, ['pilot', '--manifest', str(manifest)]),
                        (social_collect, ['social_collect', '--city', 'hanoi', '--providers'])]
            with patch.dict(os.environ, settings, clear=True), patch('trending.pilot.Store', return_value=ledger), \
                 patch('trending.pilot.SerpDiscovery') as search, patch('trending.pilot.BrightSocial') as manual_social, \
                 patch('trending.social_collect.BrightSocial') as automatic_social, \
                 patch('trending.social_collect.discover', return_value={'posts': []}):
                for command, argv in commands:
                    with self.subTest(command=command.__name__):
                        output = StringIO()
                        with patch('sys.argv', argv), redirect_stdout(output):
                            self.assertEqual(command.main(), 2)
                        self.assertEqual(json.loads(output.getvalue())['reason'], 'existing_pilot_history_required')

                with patch('trending.social_collect.reviewed_tiktok_profile', return_value={'url': 'https://www.tiktok.com/@example'}):
                    result = social_collect.profile_pilot('hanoi', datetime.now(timezone.utc), True,
                                                         settings['QUOTA_DATABASE_URL'])
                self.assertEqual(result['reason'], 'existing_pilot_history_required')
                search.assert_not_called()
                manual_social.assert_not_called()
                automatic_social.assert_not_called()
        self.assertEqual(ledger.close.call_count, 3)
