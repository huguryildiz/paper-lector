"""Write <question>/subset20.csv: the gold PDFs plus the first downloaded candidates in DEIXIS order, 20 in all.
Questions whose gold PDF was not downloaded get no file. rank.py --ids subset20.csv ranks exactly these PDFs."""
import csv, json
from pathlib import Path

SIZE = 20
HERE = Path(__file__).resolve().parent

for q in json.loads((HERE / 'questions.json').read_text())['questions']:
    d = HERE / q['id']
    log = [json.loads(x) for x in (d / 'pdfs/fetch_log.jsonl').open()] if (d / 'pdfs/fetch_log.jsonl').exists() else []
    files = {}
    for r in log:
        if r['status'] in ('OK', 'HAVE'):
            f = Path(r.get('file') or r.get('path') or '').name
            files.setdefault(r['id'].lower(), (Path(f).stem, r['sha256']))
    gold = [files[k] for g in q['gold'] if (k := (g['doi'] or g['openalex'][0]).lower()) in files]
    if not gold:
        continue
    rows = list(dict.fromkeys(gold))
    for x in q['distractors']:
        if len(rows) == SIZE:
            break
        if x['doi'] in files and files[x['doi']] not in rows:
            rows.append(files[x['doi']])
    with open(d / 'subset20.csv', 'w', newline='') as f:
        w = csv.writer(f); w.writerow(['paper', 'sha256', 'gold'])
        w.writerows([p, s, int(i < len(gold))] for i, (p, s) in enumerate(rows))
