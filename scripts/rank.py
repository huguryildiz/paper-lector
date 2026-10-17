"""Rank a PDF collection against frozen research-question slots and give a reading order with starting pages.

Method:
  1. Whole PDF through pdftotext; the bibliography is cut only when its heading is found with confidence;
     appendices stay.
  2. 1,200-token windows with 200-token overlap (Voyage's tokenizer), each labelled with its PDF pages.
  3. Per paper and query, windows are ranked by Reciprocal Rank Fusion (k = 60) of voyage-4-large cosine
     and BM25 on the query's keyword string ("hybrid"), or by cosine alone ("dense"); the top 3 are kept.
  4. rerank-3 scores every paper once per query on its abstract (or first 1,000 tokens) plus the 3 windows.
  5. fused_rank = RRF over the queries listed in "fuse" (default: main and subject). A reading order only.

  Provider "bm25" (literature.json "rank": {"provider": "bm25"}, or --provider bm25) needs no API key: windows are
  chosen by BM25 alone and each paper is scored by BM25 on the same abstract plus 3 windows. Output: <out>_bm25.csv.

  Voyage embeddings are cached in ~/.cache/paper-lector/embeddings.sqlite (key: model, input type, text), so a
  rerun or a run resumed after a crash only pays for new text.

  rank.py --out runs/2026-10-17 --dry     # counts and token estimate, no API call
  rank.py --out runs/2026-10-17           # writes <out>_hybrid.csv and <out>_run.json
"""
import argparse, csv, datetime, hashlib, json, math, re, sqlite3, subprocess, sys, urllib.request
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

EMBED, RERANK = 'voyage-4-large', 'rerank-3'
WIN, STEP, RRF_K, N_WIN, MAX_OVERLAP, HEAD = 1200, 1000, 60, 3, 0.2, 1000
EMBED_BATCH, RERANK_BATCH = 100_000, 500_000
TOK_URL = 'https://huggingface.co/voyageai/voyage-4-large/resolve/main/tokenizer.json'
TOK_PATH = Path.home() / '.cache/paper-lector/voyage-4-large-tokenizer.json'
CACHE = Path.home() / '.cache/paper-lector/embeddings.sqlite'
STOP = set('a an the of for and or in on with to via under by at as is are be been was were this that these those it its '
           'from into over than then which when where while what who how does do can not no'.split())
KEY = None


def call(ep, body):
    req = urllib.request.Request(f'https://api.voyageai.com/v1/{ep}', json.dumps(body).encode(),
                                 {'Authorization': 'Bearer ' + KEY, 'content-type': 'application/json'})
    return common.open_json(req, timeout=600)


def embed(items, input_type, usage):
    """Unit-norm embeddings for (text, tokens) items. Cached vectors are reused; new ones are stored after each
    API batch, so a crashed run resumes without paying again. Stored as float32 whether fresh or cached."""
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(CACHE)
    db.execute('create table if not exists emb (key text primary key, vec blob)')
    keys = [hashlib.sha256(f'{EMBED}\0{input_type}\0{t}'.encode()).hexdigest() for t, _ in items]
    vec = {}
    for k in dict.fromkeys(keys):
        row = db.execute('select vec from emb where key = ?', (k,)).fetchone()
        if row:
            vec[k] = np.frombuffer(row[0], np.float32)
    cached = len(vec)
    todo = list({k: it for k, it in zip(keys, items) if k not in vec}.items())
    for part in batches(todo, lambda x: x[1][1], EMBED_BATCH):
        r = call('embeddings', {'input': [it[0] for _, it in part], 'model': EMBED, 'input_type': input_type, 'truncation': False})
        usage['embed'] += r['usage']['total_tokens']
        for (k, _), x in zip(part, r['data']):
            vec[k] = np.asarray(x['embedding'], np.float32)
        db.executemany('insert or replace into emb values (?, ?)', [(k, vec[k].tobytes()) for k, _ in part])
        db.commit()
    db.close()
    usage['embed_cached'] += cached
    E = np.array([vec[k] for k in keys], float)
    return E / np.linalg.norm(E, axis=1, keepdims=True)


def tokenizer():
    from tokenizers import Tokenizer
    if not TOK_PATH.exists():
        TOK_PATH.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(TOK_URL, TOK_PATH)
    return Tokenizer.from_file(str(TOK_PATH))


def find_pdfs(dirs, known, ids=None):
    """Paper id -> PDF. Papers in the sources table keep their key; every other PDF is named by its file stem."""
    out = {k: v['pdf'] for k, v in known.items() if v['pdf'] and v['pdf'].is_file()}
    taken = {p.resolve() for p in out.values()}
    gone = [str(d) for d in dirs if not Path(d).is_dir()]
    if gone:
        sys.exit(f'PDF folder not found: {", ".join(gone)}. Check "pdf_dirs" in the config or --dirs')
    for d in dirs:
        for p in sorted(Path(d).rglob('*.pdf')):
            if p.resolve() in taken:
                continue
            pid, n = p.stem, 2
            while pid in out:
                pid, n = f'{p.stem}-{n}', n + 1
            if pid != p.stem:
                print(f'note: {p} has the same name as {out[p.stem]}; ranked as {pid}', file=sys.stderr)
            out[pid] = p; taken.add(p.resolve())
    if ids:
        missing = [i for i in ids if i not in out]
        if missing:
            sys.exit(f'no PDF for {missing}')
        out = {i: out[i] for i in ids}
    if not out:
        sys.exit(f'no PDFs in {", ".join(map(str, dirs))}. Add PDFs there, or search and fetch them first')
    return out


def clean(text):
    """Cut the bibliography if a References heading in the second half is followed by citation entries; keep appendices."""
    heads = [m for m in re.finditer(r'(?m)^\s*(?:[IVX]+\.\s*|\d+\.?\s*)?(r ?eferences|b ?ibliography)\s*$', text, re.I)
             if m.start() > len(text) * 0.5]
    if not heads:
        return text, False, None
    start = heads[-1].start()
    tail = text[start:start + 5000]
    if len(re.findall(r'(?m)^\s*\[\d+\]', tail)) < 3 and len(re.findall(r'\(\d{4}\)|, \d{4}\.', tail)) < 3:
        return text, False, None
    app = re.search(r'(?m)^\s*(?:[A-Z]\.?\s*)?(a ?ppendix|a ?ppendices|s ?upplementary material)\b', text[start:], re.I)
    if not app:
        return text[:start], True, None
    return text[:start] + text[start + app.start():], True, (start, app.start())


def abstract(text):
    m = re.search(r'abstract\W{0,3}(.{300,3000}?)(?=\b(?:I\.|1\.?)?\s*i ?ntroduction\b)', text[:15000], re.I | re.S)
    return m.group(1).strip() if m else None


def windows(path, tok):
    pages = subprocess.run(['pdftotext', str(path), '-'], capture_output=True, text=True).stdout.split('\f')
    starts, text = [], ''
    for p in pages:
        starts.append(len(text)); text += re.sub(r'[ \t]+', ' ', p) + '\n'
    body, cut, shift = clean(text)
    enc = tok.encode(body, add_special_tokens=False)
    orig = lambda c: c + shift[1] if shift and c >= shift[0] else c
    page_of = lambda c: sum(1 for s in starts if s <= orig(c))
    wins = []
    for i in range(0, max(1, len(enc.ids) - WIN + STEP), STEP):
        span = enc.offsets[i:i + WIN]
        if not span:
            break
        a, b = span[0][0], span[-1][1]
        p0, p1 = page_of(a), page_of(b - 1)
        wins.append({'text': re.sub(r'\s+', ' ', body[a:b]).strip(), 'pages': f'p. {p0}' if p0 == p1 else f'p. {p0}-{p1}',
                     'span': (i, i + len(span))})
    ab = abstract(text)
    head = ab if ab else tok.decode(tok.encode(text, add_special_tokens=False).ids[:HEAD])
    return [w for w in wins if w['text']], head, cut, ab is not None, len(enc.ids)


def bm25_scores(docs, query, k1=1.2, b=0.75):
    terms = lambda s: [t for t in re.split(r'[^a-z0-9]+', s.lower()) if t and t not in STOP]
    toks = [Counter(terms(d)) for d in docs]
    lens = np.array([sum(t.values()) for t in toks], float); avg = lens.mean() or 1.0
    df = Counter(t for c in toks for t in c)
    out = np.zeros(len(docs))
    for t in dict.fromkeys(terms(query)):
        idf = math.log((len(docs) - df[t] + 0.5) / (df[t] + 0.5) + 1)
        tf = np.array([c[t] for c in toks], float)
        out += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * lens / avg))
    return out


def min_ranks(x):
    """1 = best; ties share the best rank."""
    x = np.asarray(x)
    return np.array([1 + int((x > v).sum()) for v in x])


def pick(wins, score):
    chosen = []
    for j in sorted(range(len(wins)), key=lambda j: -score[j]):
        s = wins[j]['span']
        ok = all(max(0, min(s[1], wins[c]['span'][1]) - max(s[0], wins[c]['span'][0]))
                 / min(s[1] - s[0], wins[c]['span'][1] - wins[c]['span'][0]) < MAX_OVERLAP for c in chosen)
        if ok:
            chosen.append(j)
        if len(chosen) == N_WIN:
            break
    return chosen


def batches(items, cost, limit):
    cur, total = [], 0
    for it in items:
        if cur and total + cost(it) > limit:
            yield cur; cur, total = [], 0
        cur.append(it); total += cost(it)
    if cur:
        yield cur


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()[:12]


def main(argv=None):
    global KEY
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--config', help=f'path to {common.CONFIG_NAME} (default: searched upward from the current folder)')
    ap.add_argument('--queries', help='queries file (default: "queries" in the config)')
    ap.add_argument('--dirs', help='comma-separated PDF folders (default: "pdf_dirs" in the config)')
    ap.add_argument('--ids', help='CSV with a "paper" column: rank exactly these paper ids (frozen corpus)')
    ap.add_argument('--provider', choices=common.PROVIDERS, help='voyage or bm25 (no API key); default: "rank" in the config, else voyage')
    ap.add_argument('--variants', default='hybrid', help='hybrid, dense or hybrid,dense (dense is an ablation); voyage only')
    ap.add_argument('--expect', default='', help='paper ids expected in the first query\'s top 10, fixed before the run')
    ap.add_argument('--budget', type=int, default=15_000_000, help='stop before any API call if the token estimate is higher')
    ap.add_argument('--dry', action='store_true', help='build windows, print counts and the token estimate; no API call')
    ap.add_argument('--out', required=True, help='output path prefix')
    a = ap.parse_args(argv)

    cfg = common.load_config(a.config, required=not (a.dirs and a.queries))
    qpath = a.queries or (cfg and cfg['queries'])
    if not qpath:
        sys.exit('no queries file: pass --queries or set "queries" in the config')
    question, Q, fuse = common.load_queries(qpath)
    prev = Path(f'{a.out}_run.json')
    if prev.is_file() and json.loads(prev.read_text()).get('queries_sha') != sha(json.dumps(Q, sort_keys=True)):
        sys.exit(f'{prev} was made with different queries. A frozen queries file is not edited: '
                 f'write a new queries file and rank it with a new --out')
    provider = a.provider or (cfg and cfg['provider']) or 'voyage'
    variants = a.variants.split(',')
    if any(v not in ('hybrid', 'dense') for v in variants):
        sys.exit('--variants takes hybrid and/or dense')
    if provider == 'bm25':
        if variants != ['hybrid']:
            sys.exit('--variants applies to the voyage provider only')
        variants = ['bm25']
    dirs = [Path(d) for d in a.dirs.split(',')] if a.dirs else cfg['pdf_dirs']
    ids = [r['paper'] for r in csv.DictReader(open(a.ids, encoding='utf-8-sig'))] if a.ids else None

    tok = tokenizer()
    ntok = lambda s: len(tok.encode(s, add_special_tokens=False).ids)
    P, W = [], []
    for pid, path in find_pdfs(dirs, common.sources(cfg), ids).items():
        wins, head, cut, has_ab, n = windows(path, tok)
        if not wins:
            print(f'note: no text extracted from {path}; skipped', file=sys.stderr); continue
        P.append({'id': pid, 'path': str(path), 'head': head, 'bib_cut': cut, 'abstract_found': has_ab, 'tokens': n,
                  'wins': list(range(len(W), len(W) + len(wins)))})
        W += [dict(w, paper=len(P) - 1) for w in wins]
    if not P:
        sys.exit('no PDFs with extractable text')
    for w in W:
        w['n'] = ntok(w['text'])
    head_n = [ntok(p['head']) for p in P]
    pkg = sum(h + sum(sorted((W[j]['n'] for j in p['wins']), reverse=True)[:N_WIN]) for h, p in zip(head_n, P))
    estimate = sum(w['n'] for w in W) + len(variants) * sum(pkg + ntok(q['text']) * len(P) for q in Q.values())
    print(f'{len(P)} papers, {len(W)} windows, bibliography cut in {sum(p["bib_cut"] for p in P)}, '
          f'abstract found in {sum(p["abstract_found"] for p in P)}; {len(Q)} queries, fuse {fuse}; '
          + (f'estimated {estimate:,} tokens' if provider == 'voyage' else 'provider bm25, no API call'), file=sys.stderr)
    if a.dry:
        for p in P:
            print(p['id'], p['tokens'], len(p['wins']), 'bib' if p['bib_cut'] else '-', 'abs' if p['abstract_found'] else '-', sep='\t')
        return
    usage = Counter()
    if provider == 'voyage':
        if estimate > a.budget:
            sys.exit(f'estimate {estimate:,} tokens is above --budget {a.budget:,}; raise --budget to run')
        KEY = common.api_key('VOYAGE_API_KEY', cfg)
        E = embed([(w['text'], w['n']) for w in W], 'document', usage)
        QE = embed([(q['text'], ntok(q['text'])) for q in Q.values()], 'query', usage)

    outputs = {}
    for variant in variants:
        rows = {p['id']: {'paper': p['id']} for p in P}
        sanity = None
        for qi, (qid, q) in enumerate(Q.items()):
            col = f'{qid}_{q["label"]}'
            cos = E @ QE[qi] if variant != 'bm25' else None
            lex = bm25_scores([w['text'] for w in W], q['keywords'] or q['text']) if variant != 'dense' else None
            pkgs = []
            for pi, p in enumerate(P):
                idx = p['wins']
                score = 1 / (RRF_K + min_ranks(cos[idx])) if cos is not None else np.zeros(len(idx))
                if lex is not None:
                    l = lex[idx]
                    score = score + np.where(l > 0, 1 / (RRF_K + min_ranks(l)), 0)
                chosen = [idx[k] for k in pick([W[j] for j in idx], score)]
                text = 'Abstract: ' + p['head'] + ''.join(f"\n\n[{W[j]['pages']}] {W[j]['text']}" for j in chosen)
                pkgs.append({'pi': pi, 'text': text, 'n': ntok(text), 'pages': '; '.join(W[j]['pages'] for j in chosen)})
            qn, score = ntok(q['text']), {}
            if variant == 'bm25':
                score = {k['pi']: float(v) for k, v in zip(pkgs, bm25_scores([k['text'] for k in pkgs], q['keywords'] or q['text']))}
            for part in (batches(pkgs, lambda k: k['n'] + qn, RERANK_BATCH) if variant != 'bm25' else []):
                r = call('rerank', {'query': q['text'], 'documents': [k['text'] for k in part], 'model': RERANK, 'truncation': False})
                usage['rerank'] += r['usage']['total_tokens']
                for x in r['data']:
                    score[part[x['index']]['pi']] = x['relevance_score']
            for k in pkgs:
                row = rows[P[k['pi']]['id']]
                row[f'{col}_rank'] = 1 + sum(1 for v in score.values() if v > score[k['pi']])
                row[f'{col}_score'] = round(score[k['pi']], 4)
                row[f'{col}_pages'] = k['pages']
            if sanity is None:
                sanity = [P[i]['id'] for i in sorted(score, key=lambda i: (-score[i], P[i]['id']))[:10]]
        cols = {qid: f'{qid}_{q["label"]}' for qid, q in Q.items()}
        for r in rows.values():
            r['_fs'] = sum(1 / (RRF_K + r[f'{cols[q]}_rank']) for q in fuse)
        for r in rows.values():
            r['fused_rank'] = 1 + sum(1 for o in rows.values() if o['_fs'] > r['_fs'])
            r['fused_score'] = round(r['_fs'], 6)
        first = cols[next(iter(Q))]
        order = sorted(rows.values(), key=lambda r: (-r['_fs'], r[f'{first}_rank'], r['paper']))
        meta = {p['id']: p for p in P}
        head = ['paper', 'fused_rank', 'fused_score'] + [f'{c}_{s}' for c in cols.values() for s in ('rank', 'score')] \
            + [f'{c}_pages' for c in cols.values()] + ['tokens', 'bib_cut', 'abstract_found']
        path = Path(f'{a.out}_{variant}.csv'); path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f); w.writerow(head)
            for r in order:
                m = meta[r['paper']]
                w.writerow([r.get(h, m.get(h)) for h in head])
        outputs[variant] = {'csv': str(path), 'fused_top10': [r['paper'] for r in order[:10]], 'first_query_top10': sanity}
        print(f'[{variant}] fused top 10: ' + ', '.join(r['paper'] for r in order[:10]))
        if a.expect:
            exp = [k for k in a.expect.split(',') if k]
            print(f'[{variant}] sanity check: {sum(k in sanity for k in exp)} of {len(exp)} expected papers in '
                  f'{next(iter(Q))} top 10; missing: {[k for k in exp if k not in sanity]}')
        print(f'[{variant}] -> {path}', file=sys.stderr)

    try:
        commit = subprocess.run(['git', '-C', str(Path(__file__).resolve().parent), 'rev-parse', '--short', 'HEAD'],
                                capture_output=True, text=True).stdout.strip()
    except OSError:
        commit = ''
    run = {'created': datetime.datetime.now().isoformat(timespec='seconds'), 'paper_lector_commit': commit,
           'question': question, 'queries': Q, 'queries_sha': sha(json.dumps(Q, sort_keys=True)), 'fuse': fuse,
           'models': {'provider': provider, 'embed': EMBED if provider == 'voyage' else None,
                      'rerank': RERANK if provider == 'voyage' else None, 'tokenizer': TOK_URL},
           'params': {'window': WIN, 'step': STEP, 'rrf_k': RRF_K, 'windows_per_paper': N_WIN, 'max_overlap': MAX_OVERLAP},
           'corpus': {'papers': len(P), 'windows': len(W), 'ids': [p['id'] for p in P]},
           'expect': a.expect, 'usage': dict(usage), 'estimate': estimate, 'outputs': outputs}
    Path(f'{a.out}_run.json').write_text(json.dumps(run, indent=1, ensure_ascii=False))
    print(f'tokens: embed {usage["embed"]:,} ({usage["embed_cached"]:,} texts from cache), rerank {usage["rerank"]:,} '
          f'-> {a.out}_run.json', file=sys.stderr)


if __name__ == '__main__':
    main()
