"""Build the LitSearch test set from DEIXIS's data: one folder per question with literature.json and ids.txt.

Questions: the first 50 of DEIXIS's seeded sample (seed 20261017). Collection per question: its gold papers plus the
first arXiv or ACL papers of DEIXIS's pre-rerank candidate list for that question (gold excluded), up to SIZE in all.
Usage: build.py <DEIXIS .local/litsearch folder>
"""
import json, sys
from pathlib import Path

N_QUESTIONS, SIZE = 50, 40
HERE = Path(__file__).resolve().parent
OPEN = ('10.48550/arxiv.', '10.18653/')          # arXiv and ACL Anthology DOIs: open PDFs


def pick_doi(dois):
    """arXiv DOI first (fetched straight from arXiv), else ACL, else None."""
    dois = [d.lower() for d in dois if d]
    return next((d for d in dois if d.startswith(OPEN[0])), None) or next((d for d in dois if d.startswith(OPEN[1])), None)


def main(src):
    sample = json.loads((src / 'sample.json').read_text())
    gold_meta = json.loads((src / 'gold_meta.json').read_text())
    pools = {r['id']: r['records'] for r in map(json.loads, (src / 'runs/deixis.jsonl').open())}
    out = []
    for q in sample['questions'][:N_QUESTIONS]:
        gold = []
        for g in q['gold']:
            m = gold_meta[g]
            gold.append({'corpus_id': g, 'title': m['title'], 'doi': pick_doi(m['dois']), 'openalex': m['openalex']})
        gold_oa = {w for g in gold for w in g['openalex']}
        gold_dois = {d.lower() for g in q['gold'] for d in gold_meta[g]['dois']}
        distractors = []
        for r in pools[q['id']]:
            d = (r.get('doi') or '').lower()
            if not d.startswith(OPEN) or d in gold_dois or r.get('openalex') in gold_oa:
                continue
            if d not in {x['doi'] for x in distractors}:
                distractors.append({'doi': d, 'title': r['title'], 'openalex': r.get('openalex')})
            if len(gold) + len(distractors) == SIZE:
                break
        folder = HERE / q['id']
        (folder / 'queries').mkdir(parents=True, exist_ok=True)
        (folder / 'literature.json').write_text(json.dumps(
            {'pdf_dirs': ['pdfs'], 'download_dir': 'pdfs', 'queries': 'queries/queries.json',
             'rank': {'provider': 'voyage'}}, indent=2) + '\n')
        ids = [g['doi'] or g['openalex'][0] for g in gold] + [x['doi'] for x in distractors]
        (folder / 'ids.txt').write_text('\n'.join(ids) + '\n')
        out.append({'id': q['id'], 'question': q['body'], 'query_set': q['query_set'], 'specificity': q['specificity'],
                    'quality': q['quality'], 'gold': gold, 'distractors': distractors})
    (HERE / 'questions.json').write_text(json.dumps(
        {'source': 'DEIXIS .local/litsearch (sample.json, gold_meta.json, runs/deixis.jsonl)', 'seed': sample['seed'],
         'size': SIZE, 'questions': out}, indent=1, ensure_ascii=False) + '\n')
    print(f'{len(out)} questions; collection sizes {sorted(len(q["gold"]) + len(q["distractors"]) for q in out)}')


if __name__ == '__main__':
    main(Path(sys.argv[1]))
