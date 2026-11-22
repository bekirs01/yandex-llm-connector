import json
from pathlib import Path

from tools.question_tree_viewer import build_graph, render_html

SOURCE = Path(__file__).resolve().parents[1] / 'docs/auto-question-tree'


def test_real_graph_resolves_edges_and_preserves_services():
    graph = build_graph(SOURCE)
    ids = {node['id'] for node in graph['nodes']}
    assert {'root', 'mechanical.scope', 'equipment.climate', 'entry_rules'} <= ids
    assert all(edge['source'] in ids and edge['target'] in ids for edge in graph['edges'])
    assert len(graph['services']) == 394
    assert any(edge['source'] == 'root' and edge['target'] == 'entry_rules' for edge in graph['edges'])
    assert any(edge['source'] == 'entry_rules.complaint' and edge['target'] == 'equipment.climate' for edge in graph['edges'])


def test_html_embeds_data_without_script_injection():
    graph = {'nodes': [], 'edges': [], 'services': [{'id': '</script><script>alert(1)</script>'}]}
    html = render_html(graph)
    payload = html.split('<script id="tree-data" type="application/json">')[1].split('</script>')[0]
    assert json.loads(payload) == graph
    assert '</script>' not in payload


def test_analysis_distinguishes_depth_longest_path_cycles_and_unreachable():
    from tools.question_tree_viewer import analyze_graph
    graph = {'nodes': [{'id': n, 'kind': k} for n, k in [
        ('root', 'question'), ('a', 'question'), ('b', 'rule'),
        ('leaf', 'result'), ('detached', 'question')]], 'edges': [
        {'source': s, 'target': t} for s, t in [
            ('root', 'a'), ('a', 'b'), ('b', 'a'), ('root', 'leaf'), ('b', 'leaf')]]}
    analysis = analyze_graph(graph)
    assert analysis['levels'] == {'root': 0, 'a': 1, 'leaf': 1, 'b': 2}
    assert analysis['unreachable'] == ['detached']
    assert analysis['leaves'] == ['leaf']
    assert analysis['longest_path'] == ['root', 'a', 'b', 'leaf']
    assert analysis['max_questions'] == 2
    assert analysis['has_cycles'] is True


def test_mechanical_area_routes_are_not_lost():
    graph = build_graph(SOURCE)
    assert any(edge['source'] == 'mechanical.entry_rules' and
               edge['target'] == 'mechanical.result.clutch' for edge in graph['edges'])
