"""Score the 20-PDF voyage runs: best gold rank per question for main only (Q0_main_rank) and fused (fused_rank);
hit@3/5/10, MRR, and a paired bootstrap of the MRR difference. Writes results20.json."""
import csv, glob, json, random
from pathlib import Path

HERE = Path(__file__).resolve().parent
rows = []
for sub in sorted(HERE.glob('ls*/subset20.csv')):
    q = sub.parent
    gold = {r['paper'] for r in csv.DictReader(sub.open()) if r['gold'] == '1'}
    runs = sorted(glob.glob(str(q / 'runs/*_rank.csv')))
    if not runs:
        continue
    ranked = list(csv.DictReader(open(runs[-1], encoding='utf-8')))
    best = lambda col: min(int(r[col]) for r in ranked if r['paper'] in gold)
    rows.append({'id': q.name, 'n': len(ranked), 'main': best('Q0_main_rank'), 'fused': best('fused_rank')})


def stats(key):
    r = [x[key] for x in rows]
    return {f'hit@{k}': round(sum(v <= k for v in r) / len(r), 2) for k in (3, 5, 10)} | \
           {'mrr': round(sum(1 / v for v in r) / len(r), 2)}


diff = [1 / x['main'] - 1 / x['fused'] for x in rows]
rng = random.Random(20261018)
boot = sorted(sum(rng.choice(diff) for _ in diff) / len(diff) for _ in range(10000))
out = {'questions': len(rows), 'main': stats('main'), 'fused': stats('fused'),
       'mrr_main_minus_fused': round(sum(diff) / len(diff), 3),
       'ci95': [round(boot[249], 3), round(boot[9749], 3)],
       'main_better': sum(x['main'] < x['fused'] for x in rows), 'main_worse': sum(x['main'] > x['fused'] for x in rows),
       'per_question': rows}
(HERE / 'results20.json').write_text(json.dumps(out, indent=1) + '\n')
print(json.dumps({k: v for k, v in out.items() if k != 'per_question'}, indent=1))
