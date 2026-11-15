import unittest
from datetime import datetime, timezone, timedelta
from trending.engagement import in_review_window
from trending.engagement import assess, metrics, priority, instagram_record


class EngagementTests(unittest.TestCase):
    def test_review_window_excludes_old_pinned_and_future_posts(self):
        now = datetime(2026,11,15,tzinfo=timezone.utc)
        for days, expected in [(0,True),(35,True),(36,False),(-1,False)]:
            self.assertEqual(in_review_window({'timestamp':(now-timedelta(days=days)).isoformat()},now),expected)
        self.assertFalse(in_review_window({},now))
    def test_instagram_sample_preserves_counts_without_profile_data(self):
        row = instagram_record({'url':'https://www.instagram.com/p/ABC123/',
            'likesCount':-1, 'commentsCount':465, 'videoPlayCount':1361553,
            'latestComments':[{'text':'Mua vé ở đâu?', 'ownerUsername':'private_detail',
                               'timestamp':'2026-11-15T00:00:00Z'}]}, '2026-11-15T01:00:00Z')
        self.assertIsNone(row['digg_count'])
        self.assertEqual(row['comment_count'],465)
        self.assertEqual(len(row['comment_samples']),1)
        self.assertNotIn('ownerUsername',row['comment_samples'][0])
        self.assertEqual(row['play_count'],1361553)

    def test_hidden_and_invalid_are_unknown(self):
        self.assertIsNone(metrics({'likesCount': -1})['likes'])
        self.assertIsNone(metrics({'likesCount': True})['likes'])
        self.assertIsNone(metrics({'likesCount': float('nan')})['likes'])
        self.assertEqual(metrics({'likesCount': 0})['likes'], 0)

    def test_counts_never_grant_virality_or_publication(self):
        r = assess({'likesCount': 46000, 'videoPlayCount': 513200})
        self.assertTrue(r['popularity_candidate'])
        self.assertEqual(r['viral_status'], 'unverified')
        self.assertFalse(r['publishable'])

    def test_reach_not_double_counted(self):
        self.assertFalse(assess({'videoPlayCount': 30000, 'videoViewCount': 30000})['popularity_candidate'])

    def test_platform_fields_and_ranking(self):
        self.assertEqual(metrics({'diggCount': 42})['likes'], 42)
        self.assertLess(priority({'likesCount': 1001}), priority({'likesCount': 17}))
        self.assertFalse(assess({'timestamp': '2026-11-15'})['popularity_candidate'])
