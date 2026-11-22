"""Build an offline React Flow + Dagre viewer of the question-tree specification.

Build UI: npm --prefix tools/question-tree-ui ci
          npm --prefix tools/question-tree-ui run build
Generate: python -m tools.question_tree_viewer --output /tmp/auto-question-tree.html
"""
import argparse
from collections import deque
import json
from pathlib import Path

DEFAULT_SOURCE = Path(__file__).resolve().parents[1] / 'docs/auto-question-tree'


def build_graph(source: Path) -> dict:
    documents = {name: json.loads((source / f'{name}.json').read_text())
                 for name in ('tree', 'mechanical', 'equipment', 'catalog')}
    nodes, edges = {}, []
    service_titles = {entry['id']: entry['source_title'] for entry in documents['catalog']['results']}

    def add_node(identifier, kind, data):
        if identifier in nodes:
            raise ValueError(f'Duplicate node: {identifier}')
        nodes[identifier] = {'id': identifier, 'kind': kind, 'data': data,
                              'title': data.get('text') or ' / '.join(data.get('source_titles', []))
                              or ' / '.join(data.get('service_titles', []))
                              or ' / '.join(service_titles[sid] for sid in data.get('service_ids', []) if sid in service_titles)
                              or ('Выбранная услуга или диагностика' if identifier == 'result' else identifier)}

    def link(origin, target, label):
        if isinstance(target, list):
            for item in target:
                link(origin, item, label)
        elif isinstance(target, str):
            target = target.removeprefix('parent.')
            edges.append({'source': origin, 'target': target, 'label': label})
        else:
            raise ValueError(f'Unsupported transition at {origin}: {target!r}')

    for name in ('tree', 'mechanical', 'equipment'):
        doc = documents[name]
        for node in doc['nodes']:
            add_node(node['id'], 'question', node)
            options = {o['value']: o.get('label', o.get('text', o['value']))
                       for o in node.get('options', []) if isinstance(o, dict)}
            for answer, target in node.get('transitions', {}).items():
                link(node['id'], target, options.get(answer, answer))
            unknown = node.get('unknown')
            if isinstance(unknown, dict):
                unknown = unknown.get('result')
            if unknown:
                link(node['id'], unknown, 'Не знаю')
        for result in doc.get('results', []):
            add_node(result['id'], 'result', result)
    for identifier, data in documents['tree']['terminal_templates'].items():
        add_node(identifier, 'result', data)
    for identifier, title in [('entry_rules', 'Входные правила'),
                              ('entry_rules.complaint', 'Маршрутизация жалобы'),
                              ('entry_rules_each', 'Обработка каждой задачи'),
                              ('mechanical.entry_rules', 'Механика: входные правила')]:
        rules = documents['mechanical' if identifier.startswith('mechanical') else 'tree']['entry_rules']
        add_node(identifier, 'rule', {'text': title, 'rules': rules})
    for origin in ('entry_rules', 'entry_rules.complaint', 'entry_rules_each'):
        for rule in documents['tree']['dispatch']:
            link(origin, rule['target'], rule['observed'])
    for rule in documents['mechanical']['entry_rules']:
        if 'target' in rule:
            link('mechanical.entry_rules', rule['target'], rule['observed'])
        for area, target in rule.get('target_by_area', {}).items():
            link('mechanical.entry_rules', target, f"{rule['observed']} ({area})")
    # Global entry rules are prose, so expose explicit references without inferring routes.
    for edge in edges:
        if edge['target'] not in nodes:
            add_node(edge['target'], 'reference', {'text': edge['target'],
                     'note': 'Ссылка спецификации: см. исходные правила; автоматический переход не определён.'})
    graph = {'nodes': list(nodes.values()), 'edges': edges,
            'services': documents['catalog']['results'], 'specification': documents['tree'],
            'profiles': documents['catalog']['profiles']}
    graph['analysis'] = analyze_graph(graph)
    return graph


def analyze_graph(graph: dict) -> dict:
    """Measure explicit edges; a simple path never revisits a node."""
    nodes = {node['id']: node for node in graph['nodes']}
    if 'root' not in nodes:
        raise ValueError('Graph must contain root')
    outgoing = {identifier: [] for identifier in nodes}
    for edge in graph['edges']:
        if edge['target'] not in outgoing[edge['source']]:
            outgoing[edge['source']].append(edge['target'])
    levels, parents = {'root': 0}, {}
    queue = deque(['root'])
    while queue:
        origin = queue.popleft()
        for target in outgoing[origin]:
            if target not in levels:
                levels[target] = levels[origin] + 1
                parents[target] = origin
                queue.append(target)
    leaves = [identifier for identifier in levels if not outgoing[identifier]]
    longest, max_questions, has_cycles, visits = [], 0, False, 0

    def walk(identifier, path, active, questions):
        nonlocal longest, max_questions, has_cycles, visits
        visits += 1
        if visits > 1_000_000:
            raise ValueError('Too many simple paths to measure exactly')
        path = path + [identifier]
        active = active | {identifier}
        questions += nodes[identifier]['kind'] == 'question'
        if not outgoing[identifier]:
            if len(path) > len(longest):
                longest = path
            max_questions = max(max_questions, questions)
        for target in outgoing[identifier]:
            if target in active:
                has_cycles = True
            else:
                walk(target, path, active, questions)

    walk('root', [], set(), 0)
    return {'root': 'root', 'levels': levels, 'parents': parents,
            'leaves': leaves, 'longest_path': longest,
            'max_questions': max_questions, 'has_cycles': has_cycles,
            'unreachable': [identifier for identifier in nodes if identifier not in levels]}


def render_html(graph: dict) -> str:
    payload = json.dumps(graph, ensure_ascii=False).replace('<', '\\u003c')
    template = Path(__file__).with_name('question_tree_viewer.html').read_text()
    bundle = Path(__file__).with_name('question-tree-ui') / 'dist'
    if not (bundle / 'viewer.js').exists() or not (bundle / 'viewer.css').exists():
        raise FileNotFoundError('Build viewer first: npm --prefix tools/question-tree-ui ci && npm --prefix tools/question-tree-ui run build')
    script = (bundle / 'viewer.js').read_text().replace('</script', '<\\/script')
    stylesheet = (bundle / 'viewer.css').read_text()
    return (template.replace('__VIEWER_CSS__', stylesheet)
            .replace('__VIEWER_JS__', script).replace('__TREE_DATA__', payload))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=DEFAULT_SOURCE)
    parser.add_argument('--output', type=Path, default=Path('/tmp/auto-question-tree.html'))
    args = parser.parse_args()
    args.output.write_text(render_html(build_graph(args.source)), encoding='utf-8')
    print(args.output.resolve())


if __name__ == '__main__':
    main()
