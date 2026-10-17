"""Offline fixtures: tiny real PDFs, a whitespace tokenizer, a fake Voyage API and a fake local model."""
import hashlib, re, sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))


def make_pdf(path, pages):
    """Write a minimal PDF; pages is a list of lists of text lines."""
    objs, kids = [], []
    font_id = 3
    for i, lines in enumerate(pages):
        content = 'BT /F1 10 Tf 12 TL 40 760 Td ' + ' '.join(
            '(' + l.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)') + ') Tj T*' for l in lines) + ' ET'
        cid, pid = 4 + 2 * i, 5 + 2 * i
        objs.append((cid, f'<< /Length {len(content)} >>\nstream\n{content}\nendstream'))
        objs.append((pid, f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {cid} 0 R >>'))
        kids.append(f'{pid} 0 R')
    objs = [(1, '<< /Type /Catalog /Pages 2 0 R >>'),
            (2, f'<< /Type /Pages /Kids [{" ".join(kids)}] /Count {len(pages)} >>'),
            (3, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>')] + objs
    out, offs = b'%PDF-1.4\n', {}
    for n, body in sorted(objs):
        offs[n] = len(out)
        out += f'{n} 0 obj\n{body}\nendobj\n'.encode('latin-1')
    xref = len(out)
    out += f'xref\n0 {len(objs) + 1}\n0000000000 65535 f \n'.encode()
    for n in range(1, len(objs) + 1):
        out += f'{offs[n]:010d} 00000 n \n'.encode()
    out += f'trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()
    Path(path).write_bytes(out)


class _Enc:
    def __init__(self, ids, offsets):
        self.ids, self.offsets = ids, offsets


class WordTokenizer:
    """One token per whitespace-separated word, with character offsets like tokenizers.Encoding."""
    def __init__(self):
        self.vocab = []

    def encode(self, text, add_special_tokens=False):
        ids, offs = [], []
        for m in re.finditer(r'\S+', text):
            self.vocab.append(m.group()); ids.append(len(self.vocab) - 1); offs.append((m.start(), m.end()))
        return _Enc(ids, offs)

    def decode(self, ids):
        return ' '.join(self.vocab[i] for i in ids)


def bag(text, dim=64):
    v = np.zeros(dim)
    for t in re.findall(r'[a-z]+', text.lower()):
        v[int(hashlib.md5(t.encode()).hexdigest(), 16) % dim] += 1
    return (v + 1e-3).tolist()


def local_vecs(texts):
    """Stands in for rank.local_model(): unit-norm hashed bag of words."""
    V = np.array([bag(t, 4096) for t in texts], float).reshape(-1, 4096)
    return V / np.linalg.norm(V, axis=1, keepdims=True)


class FakeVoyage:
    """Embeddings = hashed bag of words; rerank score = share of query words found in the document."""
    def __init__(self):
        self.calls = []

    def __call__(self, ep, body):
        self.calls.append((ep, body))
        if ep == 'embeddings':
            return {'data': [{'embedding': bag(t)} for t in body['input']],
                    'usage': {'total_tokens': sum(len(t.split()) for t in body['input'])}}
        q = set(re.findall(r'[a-z]+', body['query'].lower()))
        data = [{'index': i, 'relevance_score': len(q & set(re.findall(r'[a-z]+', d.lower()))) / max(1, len(q))}
                for i, d in enumerate(body['documents'])]
        return {'data': sorted(data, key=lambda x: -x['relevance_score']),
                'usage': {'total_tokens': sum(len(d.split()) for d in body['documents'])}}


@pytest.fixture
def project(tmp_path):
    """A project with a .git marker, three PDFs, a sources table, a queries file and literature.json."""
    root = tmp_path / 'proj'
    (root / '.git').mkdir(parents=True)
    pdfs = root / 'papers' / 'topic'
    pdfs.mkdir(parents=True)
    filler = ['lorem ipsum dolor sit amet consectetur'] * 40
    make_pdf(pdfs / 'Switch2024.pdf', [
        ['Age based scheduling at a quantum switch', 'Abstract', 'We study which user receives a stored entangled pair.'] + filler,
        ['Our policy serves the youngest stored pair first', 'threshold structure of the optimal policy'] + filler,
        ['References', '[1] A. Author, Title one, 2020.', '[2] B. Author, Title two, 2021.', '[3] C. Author, Title three, 2022.',
         '[4] D. Author, quantum switch scheduling survey, 2023.']])
    make_pdf(pdfs / 'Ocean2023.pdf', [
        ['Underwater optical links in seawater', 'Abstract', 'We measure attenuation of light in seawater channels.'] + filler,
        ['Turbulence and scattering in the ocean'] + filler])
    make_pdf(pdfs / 'Queue2022.pdf', [
        ['Last in first out service discipline for noisy memories', 'Abstract', 'Requests wait in a buffer.'] + filler,
        ['LIFO with pushout maximizes average fidelity'] + filler])
    (root / 'sources.csv').write_text('key,pdf_path,doi\nqueue2022,papers/topic/Queue2022.pdf,10.1/q\n')
    (root / 'queries').mkdir()
    (root / 'queries/queries.json').write_text('''{
 "question": "Which user should receive an ageing stored entangled pair?",
 "queries": {
  "Q0": {"label": "main", "text": "Which user receives a stored entangled pair at a quantum switch", "keywords": "user stored entangled pair switch"},
  "Q1": {"label": "subject", "text": "quantum switch with memories and waiting requests buffer", "keywords": "switch memory buffer requests"},
  "Q2": {"label": "approach", "text": "service discipline youngest first LIFO policy", "keywords": "lifo youngest discipline policy"},
  "Q3": {"label": "context", "text": "underwater seawater ocean links", "keywords": "underwater seawater ocean"},
  "Q4": {"label": "comparison", "text": "", "keywords": ""}
 }
}''')
    (root / 'literature.json').write_text('{"pdf_dirs": ["papers"], "download_dir": "papers/new", "sources": "sources.csv", "queries": "queries/queries.json"}')
    return root
