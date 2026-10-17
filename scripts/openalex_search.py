"""Search OpenAlex and write one JSON record per work.

Modes (pick one):
  --semantic TEXT   meaning-based search, at most 50 results, not reproducible
  --exact QUERY     boolean query on title and abstract, unstemmed (use rout* for routing/routes), all pages
  --cites ID        works that cite ID (DOI, arXiv id or OpenAlex W id)
  --refs ID         works that ID references

Run anywhere inside a project (the key comes from the environment, the project .env or
~/.config/paper-lector/.env; literature.json, when present, marks works already in the sources table):
  python openalex_search.py --exact '(entanglement) AND (switch OR repeater) AND (age OR cutoff)'
Without --out the records go to runs/<date>_<time>_<name>_<mode>.jsonl next to literature.json (else in the current
folder), for example runs/2026-10-18_1420_entanglement-scheduling_exact.jsonl, with -2 added when that minute is taken.
<name> is --name, the same short name the queries file will carry; without --name the file is <date>_<time>_<mode>.jsonl.
"""
import argparse, datetime, json, re, sys, urllib.error, urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

API = 'https://api.openalex.org'
KEY = None
FIELDS = 'id,doi,display_name,publication_year,primary_location,best_oa_location,locations,authorships,abstract_inverted_index,type,biblio,cited_by_count,citation_normalized_percentile'


def get(path, params):
    try:
        return common.openalex_json(f'{API}/{path}?{urllib.parse.urlencode(params)}', KEY, timeout=120)
    except urllib.error.HTTPError as e:
        if msg := common.openalex_error(e, KEY):
            sys.exit(msg)
        raise


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
MAX_DEPTH = 10


def query_issues(q):
    """What OpenAlex would get wrong without saying so, or refuse. It reads OR wrongly when OR shares a level with
    AND, NOT or plain adjacency: live 2026-10-17, '"quantum switch" scheduling OR "operations research"' returned
    the 500 works of the phrase alone, the bracketed '"quantum switch" AND (scheduling OR "operations research")' 20.
    A bracketed group next to a term with no operator is read as AND (live 2026-10-18, both orders gave 20), so it
    passes. Lower-case and/or/not are searched as words ('"quantum switch" or "quantum network"' gave 10), and
    NOT NOT gets HTTP 500. A quoted phrase with * inside a boolean query gets HTTP 400. Many operators slow the search."""
    if not q.strip():
        return ['empty query']
    q = re.sub('[\u201c\u201d\u201e\u00ab\u00bb]', '"', q)   # OpenAlex reads curly quotes as quotes (live 2026-10-18)
    if q.count('"') % 2:
        return ['unbalanced quotes']
    tokens = re.findall(r'"[^"]*"|\(|\)|[^\s()"]+', q)
    depth = deepest = 0
    for t in tokens:
        depth += (t == '(') - (t == ')')
        deepest = max(deepest, depth)
    if deepest > MAX_DEPTH:
        return [f'brackets nested {deepest} deep; at most {MAX_DEPTH}']
    issues = ['empty quotes'] if any(t.startswith('"') and not t.strip('" ') for t in tokens) else []
    if lower := sorted({t for t in tokens if t in ('and', 'or', 'not')}):
        issues.append(f'{", ".join(lower)} in lower case is searched as a word; write AND, OR, NOT')

    def group(i):
        """Check operands and operators up to the matching ')'; return the index there."""
        n_items, joins, expect_operand = 0, [], True
        while i < len(tokens) and tokens[i] != ')':
            t = tokens[i]
            if t in ('AND', 'OR', 'NOT'):
                if expect_operand and not (t == 'NOT' and n_items and joins[-1:] != ['NOT']):
                    issues.append('NOT NOT (OpenAlex answers 500)' if joins[-1:] == ['NOT'] and t == 'NOT'
                                  else f'{t} has no term before it')
                joins.append(t)
                expect_operand, i = True, i + 1
                continue
            if not expect_operand:                # two operands side by side: OpenAlex reads AND
                joins.append('')
            if t == '(':
                i = group(i + 1)
                if i >= len(tokens):
                    issues.append('unbalanced parentheses')
                    return i
            i += 1
            n_items, expect_operand = n_items + 1, False
        if not n_items:
            issues.append('empty group' if i < len(tokens) else 'empty query')
        elif expect_operand:
            issues.append(f'{joins[-1]} has no term after it')
        if 'OR' in joins and any(j != 'OR' for j in joins):
            issues.append('OR is mixed with AND, NOT or adjacency at one level; put each OR list in its own parentheses')
        return i

    i = group(0)
    if i < len(tokens):
        issues.append('unbalanced parentheses')
    operands = [t for t in tokens if t not in ('AND', 'OR', 'NOT', '(', ')')]
    if len(operands) > 1:
        issues += [f'{t}: no * or ? inside quotes in a boolean query (OpenAlex answers 400); list the forms'
                   for t in operands if t.startswith('"') and re.search(r'[*?]', t)]
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
        # citations change over time: keep the count, its percentile among works of the same field and year, and the date
        'cited_by': w.get('cited_by_count'),
        'cited_pct': round(100 * pct, 1) if (pct := (w.get('citation_normalized_percentile') or {}).get('value')) is not None else None,
        'cited_at': datetime.date.today().isoformat(),
        'oa_pdf': (w.get('best_oa_location') or {}).get('pdf_url'),
        'relevance': w.get('relevance_score'),
        'in_sources': held.get(doi),  # key in the sources table, if any
        'abstract': ' '.join(k for _, k in words),
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    m = ap.add_mutually_exclusive_group(required=True)
    m.add_argument('--semantic'); m.add_argument('--exact'); m.add_argument('--cites'); m.add_argument('--refs')
    ap.add_argument('--out', help='JSONL file (default: runs/<date>_<time>_<name>_<mode>.jsonl next to the config)')
    ap.add_argument('--name', help='topic name for the default file name, as in the queries file (e.g. entanglement-scheduling)')
    ap.add_argument('--config', help='path to literature.json (default: searched upward)')
    ap.add_argument('--max', type=int, default=0, help='stop after this many records (0 = all)')
    a = ap.parse_args(argv)
    if a.name is not None and not common.valid_name(a.name):
        sys.exit(f'--name must be lowercase letters, digits and single hyphens, at most {common.NAME_MAX} characters')
    mode = next(k for k in ('exact', 'semantic', 'cites', 'refs') if getattr(a, k) is not None)
    if not getattr(a, mode).strip():
        sys.exit(f'--{mode} is empty')
    if a.exact and (issues := query_issues(a.exact)):
        sys.exit('query not sent: ' + '; '.join(issues))
    if a.out and not a.out.endswith('.jsonl'):
        sys.exit(f'{a.out}: --out must be a .jsonl file')
    global KEY
    cfg = common.load_config(a.config, required=False)
    KEY = common.api_key('OPENALEX_API_KEY', cfg, required=False)
    if not a.out:
        base = (cfg['root'] if cfg else Path.cwd()) / 'runs' / datetime.datetime.now().strftime('%Y-%m-%d_%H%M')
        tail = f'_{a.name}_{mode}.jsonl' if a.name else f'_{mode}.jsonl'
        a.out, n = f'{base}{tail}', 2
        while not reserve(a.out):                   # same name and mode in the same minute, or another run
            a.out, n = f'{base}-{n}{tail}', n + 1
    elif not reserve(a.out):
        sys.exit(f'{a.out}: --out must be a new file (it and its .query.json are never overwritten)')
    try:
        search(a, cfg, mode)
    except BaseException:
        for f in (Path(a.out), Path(a.out).with_suffix('.query.json')):   # both reserved by this run
            f.unlink(missing_ok=True)
        raise


def reserve(out):
    """Create out and its .query.json, both or neither, so no other run can write them; False if either exists."""
    side = Path(out).with_suffix('.query.json')
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    try:
        open(out, 'x').close()
    except FileExistsError:
        return False
    try:
        open(side, 'x').close()
    except FileExistsError:
        Path(out).unlink()
        return False
    return True


def search(a, cfg, mode):

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
    with open(a.out, 'w', encoding='utf-8') as f:
        for w in works:
            f.write(json.dumps(record(w, held), ensure_ascii=False) + '\n')
    n_held = sum(1 for w in works if held.get((w.get('doi') or '').removeprefix('https://doi.org/').lower()))
    if a.refs:
        print(f'references: listed {meta["count"]}, written {len(works)}', file=sys.stderr)
    print(f"count {meta.get('count')}  written {len(works)}  already in sources.csv {n_held}  -> {a.out}", file=sys.stderr)
    # without a key only page 1 of a keyword or citing search comes back
    cut = not KEY and mode in ('exact', 'cites') and (meta.get('count') or 0) > len(works) and (not a.max or a.max > len(works))
    Path(a.out).with_suffix('.query.json').write_text(json.dumps({
        'mode': mode, 'query': getattr(a, mode), 'date': datetime.datetime.now().isoformat(timespec='seconds'),
        'count': meta.get('count'), 'written': len(works), 'already_in_sources': n_held, 'max': a.max or None,
        'keyless': not KEY, 'keyless_first_page_only': cut, 'name': a.name, 'out': Path(a.out).name},
        ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    if cut:
        print(f'no OPENALEX_API_KEY: only the first {len(works)} of {meta["count"]} were written; a free key gets them all',
              file=sys.stderr)


if __name__ == '__main__':
    main()
