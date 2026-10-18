"""Compare search files: how many works each holds, how many they share, and the distinct total.

A work is the same in two files when they give the same OpenAlex id, DOI or arXiv id. The mode of each file comes
from its .query.json. With a keyword and a semantic file, it prints the share of semantic works the keyword file
also holds, LOW OVERLAP when that share is under half (the keyword query probably misses words the field uses:
measured on the entanglement-scheduling example, 20 of 50), and the titles of the semantic works the keyword file lacks.

Usage: search_overlap.py <file>_search.jsonl <file>_search.jsonl [...]
"""
import json, sys
from pathlib import Path

LOW = 0.5


def ids(r):
    return {x for x in (r.get('openalex'), r.get('doi'), r.get('arxiv')) if x}


def load(path):
    """(mode, records) of a search file; a missing file or a broken line stops with the file and line named."""
    p = Path(path)
    if not p.is_file():
        sys.exit(f'{path}: file not found')
    side = p.with_suffix('.query.json')
    try:
        mode = json.loads(side.read_text(encoding='utf-8')).get('mode') if side.is_file() and side.stat().st_size else None
    except (ValueError, AttributeError):
        sys.exit(f'{side}: not a query record (broken JSON)')
    recs = []
    for n, l in enumerate(p.read_text(encoding='utf-8').splitlines(), 1):
        if l.strip():
            try:
                r = json.loads(l)
                if not isinstance(r, dict):
                    raise ValueError('not an object')
            except ValueError as e:
                sys.exit(f'{path} line {n}: not a JSON record ({e})')
            recs.append(r)
    return mode, recs


def held_by(r, works):
    return any(ids(r) & ids(w) for w in works)


def distinct(works):
    seen, out = [], []
    for r in works:
        if not held_by(r, seen):
            seen.append(r); out.append(r)
    return out


def main(argv=None):
    paths = argv if argv is not None else sys.argv[1:]
    if len(paths) < 2:
        sys.exit(__doc__.strip().splitlines()[-1])
    files = [(p, *load(p)) for p in paths]
    for p, mode, works in files:
        print(f'{mode or "?":9} {len(works):5}  {Path(p).name}')
    print(f'distinct works: {len(distinct([r for _, _, ws in files for r in ws]))}')
    for i, (p, _, a) in enumerate(files):
        for q, _, b in files[i + 1:]:
            print(f'shared: {sum(held_by(r, b) for r in distinct(a))}  {Path(p).name} & {Path(q).name}')
    kw = [r for _, mode, ws in files if mode == 'exact' for r in ws]
    sem = distinct([r for _, mode, ws in files if mode == 'semantic' for r in ws])
    if kw and sem:
        missing = [r for r in sem if not held_by(r, kw)]
        share = 1 - len(missing) / len(sem)
        print(f'semantic works the keyword search also found: {len(sem) - len(missing)} of {len(sem)} ({share:.0%})'
              + ('  LOW OVERLAP' if share < LOW else ''))
        for r in missing:
            print(f'  only semantic: {r.get("year") or "-"}  {r.get("title")}')


if __name__ == '__main__':
    main()
