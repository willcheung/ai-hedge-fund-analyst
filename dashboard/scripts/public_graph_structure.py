"""Bounded public graph identities. Never infer edges from labels or order."""
import re

SOURCE_IDS = (
    'news_calendar', 'x_signals', 'transcripts', 'sec_insiders', 'macro_breadth',
    'ai_projection_exhibits', 'upcoming_earnings', 'preview', 'post_print_trigger',
    'press_release_8k', 'financials', 'guidance', 'call_transcript', 'price_volume',
    'peer_readthrough', 'post_print_projection_update',
)
KINDS = {**dict.fromkeys(SOURCE_IDS, 'source'), 'checker': 'checker',
         'synthesis': 'synthesis', 'public_snapshot': 'publish',
         'runtime_manifest': 'transport', 'workflow_ops': 'consumer'}
PUBLIC_IDS = {raw: raw.replace('_', '-') for raw in KINDS}
IDENTITIES = {key: (PUBLIC_IDS[raw], KINDS[raw]) for raw in KINDS for key in (raw, PUBLIC_IDS[raw])}
IDENTITY_PATH = re.compile(r'\$\.marketGraphs\[\d+\]\.(?:graphNodes\[\d+\]\.id|graphEdges\[\d+\]\.(?:from|to))')


def sanitize_graph_identity(value, pointer):
    """None means not an identity field; empty string means rejected identity."""
    if not IDENTITY_PATH.fullmatch(pointer):
        return None
    return value if isinstance(value, str) and value in PUBLIC_IDS.values() else ''


def _explicitly_public(value):
    tags = [value[k] for k in ('privacy_class', 'privacyClass') if k in value]
    return bool(tags) and all(tag in ('public', 'public_ok') for tag in tags)


def project_graph_structure(graph):
    """Return projected nodes/edges; any ambiguous topology fails closed.

    Call before generic sanitization, with original privacy classifications.
    Private nodes and their incident edges are omitted. Unknown public nodes,
    duplicate/blank identities, unknown/dangling endpoints, and duplicate edges
    invalidate the topology rather than guessing a replacement identity.
    """
    empty = {'graphNodes': [], 'graphEdges': []}
    if not _explicitly_public(graph):
        return empty
    nodes, edges = graph.get('graphNodes'), graph.get('graphEdges')
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return empty
    identities, retained, projected = set(), {}, []
    for node in nodes:
        if not isinstance(node, dict):
            return empty
        raw = node.get('id')
        if not isinstance(raw, str) or not raw or raw in identities:
            return empty
        identities.add(raw)
        if not _explicitly_public(node):
            continue
        identity = IDENTITIES.get(raw)
        if identity is None or node.get('kind') != identity[1] or identity[0] in retained.values():
            return empty
        retained[raw] = identity[0]
        projected.append({**node, 'id': identity[0]})
    projected_edges, pairs = [], set()
    for edge in edges:
        if not isinstance(edge, dict):
            return empty
        a, b = edge.get('from'), edge.get('to')
        if not isinstance(a, str) or not isinstance(b, str) or a not in identities or b not in identities or (a, b) in pairs or a == b:
            return empty
        pairs.add((a, b))
        if a not in retained or b not in retained:
            continue
        projected_edges.append({'from': retained[a], 'to': retained[b], 'status': edge.get('status', 'unknown')})
    return {'graphNodes': projected, 'graphEdges': projected_edges}
