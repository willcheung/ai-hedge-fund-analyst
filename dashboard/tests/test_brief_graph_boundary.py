# SYNTHETIC regression inputs only; all companies, values and histories are fictional.
import sys
import unittest
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from public_content import adapt_legacy, sanitize_legacy
from public_snapshot import build_public_snapshot
from public_graph_structure import project_graph_structure


class BriefGraphBoundaryTests(unittest.TestCase):
    def test_sourced_title_is_allowed_only_in_timeline_title_field(self):
        title = '$AAA — Company research update'
        raw = {'jobName': title, 'other': {'jobName': title}, 'cronTimeline': [{'id': 'market_brief_friday_take_2026-09-04', 'jobName': title, 'summary': 'Demand improved.'}]}
        clean = sanitize_legacy(raw)
        self.assertNotIn('jobName', clean)
        self.assertNotIn('jobName', clean['other'])
        self.assertEqual(clean['cronTimeline'][0]['jobName'], title)
        self.assertEqual(clean['cronTimeline'][0]['id'], 'market_brief_friday_take_2026-09-04')

    def test_generic_retained_title_can_gain_same_run_context_without_retiming_or_body_changes(self):
        old = {'schemaVersion': 1, 'id': 'brief:job:run', 'jobId': 'job', 'type': 'brief', 'title': 'Research update', 'summary': 'Revenue grew 20%.', 'publishedAt': None, 'publishedDate': '2026-09-06', 'informationAt': None, 'tickers': [], 'sources': [], 'sections': [{'heading': 'Research', 'markdown': 'Revenue grew 20%.', 'sourceIds': []}]}
        row = {'id': 'run', 'jobId': 'job', 'jobName': '$AAA — Company research update', 'runTime': '2026-09-06 12:00:00', 'summary': 'Revenue grew 20%.', 'highlights': ['Appended log entry: log.md']}
        clean = adapt_legacy({'cronTimeline': [row]}, previous=[old])[0]
        self.assertEqual(clean['title'], row['jobName'])
        self.assertEqual(clean['tickers'], ['AAA'])
        self.assertEqual({k:v for k,v in clean.items() if k not in ('title','tickers')}, {k:v for k,v in old.items() if k not in ('title','tickers')})
        newer = adapt_legacy({'cronTimeline': [{**row, 'runTime': '2026-09-07 12:00:00'}]}, previous=[old])[0]
        self.assertEqual(newer, old)
        private = adapt_legacy({'cronTimeline': [{**row, 'privacy_class': 'private_local_only'}]}, previous=[old])[0]
        self.assertEqual(private, old)

    def test_full_snapshot_preserves_matching_public_graph_identities_and_removes_private_edges(self):
        graph = {'privacy_class': 'public_ok', 'label': 'Market research checks', 'generatedAt': '2026-09-06T12:00:00Z', 'finalGate': 'pass', 'graphNodes': [
            {'id':'news_calendar','kind':'source','privacy_class':'public_ok','label':'News Calendar','status':'pass'},
            {'id':'checker','kind':'checker','privacy_class':'public_ok','label':'Checker gate','status':'pass'},
            {'id':'hidden-account','kind':'source','privacy_class':'private_local_only','label':'Private source'},
        ], 'graphEdges':[{'from':'news_calendar','to':'checker','status':'pass'},{'from':'hidden-account','to':'checker','status':'pass'}]}
        with tempfile.TemporaryDirectory() as directory:
            snapshot = build_public_snapshot({'marketGraphs':[graph]}, data_as_of='2026-09-06T12:00:00Z', cron_root=Path(directory))
        result = snapshot['marketGraphs'][0]
        self.assertEqual([n['id'] for n in result['graphNodes']], ['news-calendar','checker'])
        self.assertEqual(result['graphEdges'], [{'from':'news-calendar','to':'checker','status':'pass'}])
        self.assertEqual(sanitize_legacy(snapshot)['marketGraphs'][0]['graphEdges'], result['graphEdges'])
        self.assertNotIn('hidden-account', str(snapshot))

    def test_alias_collision_and_conflicting_privacy_tags_fail_closed(self):
        graph={'privacy_class':'public_ok','graphNodes':[{'id':'news_calendar','kind':'source','privacy_class':'public_ok'},{'id':'news-calendar','kind':'source','privacy_class':'public_ok'}],'graphEdges':[]}
        self.assertEqual(project_graph_structure(graph), {'graphNodes':[],'graphEdges':[]})
        self.assertEqual(project_graph_structure({**graph,'privacyClass':'private'}), {'graphNodes':[],'graphEdges':[]})

if __name__ == '__main__': unittest.main()
