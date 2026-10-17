"""Search OpenAlex and write one JSON record per work.

Modes (pick one):
  --semantic TEXT   meaning-based search, at most 50 results, not reproducible
  --exact QUERY     boolean query on title and abstract, all pages, reproducible
  --cites ID        works that cite ID (DOI, arXiv id or OpenAlex W id)
  --refs ID         works that ID references

Run anywhere inside a project (the key comes from the environment, the project .env or
~/.config/paper-lector/.env; literature.json, when present, marks works already in the sources table):
  python openalex_search.py --exact '(entanglement) AND (switch OR repeater) AND (age OR cutoff)' --out runs/x17.jsonl
"""
import argparse, json, sys, urllib.error, urllib.parse, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

API = 'https://api.openalex.org'
KEY = None
FIELDS = 'id,doi,display_name,publication_year,primary_location,best_oa_location,locations,authorships,abstract_inverted_index,type'


def get(path, params):
    req = urllib.request.Request(f'{API}/{path}?{urllib.parse.urlencode(params)}',
                                 headers={'Authorization': 'Bearer ' + KEY})
    return common.open_json(req, timeout=120)


def work_id(x):
    x = x.strip()
    if x.startswith('W') or 'openalex.org/' in x:
        return x.split('/')[-1]
    if not x.startswith('10.'):  # bare arXiv id
        x = '10.48550/arXiv.' + x.removeprefix('arXiv:')
    try:
        return get('works/doi:' + urllib.parse.quote(x), {'select': 'id'})['id'].split('/')[-1]
    except urllib.error.HTTPError as e:
        sys.exit(f'{x}: not found in OpenAlex ({e.code})')


def held_dois(cfg):
    return {v['doi']: k for k, v in common.sources(cfg).items() if v['doi']}


def record(w, held):
    inv = w.get('abstract_inverted_index') or {}
    words = sorted((p, k) for k, ps in inv.items() for p in ps)
    doi = (w.get('doi') or '').removeprefix('https://doi.org/')
    src = ((w.get('primary_location') or {}).get('source') or {}).get('display_name')
    arxiv = next((l['landing_page_url'].split('/abs/')[-1] for l in w.get('locations') or []
                  if 'arxiv.org/abs/' in (l.get('landing_page_url') or '')), None)
    return {
        'openalex': w['id'].split('/')[-1], 'doi': doi, 'arxiv': arxiv,
        'title': w.get('display_name'), 'year': w.get('publication_year'), 'venue': src,
        'first_author': next((a['author']['display_name'] for a in w.get('authorships') or []), None),
        'oa_pdf': (w.get('best_oa_location') or {}).get('pdf_url'),
        'relevance': w.get('relevance_score'),
        'in_sources': held.get(doi.lower()),  # key in the sources table, if any
        'abstract': ' '.join(k for _, k in words),
    }


def main():
    ap = argparse.ArgumentParser()
    m = ap.add_mutually_exclusive_group(required=True)
    m.add_argument('--semantic'); m.add_argument('--exact'); m.add_argument('--cites'); m.add_argument('--refs')
    ap.add_argument('--out', required=True, help='JSONL file')
    ap.add_argument('--config', help='path to literature.json (default: searched upward)')
    ap.add_argument('--max', type=int, default=0, help='stop after this many records (0 = all)')
    a = ap.parse_args()
    global KEY
    cfg = common.load_config(a.config, required=False)
    KEY = common.api_key('OPENALEX_API_KEY', cfg)

    if a.semantic:
        r = get('works', {'search.semantic': a.semantic, 'per_page': 50, 'select': FIELDS + ',relevance_score'})
        works, meta = r['results'], r['meta']
    else:
        if a.refs:
            ids = get('works/' + work_id(a.refs), {'select': 'referenced_works'})['referenced_works']
            if len(ids) > 100:
                print(f'{len(ids)} references; only the first 100 are fetched', file=sys.stderr)
            flt = 'ids.openalex:' + '|'.join(i.split('/')[-1] for i in ids[:100]) if ids else None
        else:
            flt = f'cites:{work_id(a.cites)}' if a.cites else 'title_and_abstract.search:' + a.exact
        works, meta, cur = [], {'count': 0}, '*'
        while flt and cur:
            r = get('works', {'filter': flt, 'per_page': 200, 'cursor': cur, 'select': FIELDS})
            works += r['results']; meta = r['meta']
            cur = meta.get('next_cursor') if r['results'] else None
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
    print(f"count {meta.get('count')}  written {len(works)}  already in sources.csv {n_held}  -> {a.out}", file=sys.stderr)


if __name__ == '__main__':
    main()
