# SYNTHETIC regression inputs only; all companies, values and histories are fictional.
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from public_graph_structure import project_graph_structure, sanitize_graph_identity


def graph():
    return {'privacy_class': 'public_ok', 'graphNodes': [
        {'id': 'news_calendar', 'kind': 'source', 'privacy_class': 'public_ok', 'status': 'degraded'},
        {'id': 'checker', 'kind': 'checker', 'privacy_class': 'public_ok'},
    ], 'graphEdges': [{'from': 'news_calendar', 'to': 'checker', 'status': 'degraded'}]}


class PublicGraphStructureTests(unittest.TestCase):
    def test_exact_matching_not_source_order(self):
        g = graph()
        g['graphNodes'].reverse()
        p = project_graph_structure(g)
        self.assertEqual(p['graphEdges'], [{'from': 'news-calendar', 'to': 'checker', 'status': 'degraded'}])
        self.assertEqual(p['graphNodes'][1]['status'], 'degraded')
        self.assertEqual(g['graphNodes'][1]['id'], 'news_calendar')

    def test_explicit_public_classification_required(self):
        for privacy in [None, '', 'private', 'unknown']:
            g = graph()
            g['graphNodes'][0]['privacy_class'] = privacy
            p = project_graph_structure(g)
            self.assertEqual(len(p['graphNodes']), 1)
            self.assertEqual(p['graphEdges'], [])
        g = graph(); del g['privacy_class']
        self.assertEqual(project_graph_structure(g), {'graphNodes': [], 'graphEdges': []})

    def test_no_private_ids_or_incident_edges(self):
        g = graph()
        g['graphNodes'].append({'id': '/root/private/source', 'kind': 'source', 'privacy_class': 'private'})
        g['graphEdges'].append({'from': '/root/private/source', 'to': 'checker'})
        self.assertNotIn('/root', str(project_graph_structure(g)))
        self.assertEqual(len(project_graph_structure(g)['graphEdges']), 1)

    def test_ambiguous_or_unknown_topology_fails_closed(self):
        cases = []
        for raw in ['', 'unknown', '/root/private/source']:
            g = graph(); g['graphNodes'][0]['id'] = raw; cases.append(g)
        g = graph(); g['graphNodes'].append(copy.deepcopy(g['graphNodes'][0])); cases.append(g)
        g = graph(); g['graphEdges'][0]['to'] = 'missing'; cases.append(g)
        g = graph(); g['graphEdges'].append(copy.deepcopy(g['graphEdges'][0])); cases.append(g)
        g = graph(); g['graphNodes'][0]['kind'] = 'consumer'; cases.append(g)
        for g in cases:
            self.assertEqual(project_graph_structure(g), {'graphNodes': [], 'graphEdges': []})

    def test_identity_exception_is_exact_path_and_bounded(self):
        for pointer in ['$.marketGraphs[0].graphNodes[0].id', '$.marketGraphs[1].graphEdges[2].from', '$.marketGraphs[1].graphEdges[2].to']:
            self.assertEqual(sanitize_graph_identity('news-calendar', pointer), 'news-calendar')
            self.assertEqual(sanitize_graph_identity('news_calendar', pointer), '')
            self.assertEqual(sanitize_graph_identity('/root/private', pointer), '')
        for pointer in ['$.tickers[0].id', '$.marketGraphs[0].runId', '$.marketGraphs[0].graphNodes[0].reason']:
            self.assertIsNone(sanitize_graph_identity('news-calendar', pointer))


if __name__ == '__main__':
    unittest.main()
