"""Baselines on the 20-PDF set, scored like evaluate20.py: best gold rank per question, hit@3/5/10, MRR, and a paired
bootstrap of the MRR difference against paper-lector (voyage, fused and main only, from each question's run CSV).

  random          expected value of a uniformly random order (exact, no sampling)
  bm25_full       BM25 over each paper's full text with the bibliography cut, as rank.py extracts it
  bm25_abstract   BM25 over the abstract rank.py reads first (PDF abstract, else the opening 1,000 tokens)
  rerank_abstract rerank-3 on that same abstract alone (--voyage): rank.py's step 4 without the windows

Every baseline uses the main query's text, the LitSearch question as written. Ties share the best rank, as in
rank.py. PDFs come from download.sh and are matched to subset20.csv by SHA-256; a question with a missing PDF stops
the script. Writes baselines20.json (rerank_abstract only with --voyage).

  ../../.venv/bin/python baselines20.py                 # random and BM25, offline
  ../../.venv/bin/python baselines20.py --voyage --dry  # token estimate for rerank_abstract, no API call
  ../../.venv/bin/python baselines20.py --voyage        # adds rerank_abstract
"""
import argparse, csv, glob, json, random, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / 'scripts'))
import common, rank


def texts(path, tok):
    """(full text with the bibliography cut, head) as rank.windows builds them."""
    text = ''
    for p in rank.pdf_pages(path):
        text += re.sub(r'[ \t]+', ' ', p) + '\n'
    body, _, _ = rank.clean(text)
    ab, _ = rank.abstract(body)
    return body, ab if ab else tok.decode(tok.encode(body, add_special_tokens=False).ids[:rank.HEAD])


def load(q, tok):
    rows = list(csv.DictReader((q / 'subset20.csv').open()))
    held = {common.sha256_file(p): p for p in (q / 'pdfs').rglob('*.pdf', case_sensitive=False)} \
        if (q / 'pdfs').is_dir() else {}
    gone = [r['paper'] for r in rows if r['sha256'] not in held]
    if gone:
        sys.exit(f'{q.name}: {len(gone)} PDFs of subset20.csv not found under {q.name}/pdfs (first: {gone[0]}); '
                 f'run download.sh')
    papers = []
    for r in rows:
        body, head = texts(held[r['sha256']], tok)
        papers.append({'id': r['paper'], 'gold': r['gold'] == '1', 'body': body, 'head': head})
    query = json.loads((q / 'queries/queries.json').read_text())['queries']['Q0']['text']
    return papers, query


def best(ranks, papers):
    return int(min(k for k, p in zip(ranks, papers) if p['gold']))


def random_expected(n, g):
    """Expected hit@k and 1/rank of the best of g gold papers among n in a random order."""
    from math import comb
    p_le = lambda k: 1 - comb(n - g, k) / comb(n, k) if k < n else 1.0
    return {**{f'hit@{k}': p_le(k) for k in (3, 5, 10)},
            'rr': sum((p_le(r) - p_le(r - 1)) / r for r in range(1, n + 1))}


def summary(rows, key):
    r = [x[key] for x in rows]
    return {f'hit@{k}': round(sum(v <= k for v in r) / len(r), 2) for k in (3, 5, 10)} | \
           {'mrr': round(sum(1 / v for v in r) / len(r), 2)}


def paired(rows, a, b, seed=20261018):
    diff = [1 / x[a] - 1 / x[b] for x in rows]
    rng = random.Random(seed)
    boot = sorted(sum(rng.choice(diff) for _ in diff) / len(diff) for _ in range(10000))
    return {'mrr_diff': round(sum(diff) / len(diff), 3), 'ci95': [round(boot[249], 3), round(boot[9749], 3)],
            'better': sum(x[a] < x[b] for x in rows), 'worse': sum(x[a] > x[b] for x in rows)}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--voyage', action='store_true', help='also rank with rerank-3 on the abstract alone (paid)')
    ap.add_argument('--dry', action='store_true', help='with --voyage: print the token estimate, no API call')
    ap.add_argument('--budget', type=int, default=2_000_000, help='stop before any API call above this many tokens')
    a = ap.parse_args()

    tok = rank.tokenizer()
    ntok = lambda s: len(tok.encode(s, add_special_tokens=False).ids)
    data = []
    for sub in sorted(HERE.glob('ls*/subset20.csv')):
        q = sub.parent
        runs = sorted(glob.glob(str(q / 'runs/*_rank.csv')))
        if not runs:
            continue
        papers, query = load(q, tok)
        ranked = {r['paper']: r for r in csv.DictReader(open(runs[-1], encoding='utf-8'))}
        if set(ranked) != {p['id'] for p in papers}:
            sys.exit(f'{q.name}: the run CSV and subset20.csv list different papers')
        data.append((q.name, papers, query, ranked))

    docs = lambda papers: ['Abstract: ' + p['head'] for p in papers]
    if a.voyage:
        estimate = sum(sum(ntok(d) for d in docs(papers)) + ntok(query) * len(papers) for _, papers, query, _ in data)
        print(f'rerank_abstract: {len(data)} questions, estimated {estimate:,} tokens (rerank-3)', file=sys.stderr)
        if a.dry:
            return
        if estimate > a.budget:
            sys.exit(f'estimate {estimate:,} tokens is above --budget {a.budget:,}; raise --budget to run')
        rank.KEY, rank.SENT, rank.BUDGET = common.api_key('VOYAGE_API_KEY'), 0, a.budget

    rows, rand = [], []
    for name, papers, query, ranked in data:
        pl = lambda col: min(int(ranked[p['id']][col]) for p in papers if p['gold'])
        row = {'id': name, 'n': len(papers), 'fused': pl('fused_rank'), 'main': pl('Q0_main_rank'),
               'bm25_full': best(rank.min_ranks(rank.bm25_scores([p['body'] for p in papers], query)), papers),
               'bm25_abstract': best(rank.min_ranks(rank.bm25_scores([p['head'] for p in papers], query)), papers)}
        if a.voyage:
            d = docs(papers)
            r = rank.call('rerank', {'query': query, 'documents': d, 'model': rank.RERANK, 'truncation': False},
                          sum(ntok(x) for x in d) + ntok(query) * len(d))
            sc = rank.rerank_scores(r, len(d))
            row['rerank_abstract'] = best(rank.min_ranks([sc[i] for i in range(len(d))]), papers)
        rows.append(row)
        rand.append(random_expected(len(papers), sum(p['gold'] for p in papers)))

    keys = ['fused', 'main', 'bm25_full', 'bm25_abstract'] + ['rerank_abstract'] * a.voyage
    out = {'questions': len(rows), 'query': 'Q0 text (LitSearch question)',
           'random': {k: round(sum(x[k] for x in rand) / len(rand), 2) for k in ('hit@3', 'hit@5', 'hit@10')}
           | {'mrr': round(sum(x['rr'] for x in rand) / len(rand), 2)},
           **{k: summary(rows, k) for k in keys},
           'fused_minus': {k: paired(rows, 'fused', k) for k in keys[2:]},
           'per_question': rows}
    (HERE / 'baselines20.json').write_text(json.dumps(out, indent=1) + '\n')
    print(json.dumps({k: v for k, v in out.items() if k != 'per_question'}, indent=1))


if __name__ == '__main__':
    main()
