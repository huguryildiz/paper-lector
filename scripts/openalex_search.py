"""Search OpenAlex and write one JSON record per work.

Modes (pick one):
  --semantic TEXT   meaning-based search, at most 50 results, not reproducible
  --exact QUERY     boolean query on title and abstract, unstemmed (use rout* for routing/routes), all pages
  --cites ID        works that cite ID (DOI, arXiv id or OpenAlex W id)
  --refs ID         works that ID references

Run anywhere inside a project (the key comes from the environment, the project .env or
~/.config/paper-lector/.env; literature.json, when present, marks works already in the sources table):
  python openalex_search.py --exact '(entanglement) AND (switch OR repeater) AND (age OR cutoff)'
Without --out the records go to runs/<date>_<time>_<mode>.jsonl next to literature.json (else in the current folder),
for example runs/2026-10-18_1420_exact.jsonl, with -2 added when that minute is taken.
"""
import argparse, datetime, json, re, sys, urllib.error, urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

API = 'https://api.openalex.org'
KEY = None
FIELDS = 'id,doi,display_name,publication_year,primary_location,best_oa_location,locations,authorships,abstract_inverted_index,type,biblio'


def get(path, params):
    return common.openalex_json(f'{API}/{path}?{urllib.parse.urlencode(params)}', KEY, timeout=120)


def work_id(x):
    kind, v = common.norm_id(x)
    if kind == 'openalex':
        return v
    doi = common.doi_of(x)
    try:
        return get('works/doi:' + urllib.parse.quote(doi), {'select': 'id'})['id'].split('/')[-1]
    except urllib.error.HTTPError as e:
        sys.exit(f'{doi}: not found in OpenAlex' if e.code == 404 else f'{doi}: OpenAlex lookup failed (HTTP {e.code})')


def held_dois(cfg):
    return {v['doi']: k for k, v in common.sources(cfg).items() if v['doi']}


MAX_OPERATORS = 5


def query_issues(q):
    """What OpenAlex would get wrong without saying so. It reads OR wrongly when OR shares a level with AND, NOT or
    plain adjacency, or when a group holding OR sits next to a term with no operator: live 2026-10-17,
    '"quantum switch" scheduling OR "operations research"' returned the 500 works of the phrase alone, the bracketed
    '"quantum switch" AND (scheduling OR "operations research")' 20. It also slows searches with many operators."""
    if q.count('"') % 2:
        return ['unbalanced quotes']
    tokens = re.findall(r'"[^"]*"|\(|\)|[^\s()"]+', q)
    issues = [f'{t}: no * or ? inside quotes in a boolean query (OpenAlex answers 400); list the forms'
              for t in tokens if t.startswith('"') and re.search(r'[*?]', t)] if len(tokens) > 1 else []
    levels, prev, closed_or = [set()], None, False
    for t in tokens:
        if t in ('AND', 'OR', 'NOT'):
            levels[-1].add('or' if t == 'OR' else 'and')
            prev, closed_or = 'op', False
            continue
        if prev == 'term' and t != ')':          # two operands side by side: OpenAlex reads AND
            if closed_or:
                issues.append('a group with OR sits next to a term or group with no operator; write AND between them')
            levels[-1].add('and')
        if t == '(':
            levels.append(set())
            prev, closed_or = 'open', False
        elif t == ')':
            if len(levels) == 1:
                return ['unbalanced parentheses']
            closed_or = 'or' in levels.pop()
            prev = 'term'
        else:
            prev, closed_or = 'term', False
        if {'or', 'and'} <= levels[-1]:
            issues.append('OR is mixed with AND, NOT or adjacency at one level; put each OR list in its own parentheses')
    if len(levels) != 1:
        issues.append('unbalanced parentheses')
    if {'or', 'and'} <= levels[0]:
        issues.append('OR is mixed with AND, NOT or adjacency at one level; put each OR list in its own parentheses')
    n = sum(t in ('AND', 'OR', 'NOT') for t in tokens)
    if n > MAX_OPERATORS:
        issues.append(f'{n} AND/OR/NOT operators; at most {MAX_OPERATORS} (6 terms in two blocks)')
    return list(dict.fromkeys(issues))


def record(w, held):
    inv = w.get('abstract_inverted_index') or {}
    words = sorted((p, k) for k, ps in inv.items() for p in ps)
    doi = (w.get('doi') or '').removeprefix('https://doi.org/').lower()
    src = ((w.get('primary_location') or {}).get('source') or {}).get('display_name')
    arxiv = next((l['landing_page_url'].split('/abs/')[-1] for l in w.get('locations') or []
                  if 'arxiv.org/abs/' in (l.get('landing_page_url') or '')), None)
    return {
        'openalex': w['id'].split('/')[-1], 'doi': doi, 'arxiv': arxiv,
        'title': w.get('display_name'), 'year': w.get('publication_year'), 'venue': src,
        'first_author': next((a['author']['display_name'] for a in w.get('authorships') or []), None),
        'authors': [a['author']['display_name'] for a in w.get('authorships') or [] if a.get('author', {}).get('display_name')],
        'biblio': {k: v for k, v in (w.get('biblio') or {}).items() if v},
        'oa_pdf': (w.get('best_oa_location') or {}).get('pdf_url'),
        'relevance': w.get('relevance_score'),
        'in_sources': held.get(doi),  # key in the sources table, if any
        'abstract': ' '.join(k for _, k in words),
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    m = ap.add_mutually_exclusive_group(required=True)
    m.add_argument('--semantic'); m.add_argument('--exact'); m.add_argument('--cites'); m.add_argument('--refs')
    ap.add_argument('--out', help='JSONL file (default: runs/<date>_<time>_<mode>.jsonl next to the config)')
    ap.add_argument('--config', help='path to literature.json (default: searched upward)')
    ap.add_argument('--max', type=int, default=0, help='stop after this many records (0 = all)')
    a = ap.parse_args(argv)
    if a.exact and (issues := query_issues(a.exact)):
        sys.exit('query not sent: ' + '; '.join(issues))
    global KEY
    cfg = common.load_config(a.config, required=False)
    KEY = common.api_key('OPENALEX_API_KEY', cfg, required=False)
    mode = next(k for k in ('exact', 'semantic', 'cites', 'refs') if getattr(a, k))
    if not a.out:
        base = (cfg['root'] if cfg else Path.cwd()) / 'runs' / datetime.datetime.now().strftime('%Y-%m-%d_%H%M')
        a.out, n = f'{base}_{mode}.jsonl', 2
        while Path(a.out).exists():                 # same mode in the same minute
            a.out, n = f'{base}-{n}_{mode}.jsonl', n + 1

    if a.semantic:
        r = get('works', {'search.semantic': a.semantic, 'per_page': 50, 'select': FIELDS + ',relevance_score'})
        works, meta = r['results'], r['meta']
    elif a.refs:
        ids = [i.split('/')[-1] for i in get('works/' + work_id(a.refs), {'select': 'referenced_works'})['referenced_works']]
        works = []
        for k in range(0, len(ids), 100):          # OpenAlex takes at most 100 values in one OR filter
            works += get('works', {'filter': 'ids.openalex:' + '|'.join(ids[k:k + 100]), 'per_page': 100, 'select': FIELDS})['results']
            if a.max and len(works) >= a.max:
                break
        meta = {'count': len(ids)}
    else:
        params = {'filter': f'cites:{work_id(a.cites)}'} if a.cites else {'search.title_and_abstract.exact': a.exact}
        works, meta, cur = [], {'count': 0}, '*'
        while cur:
            r = get('works', dict(params, per_page=200, cursor=cur, select=FIELDS))
            works += r['results']; meta = r['meta']
            cur = meta.get('next_cursor') if r['results'] and KEY else None   # without a key only page 1 works
            if a.max and len(works) >= a.max:
                break
    if a.max:
        works = works[:a.max]

    held = held_dois(cfg)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, 'w', encoding='utf-8') as f:
        for w in works:
            f.write(json.dumps(record(w, held), ensure_ascii=False) + '\n')
    n_held = sum(1 for w in works if held.get((w.get('doi') or '').removeprefix('https://doi.org/').lower()))
    if a.refs:
        print(f'references: listed {meta["count"]}, written {len(works)}', file=sys.stderr)
    print(f"count {meta.get('count')}  written {len(works)}  already in sources.csv {n_held}  -> {a.out}", file=sys.stderr)
    Path(a.out).with_suffix('.query.json').write_text(json.dumps({
        'mode': mode, 'query': getattr(a, mode), 'date': datetime.datetime.now().isoformat(timespec='seconds'),
        'count': meta.get('count'), 'written': len(works), 'already_in_sources': n_held, 'max': a.max or None,
        'keyless': not KEY, 'out': Path(a.out).name}, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    if not KEY and (meta.get('count') or 0) > len(works) and not a.max:
        print(f'no OPENALEX_API_KEY: only the first {len(works)} of {meta["count"]} were written; a free key gets them all',
              file=sys.stderr)


if __name__ == '__main__':
    main()
