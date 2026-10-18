import csv, json

import numpy as np
import pytest

import rank
from conftest import FakeVoyage, WordTokenizer, local_vecs, needs


@pytest.fixture
def offline(monkeypatch, tmp_path):
    fake = FakeVoyage()
    monkeypatch.setattr(rank, 'CACHE', tmp_path / 'cache' / 'embeddings.sqlite')
    monkeypatch.setattr(rank, 'call', fake)
    monkeypatch.setattr(rank, 'tokenizer', WordTokenizer)
    monkeypatch.setattr(rank, 'local_model', lambda: local_vecs)
    monkeypatch.setattr(rank, 'WIN', 60)
    monkeypatch.setattr(rank, 'STEP', 50)
    monkeypatch.setenv('VOYAGE_API_KEY', 'test')
    return fake


def test_windows_cut_bibliography_and_label_pages(project):
    rank.WIN, rank.STEP = 60, 50
    try:
        wins, head, cut, has_ab, n = rank.windows(project / 'papers/topic/Switch2024.pdf', WordTokenizer())
    finally:
        rank.WIN, rank.STEP = 1200, 1000
    assert cut is True
    assert not any('Title three' in w['text'] for w in wins)
    assert {w['pages'] for w in wins} >= {'p. 1', 'p. 2'}
    assert any('youngest' in w['text'] and '2' in w['pages'] for w in wins)
    assert 'Title three' not in head                                  # no abstract found: head comes from cleaned text


def test_bm25_prefers_matching_doc():
    s = rank.bm25_scores(['seawater links', 'quantum switch scheduling', 'switch'], 'switch scheduling')
    assert s[1] > s[2] > s[0] == 0


def test_min_ranks_share_ties():
    assert rank.min_ranks(np.array([0.5, 0.9, 0.5, 0.1])).tolist() == [2, 1, 2, 4]


def test_pick_respects_overlap():
    wins = [{'spans': [(0, 100)]}, {'spans': [(10, 110)]}, {'spans': [(90, 190)]}, {'spans': [(200, 300)]}]
    assert rank.pick(wins, np.array([4, 3, 2, 1])) == [0, 2, 3]


def test_dry_run_makes_no_api_call(project, offline, monkeypatch, capsys):
    monkeypatch.chdir(project)
    rank.main(['--out', str(project / 'runs/r'), '--dry'])
    assert offline.calls == []
    assert 'estimated' in capsys.readouterr().err
    assert not (project / 'runs').exists()


def test_budget_stops_before_api(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    with pytest.raises(SystemExit, match='above --budget'):
        rank.main(['--out', str(project / 'runs/r'), '--budget', '10'])
    assert offline.calls == []


def test_full_run_columns_fusion_and_run_record(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    rank.main(['--out', str(project / 'runs/r'), '--expect', 'Switch2024'])
    rows = list(csv.DictReader(open(project / 'runs/r_paper-lector_rank.csv')))
    assert list(rows[0])[:10] == ['fused_rank', 'citation', 'link', 'cited_by', 'cited_pct', 'start_pages',
                                 'paper', 'fused_score', 'cited_at', 'Q0_main_rank']
    assert len(rows[0]) == len(set(rows[0]))                      # every column once
    for r in rows:                                                # fuse queries only (Q0, Q1), no repeated label
        assert r['start_pages'] == rank.start_pages([r['Q0_main_pages'], r['Q1_subject_pages']]) != ''
        assert all(len(c.split('; ')) == len(set(c.split('; '))) for k, c in r.items() if k.endswith('_pages'))
    assert 'Q3_context_pages' in rows[0] and not any(k.startswith('Q4') for k in rows[0])
    assert {r['paper'] for r in rows} == {'Switch2024', 'Ocean2023', 'queue2022'}   # sources key kept
    assert rows[0]['paper'] == 'Switch2024' and rows[0]['fused_rank'] == '1'
    q3 = {r['paper']: int(r['Q3_context_rank']) for r in rows}
    assert q3['Ocean2023'] == 1                       # context query still ranked, just not fused
    run = json.load(open(project / 'runs/r_paper-lector_rank_run.json'))
    assert run['fuse'] == ['Q0', 'Q1'] and run['corpus']['papers'] == 3
    assert run['models']['rerank'] == 'rerank-3' and run['usage']['rerank'] > 0
    assert all(b['truncation'] is False for e, b in offline.calls)


def test_dense_variant_and_ids_filter(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    (project / 'ids.csv').write_text('paper\nqueue2022\nOcean2023\n')
    rank.main(['--out', str(project / 'runs/d'), '--variants', 'dense', '--ids', str(project / 'ids.csv')])
    rows = list(csv.DictReader(open(project / 'runs/d_paper-lector_rank-dense.csv')))
    assert {r['paper'] for r in rows} == {'queue2022', 'Ocean2023'}


def test_missing_id_fails(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    (project / 'ids.csv').write_text('paper\nnope\n')
    with pytest.raises(SystemExit, match='no PDF'):
        rank.main(['--out', str(project / 'runs/x'), '--ids', str(project / 'ids.csv')])


def test_local_provider_needs_no_key_or_api(project, offline, monkeypatch, tmp_path):
    monkeypatch.chdir(project)
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.delenv('VOYAGE_API_KEY')
    (project / 'literature.json').write_text('{"pdf_dirs": ["papers"], "sources": "sources.csv", "queries": "queries/queries.json", '
                                             '"rank": {"provider": "local"}}')
    rank.main(['--out', str(project / 'runs/b'), '--budget', '10'])   # budget only guards API tokens
    assert offline.calls == []
    rows = list(csv.DictReader(open(project / 'runs/b_paper-lector_rank-local.csv')))
    assert rows[0]['paper'] == 'Switch2024'
    assert {r['paper']: int(r['Q3_context_rank']) for r in rows}['Ocean2023'] == 1
    assert all(r['Q0_main_pages'] for r in rows)
    run = json.load(open(project / 'runs/b_paper-lector_rank_run.json'))
    assert run['models']['provider'] == 'local' and run['models']['rerank'] is None
    assert run['models']['embed'] == f'{rank.LOCAL}@{rank.LOCAL_REV}' and run['usage'] == {}


def test_provider_flag_overrides_config(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    rank.main(['--out', str(project / 'runs/f'), '--provider', 'local'])
    assert offline.calls == [] and (project / 'runs/f_paper-lector_rank-local.csv').exists()


def test_local_rejects_variants(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    with pytest.raises(SystemExit, match='voyage provider only'):
        rank.main(['--out', str(project / 'runs/v'), '--provider', 'local', '--variants', 'dense'])


def test_changed_queries_refuse_previous_out(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    out = str(project / 'runs/q')
    rank.main(['--out', out, '--provider', 'local'])
    with pytest.raises(SystemExit, match='already exists'):            # same queries: never overwrite a run
        rank.main(['--out', out, '--provider', 'local'])
    rank.main(['--out', out, '--provider', 'local', '--dry'])           # a dry run writes nothing, so it may reuse it
    q = project / 'queries/queries.json'
    q.write_text(q.read_text().replace('"question"', '"fuse": ["Q0", "Q3"], "question"'))
    with pytest.raises(SystemExit, match='different question, queries or fuse'):
        rank.main(['--out', out, '--provider', 'local', '--dry'])
    with pytest.raises(SystemExit, match='ranked before with a different question'):   # edited after a run
        rank.main(['--out', str(project / 'runs/q2'), '--provider', 'local'])
    (project / 'queries/queries2.json').write_text(q.read_text())
    rank.main(['--out', str(project / 'runs/q2'), '--provider', 'local', '--queries', str(project / 'queries/queries2.json')])


def test_default_out_is_dated_and_each_run_is_logged(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    monkeypatch.setattr(rank, 'stamp', lambda: '2026-10-17_2315')
    rank.main(['--provider', 'local'])
    rank.main(['--provider', 'local'])                                   # same minute: a suffix, never an overwrite
    assert sorted(p.name for p in (project / 'runs').glob('*.csv')) == ['2026-10-17_2315-2_paper-lector_rank-local.csv', '2026-10-17_2315_paper-lector_rank-local.csv']
    log = [json.loads(l) for l in open(project / 'queries/questions.jsonl')]
    assert [e['out'] for e in log] == ['runs/2026-10-17_2315', 'runs/2026-10-17_2315-2']
    assert log[0]['question'].startswith('Which user should receive') and log[0]['queries'] == 'queries.json'
    rank.main(['--provider', 'local', '--dry'])                          # a dry run is not logged
    assert len(open(project / 'queries/questions.jsonl').readlines()) == 2


def test_missing_pdf_folder_fails(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    with pytest.raises(SystemExit, match='PDF folder not found'):
        rank.main(['--out', str(project / 'runs/x'), '--dry', '--dirs', str(project / 'nope')])


def test_empty_pdf_folder_fails(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    (project / 'empty').mkdir()
    (project / 'literature.json').write_text('{"pdf_dirs": ["empty"], "queries": "queries/queries.json"}')
    with pytest.raises(SystemExit, match='no PDFs in'):
        rank.main(['--out', str(project / 'runs/x'), '--dry'])


def test_embedding_cache_skips_paid_calls_on_rerun(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    rank.main(['--out', str(project / 'runs/c1')])
    first = [e for e, _ in offline.calls].count('embeddings')
    offline.calls.clear()
    rank.main(['--out', str(project / 'runs/c2')])
    assert first > 0 and [e for e, _ in offline.calls].count('embeddings') == 0
    assert open(project / 'runs/c1_paper-lector_rank.csv').read() == open(project / 'runs/c2_paper-lector_rank.csv').read()
    run = json.load(open(project / 'runs/c2_paper-lector_rank_run.json'))
    assert run['usage'].get('embed', 0) == 0 and run['usage']['embed_cached'] > 0


def test_same_file_name_in_two_folders_keeps_both(project, monkeypatch, capsys):
    from conftest import make_pdf
    other = project / 'papers' / 'other'
    other.mkdir()
    make_pdf(other / 'Ocean2023.pdf', [['A different paper about ocean acoustics']])
    make_pdf(other / 'Queue2022.pdf', [['Not the sources-table queue paper']])
    known = {'queue2022': {'pdf': project / 'papers/topic/Queue2022.pdf', 'doi': ''}}
    out = rank.find_pdfs([project / 'papers'], known)
    assert out['queue2022'] == project / 'papers/topic/Queue2022.pdf'
    assert out['Queue2022'] == other / 'Queue2022.pdf'           # same basename as a sources PDF, still ranked
    assert {out['Ocean2023'], out['Ocean2023-2']} == {other / 'Ocean2023.pdf', project / 'papers/topic/Ocean2023.pdf'}
    assert 'ranked as Ocean2023-2' in capsys.readouterr().err



def test_unreadable_pdf_recorded_and_fails_frozen_ids(project, offline, monkeypatch):
    from conftest import make_pdf
    monkeypatch.chdir(project)
    make_pdf(project / 'papers/topic/Scan2020.pdf', [[]])
    rank.main(['--out', str(project / 'runs/s'), '--provider', 'local'])
    run = json.load(open(project / 'runs/s_paper-lector_rank_run.json'))
    assert run['corpus']['skipped'][0]['id'] == 'Scan2020' and 'Scan2020' not in run['corpus']['ids']
    (project / 'ids.csv').write_text('paper\nScan2020\nOcean2023\n')
    with pytest.raises(SystemExit, match='frozen corpus is incomplete'):
        rank.main(['--out', str(project / 'runs/s2'), '--provider', 'local', '--ids', str(project / 'ids.csv')])


def test_identical_copy_skipped_and_near_duplicate_reported(project, offline, monkeypatch):
    from conftest import make_pdf
    monkeypatch.chdir(project)
    src = project / 'papers/topic/Switch2024.pdf'
    (project / 'papers/copy').mkdir()
    (project / 'papers/copy/SwitchCopy.pdf').write_bytes(src.read_bytes())
    make_pdf(project / 'papers/copy/SwitchPreprint.pdf', [
        ['Age based scheduling at a quantum switch (preprint)', 'Abstract',
         'We study which user receives a stored entangled pair.'] + ['lorem ipsum dolor sit amet consectetur'] * 40,
        ['Our policy serves the youngest stored pair first', 'threshold structure of the optimal policy']])
    rank.main(['--out', str(project / 'runs/dup'), '--provider', 'local'])
    run = json.load(open(project / 'runs/dup_paper-lector_rank_run.json'))
    kept = [i for i in run['corpus']['ids'] if i in ('Switch2024', 'SwitchCopy')]
    assert len(kept) == 1                                                  # byte-identical copy not ranked twice
    assert sorted([kept[0], 'SwitchPreprint']) in [sorted(p) for p in run['corpus']['possible_duplicates']]
    assert not any('Ocean2023' in p or 'queue2022' in p for p in run['corpus']['possible_duplicates'])


def test_missing_pdftotext_names_the_install(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    monkeypatch.setattr(rank.shutil, 'which', lambda name: None)
    with pytest.raises(SystemExit, match='brew install poppler'):
        rank.main(['--out', str(project / 'runs/x'), '--dry'])


class cut_download:
    """A download that sends a few bytes, then the connection drops."""
    def __init__(self, url, timeout=None):
        self.left = [b'{"partial']
    def __enter__(self):
        return self
    def __exit__(self, *e):
        pass
    def read(self, n=-1):
        if self.left:
            return self.left.pop()
        raise OSError('no network')


def test_offline_tokenizer_download_fails_cleanly(monkeypatch, tmp_path):
    import urllib.request
    monkeypatch.setattr(rank, 'TOK_PATH', tmp_path / 'tok.json')
    monkeypatch.setattr(urllib.request, 'urlopen', cut_download)
    with pytest.raises(SystemExit, match='rank.py --setup'):
        rank.tokenizer()
    assert not (tmp_path / 'tok.json').exists() and not (tmp_path / 'tok.part').exists()   # no half file left


def test_turkish_abstract_bibliography_and_terms():
    t = 'Başlık\nÖZET\n' + 'kelime ' * 80 + '\nGİRİŞ\nmetin\n'
    assert rank.abstract(t)[0].startswith('kelime')
    assert rank.abstract('Giriş\nözellikle ' + 'kelime ' * 80 + '\nGiriş\n')[0] is None       # "öz" inside a word is no heading
    refs = '\n'.join(f'[{i}] Yazar, Başlık, 2020.' for i in range(1, 6))
    body, cut, _ = rank.clean('satır metin\n' * 400 + 'KAYNAKLAR\n' + refs + '\nEK A\nek tablo\n')
    assert cut and 'Yazar' not in body and 'ek tablo' in body
    s = rank.bm25_scores(['güç tüketimi düşük', 'power routing', 'GÜÇ TÜKETİMİ'], 'güç tüketimi')
    assert s[0] > 0 and s[1] == 0 and s[2] > 0


@pytest.mark.parametrize('ab, intro, bib, app, ref', [
    ('Zusammenfassung', '1 Einleitung', 'Literaturverzeichnis', 'Anhang A', 'Müller, K. (2019). Titel. Verlag.'),
    ('RÉSUMÉ', 'INTRODUCTION', 'RÉFÉRENCES', 'ANNEXES', 'Dupont, J. (2018). Titre. Revue.'),
    ('Resumen', 'Introducción', 'Referencias bibliográficas', 'Apéndice A', 'García, L. (2020). Título. Revista.'),
    ('Riassunto', 'Introduzione', 'Bibliografia', 'Appendice', 'Rossi, M. (2017). Titolo. Rivista.'),
    ('Resumo', 'Introdução', 'Referências', 'Anexo A', 'Silva, P. (2021). Título. Revista.'),
    ('Аннотация', 'Введение', 'Список литературы', 'Приложение А', 'Иванов И.И. Название // Журнал. 2020. Т. 5.'),
])
def test_headings_in_other_languages(ab, intro, bib, app, ref):
    assert rank.abstract(f'Title\n{ab}\n' + 'word ' * 80 + f'\n{intro}\nbody\n')[0].startswith('word')
    refs = '\n'.join(f'{i}. {ref}' for i in range(1, 6))
    body, cut, _ = rank.clean('line text\n' * 400 + bib + '\n' + refs + '\n' + app + '\nappendix table\n')
    assert cut and ref not in body and 'appendix table' in body


def test_real_page_count_with_trailing_form_feed(project):
    from conftest import make_pdf
    for n in (1, 2, 3):
        p = project / f'pages{n}.pdf'
        make_pdf(p, [[f'page {i} text'] for i in range(1, n + 1)])
        assert len(rank.pdf_pages(p)) == n                      # no empty page after the last form feed


@needs(rank.TOK_PATH, 'rank.py --setup')
def test_last_page_label_with_real_tokenizer(project):
    from conftest import make_pdf
    p = project / 'two.pdf'
    make_pdf(p, [['first page words'] * 5, ['second page words'] * 5])
    wins, *_ = rank.windows(p, rank.tokenizer())
    assert wins[-1]['pages'] in ('p. 2', 'p. 1-2')


def test_pdftotext_failure_is_skipped_not_ranked(project, offline, monkeypatch):
    import subprocess
    monkeypatch.chdir(project)
    real = subprocess.run
    def fake(cmd, **kw):
        if cmd[0] == 'pdftotext' and 'Ocean2023' in cmd[-2]:
            return subprocess.CompletedProcess(cmd, 1, 'partial text ' * 200, 'Syntax Error: broken xref')
        return real(cmd, **kw)
    monkeypatch.setattr(rank.subprocess, 'run', fake)
    rank.main(['--out', str(project / 'runs/f'), '--provider', 'local'])
    run = json.load(open(project / 'runs/f_paper-lector_rank_run.json'))
    assert 'Ocean2023' not in run['corpus']['ids']
    assert 'broken xref' in run['corpus']['skipped'][0]['reason']


def test_empty_ids_file_is_refused(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    (project / 'ids.csv').write_text('paper\n')
    with pytest.raises(SystemExit, match='at least one row'):
        rank.main(['--out', str(project / 'runs/x'), '--ids', str(project / 'ids.csv')])
    assert offline.calls == []


def test_ids_with_sha256_catch_a_changed_file(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    rank.main(['--out', str(project / 'runs/a'), '--provider', 'local'])
    files = json.load(open(project / 'runs/a_paper-lector_rank_run.json'))['corpus']['files']
    (project / 'ids.csv').write_text('paper,sha256\n' + ''.join(f"{f['id']},{f['sha256']}\n" for f in files))
    rank.main(['--out', str(project / 'runs/b'), '--provider', 'local', '--ids', str(project / 'ids.csv')])
    from conftest import make_pdf
    make_pdf(project / 'papers/topic/Ocean2023.pdf', [['a different paper now'] * 40])
    with pytest.raises(SystemExit, match='SHA-256 differs'):
        rank.main(['--out', str(project / 'runs/c'), '--provider', 'local', '--ids', str(project / 'ids.csv')])


def test_partial_outputs_and_lock_stop_a_second_run(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    (project / 'runs').mkdir()
    (project / 'runs/p_paper-lector_rank.csv').write_text('half written')          # crashed before _run.json
    with pytest.raises(SystemExit, match='already exists'):
        rank.main(['--out', str(project / 'runs/p')])
    assert (project / 'runs/p_paper-lector_rank.csv').read_text() == 'half written'
    (project / 'runs/q_paper-lector_rank_run.lock').write_text('')                        # a run in progress
    with pytest.raises(SystemExit, match='another run'):
        rank.main(['--out', str(project / 'runs/q')])
    rank.main(['--out', str(project / 'runs/r')])
    assert not (project / 'runs/r_paper-lector_rank_run.lock').exists()


def test_batches_respect_item_limit():
    parts = list(rank.batches(range(2001), lambda x: 1, 10**9))
    assert [len(p) for p in parts] == [1000, 1000, 1]


def test_estimate_covers_actual_usage(project, offline, monkeypatch, capsys):
    import re
    monkeypatch.chdir(project)
    rank.main(['--out', str(project / 'runs/e')])
    run = json.load(open(project / 'runs/e_paper-lector_rank_run.json'))
    assert run['usage']['embed'] + run['usage']['rerank'] <= run['estimate']


def test_formula_like_paper_id_is_escaped_in_csv(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    src = project / 'papers/topic/Ocean2023.pdf'
    src.rename(src.with_name('=1+1.pdf'))
    rank.main(['--out', str(project / 'runs/x'), '--provider', 'local'])
    rows = list(csv.DictReader(open(project / 'runs/x_paper-lector_rank-local.csv')))
    assert "'=1+1" in {r['paper'] for r in rows}
    rank.main(['--out', str(project / 'runs/y'), '--provider', 'local', '--ids', str(project / 'runs/x_paper-lector_rank-local.csv')])
    assert '=1+1' in json.load(open(project / 'runs/y_paper-lector_rank_run.json'))['corpus']['ids']      # the CSV works as --ids again


def test_id_that_really_starts_with_a_quote_is_kept(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    src = project / 'papers/topic/Ocean2023.pdf'
    src.rename(src.with_name("'=x.pdf"))
    (project / 'ids.csv').write_text("paper\n'=x\n")
    rank.main(['--out', str(project / 'runs/q'), '--provider', 'local', '--ids', str(project / 'ids.csv')])
    assert json.load(open(project / 'runs/q_paper-lector_rank_run.json'))['corpus']['ids'] == ["'=x"]


def test_cache_paths_carry_the_pinned_revision():
    assert rank.TOK_REV[:7] in rank.TOK_PATH.name and rank.LOCAL_DIR.name == rank.LOCAL_REV[:7]


def test_local_model_download_fails_cleanly(monkeypatch, tmp_path):
    import urllib.request
    monkeypatch.setattr(rank, 'LOCAL_DIR', tmp_path / 'm')
    monkeypatch.setattr(urllib.request, 'urlopen', cut_download)
    with pytest.raises(SystemExit, match='531 MB.*rank.py --setup --provider local'):
        rank.local_model()
    assert list((tmp_path / 'm').iterdir()) == []                       # no half file left


def test_local_model_with_wrong_hash_is_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(rank, 'LOCAL_DIR', tmp_path)
    for f in rank.LOCAL_FILES:
        (tmp_path / f).write_text('{}')
    with pytest.raises(SystemExit, match='not the pinned local model'):
        rank.local_model()


@needs(rank.LOCAL_DIR / 'model.safetensors', 'rank.py --setup --provider local')
def test_real_local_model_vectors():
    V = rank.local_model()(['quantum switch scheduling', 'kuantum anahtarında zamanlama', 'seawater attenuation', ''])
    assert V.shape[0] == 4 and np.allclose(np.linalg.norm(V[:3], axis=1), 1) and not V[3].any()
    assert V[0] @ V[1] > V[0] @ V[2]                                     # multilingual: the Turkish phrase is closer
    assert rank.local_model()([]).shape == (0, V.shape[1])


def test_tokenizer_with_wrong_hash_is_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(rank, 'TOK_PATH', tmp_path / 'tok.json')
    (tmp_path / 'tok.json').write_text('{}')
    with pytest.raises(SystemExit, match='not the pinned tokenizer'):
        rank.tokenizer()


def test_run_record_has_files_and_versions(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    rank.main(['--out', str(project / 'runs/v'), '--provider', 'local'])
    run = json.load(open(project / 'runs/v_paper-lector_rank_run.json'))
    assert all(len(f['sha256']) == 64 for f in run['corpus']['files'])
    assert run['versions']['tokenizer_revision'] == rank.TOK_REV and run['versions']['pdftotext']


def search_file(project):
    recs = [
        {'doi': '10.1/q', 'title': 'LIFO for noisy memories', 'abstract': 'Requests wait in a buffer; LIFO serves the youngest pair.'},
        {'openalex': 'W1', 'title': 'Age based scheduling at a quantum switch', 'abstract': 'Which user receives a stored entangled pair at a switch.'},
        {'arxiv': '2205.06300', 'title': 'Seawater links', 'abstract': ''},
        {'doi': '10.9/paywalled', 'title': 'Switch memory scheduling for waiting users', 'year': 2025, 'venue': 'IEEE TQE',
         'authors': ['Ada Lovelace', 'Bo Li', 'Cy Young', 'Di Wu'], 'first_author': 'Ada Lovelace',
         'biblio': {'volume': '6', 'issue': '2', 'first_page': '10', 'last_page': '19'},
         'cited_by': 12, 'cited_pct': 93.7, 'cited_at': '2026-10-18',
         'abstract': 'Which user receives a stored entangled pair when requests wait at a quantum switch with memories.'},
        {'openalex': 'W7', 'title': 'No abstract here', 'year': 2024, 'first_author': 'Ed Ng', 'abstract': ''},
    ]
    path = project / 'search.jsonl'
    path.write_text(''.join(json.dumps(r) + '\n' for r in recs))
    (project / 'papers/topic/fetch_log.jsonl').write_text(
        json.dumps({'id': '10.48550/arxiv.2205.06300', 'status': 'OK', 'file': 'Ocean2023.pdf'}) + '\n'
        + json.dumps({'id': '10.9/paywalled', 'status': 'MANUAL', 'url': 'https://x.example'}) + '\n')
    return path


def test_abstracts_add_a_separate_order_with_abstract_only_papers(project, offline, monkeypatch, capsys):
    monkeypatch.chdir(project)
    rank.main(['--out', str(project / 'runs/a'), '--abstracts', str(search_file(project))])
    assert 'abstracts: 5 papers, 2 without a PDF, 3 of 3 PDFs matched' in capsys.readouterr().err
    rows = list(csv.DictReader(open(project / 'runs/a_paper-lector_rank.csv')))
    by = {r['paper']: r for r in rows}
    assert [r['source'] for r in rows] == ['full_text'] * 3 + ['abstract_only'] * 2     # PDFs first, then the rest
    assert list(rows[0])[:8] == ['fused_rank', 'abs_fused_rank', 'citation', 'link', 'cited_by', 'cited_pct', 'start_pages', 'paper']
    pay = by['Lovelace2025_SwitchMemorySchedulingWaitingUsers']
    assert pay['fused_rank'] == '' and pay['Q0_main_pages'] == '' and pay['start_pages'] == ''
    assert pay['abs_fused_rank'] == '1'                                    # best abstract, though it has no PDF
    assert pay['link'] == 'https://doi.org/10.9/paywalled'
    assert (pay['cited_by'], pay['cited_pct'], pay['cited_at']) == ('12', '93.7', '2026-10-18')
    assert by['queue2022']['cited_by'] == ''                              # record without the fields
    assert pay['citation'] == ('Ada Lovelace, Bo Li, Cy Young et al. (2025). Switch memory scheduling for waiting users. '
                               'IEEE TQE, 6(2), 10\u201319.')
    assert by['Ng2024_NoAbstractHere']['abs_fused_rank'] == '' and rows[-1]['paper'] == 'Ng2024_NoAbstractHere'
    assert by['Ng2024_NoAbstractHere']['link'] == 'https://openalex.org/W7'
    assert by['queue2022']['link'] == 'https://doi.org/10.1/q'
    full = [d for e, b in offline.calls if e == 'rerank' for d in b['documents'] if '\n\n[p.' in d]
    assert any(d.startswith('Abstract: Which user receives a stored entangled pair at a switch.') for d in full)
    assert by['queue2022']['abstract_from'] == 'search'                   # matched through the sources DOI
    assert by['Switch2024']['abstract_from'] == 'search'                  # matched through its title on page 1
    assert by['Ocean2023']['abstract_from'] == '' and by['Ocean2023']['abs_fused_rank'] == ''   # no abstract anywhere:
    assert by['Ocean2023']['fused_rank'] != ''                            # unranked on abstracts, ranked on full text
    assert by['Ocean2023']['citation'] == '(n.d.). Seawater links.' and by['Ocean2023']['link'] == 'https://arxiv.org/abs/2205.06300'
    ranks = sorted(int(r['abs_fused_rank']) for r in rows if r['abs_fused_rank'])
    assert len(ranks) == 3 and ranks[0] == 1                              # ties share a rank
    run = json.load(open(project / 'runs/a_paper-lector_rank_run.json'))
    assert run['abstracts']['abstract_only'] == ['Lovelace2025_SwitchMemorySchedulingWaitingUsers', 'Ng2024_NoAbstractHere']
    assert run['abstracts']['no_abstract'] == ['Ocean2023', 'Ng2024_NoAbstractHere']
    assert run['usage']['rerank'] <= run['estimate']
    rank.main(['--out', str(project / 'runs/a2'), '--ids', str(project / 'runs/a_paper-lector_rank.csv')])   # PDF rows only
    assert len(list(csv.DictReader(open(project / 'runs/a2_paper-lector_rank.csv')))) == 3


def test_abstracts_with_local_and_without_flag(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    rank.main(['--out', str(project / 'runs/b'), '--provider', 'local', '--abstracts', str(search_file(project))])
    assert offline.calls == []
    rows = list(csv.DictReader(open(project / 'runs/b_paper-lector_rank-local.csv')))
    assert {r['paper']: r['abs_fused_rank'] for r in rows}['Lovelace2025_SwitchMemorySchedulingWaitingUsers'] != ''
    rank.main(['--out', str(project / 'runs/c')])
    rows = list(csv.DictReader(open(project / 'runs/c_paper-lector_rank.csv')))
    assert all(r['source'] == 'full_text' for r in rows) and 'abs_fused_rank' not in rows[0]
    assert {r['paper']: r['link'] for r in rows} == {'queue2022': 'https://doi.org/10.1/q', 'Switch2024': '', 'Ocean2023': ''}


def test_queries_name_names_the_files_and_stays_with_the_question(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    monkeypatch.setattr(rank, 'stamp', lambda: '2026-10-17_2315')
    q = project / 'queries/queries.json'
    q.write_text(q.read_text().replace('{\n "question"', '{\n "name": "switch-scheduling",\n "question"'))
    rank.main(['--provider', 'local'])
    assert [p.name for p in (project / 'runs').glob('*.csv')] == ['2026-10-17_2315_switch-scheduling_rank-local.csv']
    assert json.loads(open(project / 'queries/questions.jsonl').readline())['name'] == 'switch-scheduling'
    q.write_text(q.read_text().replace('switch-scheduling', 'switch-queues'))       # renamed after a run: refused
    with pytest.raises(SystemExit, match='ranked before with a different question'):
        rank.main(['--provider', 'local', '--dry'])
    (project / 'queries/queries2.json').write_text(q.read_text())                          # same question, other name
    with pytest.raises(SystemExit, match='ranked before as "switch-scheduling"'):
        rank.main(['--provider', 'local', '--dry', '--queries', str(project / 'queries/queries2.json')])
    (project / 'queries/queries2.json').write_text(q.read_text().replace('switch-queues', 'switch-scheduling'))
    rank.main(['--provider', 'local', '--queries', str(project / 'queries/queries2.json')])  # revised queries, same name


@pytest.mark.parametrize('name', ['Switch', 'switch_scheduling', 'a' * 26, '-switch', 'switch--x', 7])
def test_bad_queries_name_is_refused(project, name):
    q = project / 'queries/queries.json'
    q.write_text(q.read_text().replace('{\n "question"', '{\n "name": ' + json.dumps(name) + ',\n "question"'))
    with pytest.raises(SystemExit, match='"name" must be lowercase'):
        rank.common.load_queries(q)


def test_numbered_body_paragraphs_are_not_a_bibliography():
    body = 'intro text\n' * 200
    paras = '[1] constrains the queue length\n[2] specifies the service order\n[3] defines the cutoff\nconclusion stays here\n'
    text, cut, _ = rank.clean(body + paras + 'more body\n' * 20)
    assert not cut and 'conclusion stays here' in text
    refs = '[1] A. Author, Title one, 2019.\n[2] B. Author, Title two, 2020.\n[3] C. Author, Title three, 2021.\n'
    text, cut, _ = rank.clean(body + 'conclusion stays here\n' + refs)
    assert cut and 'conclusion stays here' in text and 'Title one' not in text
    text, cut, _ = rank.clean(body + '1. A. Author, Title one, 2019.\n3. B. Author, Title two, 2020.\n4. C. Author, Title, 2021.\n')
    assert not cut                                                    # numbering out of order: not a list


def test_title_match_needs_order_and_no_rival():
    lead = rank.words('Routing in quantum networks with limited memory Ada Lovelace University').split()
    assert rank.title_cover(rank.words('Entanglement in quantum networks with memory'), lead) < 0.8
    lead = rank.words('A Quantum Router Architecture for High-Fidelity Entanglement Flows in Quantum Networks Yuan Lee').split()
    title = rank.words('A Quantum Router Architecture for High-Fidelity Entanglement Flows in Multi-User Quantum Networks')
    assert rank.title_cover(title, lead) >= 0.8
    assert rank.title_cover(rank.words(None), lead) == 0.0 and rank.words('Квантовые сети') == 'квантовые сети'


def test_abstract_matching_edge_cases(project, offline, monkeypatch):
    """A wrong title stays apart; a fetch log counts only for its own folder and file; a source outside the run and a
    record with no title do not crash."""
    monkeypatch.chdir(project)
    other = project / 'papers' / 'other'; other.mkdir()
    (other / 'Switch2024.pdf').write_bytes((project / 'papers/topic/Ocean2023.pdf').read_bytes() + b'\n% other copy\n')
    (other / 'fetch_log.jsonl').write_text(json.dumps({'id': '10.5/other', 'status': 'OK', 'file': 'Switch2024.pdf'}) + '\n')
    (project / 'sources.csv').write_text('key,pdf_path,doi\nqueue2022,papers/topic/Queue2022.pdf,10.1/q\ngone,papers/gone.pdf,10.7/gone\n')
    recs = [{'doi': '10.5/other', 'title': 'Another copy of seawater links', 'abstract': 'seawater copy', 'cited_by': 2},
            {'doi': '10.7/gone', 'title': 'The gone paper on switch queues', 'abstract': 'a paper whose PDF is not here'},
            {'openalex': 'W5', 'title': None, 'abstract': 'no title at all'},
            {'openalex': 'W6', 'title': 'Age based scheduling at a classical switch', 'abstract': 'similar title, other paper'},
            {'doi': '10.6/print', 'title': 'Another copy of seawater link', 'abstract': 'the printed version of the logged preprint',
             'cited_by': 40, 'cited_pct': 91.0, 'cited_at': '2026-10-18'},
            {'doi': '10.8/a', 'title': 'The gone paper on switch queues.', 'abstract': 'a second record of a paper with no PDF'}]
    (project / 's.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in recs))
    rank.main(['--out', str(project / 'runs/e'), '--abstracts', str(project / 's.jsonl')])
    by = {r['paper']: r for r in csv.DictReader(open(project / 'runs/e_paper-lector_rank.csv'))}
    path = {f['id']: f['path'] for f in json.load(open(project / 'runs/e_paper-lector_rank_run.json'))['corpus']['files']}
    mine = next(k for k, v in path.items() if '/other/' in v)
    twin = next(k for k, v in path.items() if v.endswith('topic/Switch2024.pdf'))
    assert by[mine]['citation'] == '(n.d.). Another copy of seawater links.'                 # the log in papers/other names that file
    assert by[twin]['citation'] == ''                                    # not the same-named file in papers/topic
    assert (by[mine]['cited_by'], by[mine]['cited_pct']) == ('40', '91.0')   # the printed version's citations
    only = {r['citation']: r['source'] for r in by.values() if r['source'] == 'abstract_only'}
    assert only == {'(n.d.). The gone paper on switch queues.': 'abstract_only', '(n.d.).': 'abstract_only',
                    '(n.d.). Age based scheduling at a classical switch.': 'abstract_only'}
    assert len(by) == 4 + 3                                              # each second version counted once


def test_ids_with_only_abstract_rows_is_refused(project, tmp_path):
    p = tmp_path / 'ids.csv'
    p.write_text('paper,source\nAnon_X,abstract_only\n')
    with pytest.raises(SystemExit, match='no paper with a PDF'):
        rank.read_ids(p)


def test_abstract_order_without_any_pdf(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    for f in (project / 'papers/topic').glob('*.pdf'):
        f.unlink()
    (project / 'sources.csv').write_text('key,pdf_path,doi\n')
    (project / 's.jsonl').write_text(json.dumps({'doi': '10.9/p', 'title': 'Switch memory scheduling', 'first_author': 'Ada Lovelace',
                                                 'year': 2025, 'abstract': 'Which user receives a stored pair.'}) + '\n')
    rank.main(['--out', str(project / 'runs/n'), '--abstracts', str(project / 's.jsonl')])
    rows = list(csv.DictReader(open(project / 'runs/n_paper-lector_rank.csv')))
    assert [(r['paper'], r['source'], r['abs_fused_rank']) for r in rows] == [('Lovelace2025_SwitchMemoryScheduling', 'abstract_only', '1')]
    assert not any(e == 'embeddings' for e, b in offline.calls)
    with pytest.raises(SystemExit, match='no PDFs'):
        rank.main(['--out', str(project / 'runs/n2')])                   # without --abstracts there is nothing to rank


def test_windows_leave_out_the_head_the_reranker_already_reads(project, monkeypatch):
    from conftest import make_pdf
    monkeypatch.setattr(rank, 'WIN', 60)
    monkeypatch.setattr(rank, 'STEP', 50)
    p = project / 'ab.pdf'
    make_pdf(p, [['Title words here', 'Abstract'] + ['abstractword sentence goes here and on'] * 10 + ['1. Introduction'] + ['intro text'] * 40])
    wins, head, _, has_ab, _ = rank.windows(p, WordTokenizer())
    assert has_ab and head.startswith('abstractword')
    assert not any('abstractword' in w['text'] for w in wins) and any('abstractword' in w['full']['text'] for w in wins)
    assert wins[0]['text'].startswith('Title words here')                 # title and authors stay
    monkeypatch.setattr(rank, 'HEAD', 20)
    q = project / 'noab.pdf'
    make_pdf(q, [[f'w{i}' for i in range(200)]])
    wins, head, _, has_ab, _ = rank.windows(q, WordTokenizer())
    assert not has_ab and head.split()[-1] == 'w19'
    assert wins[0]['text'].split()[0] == 'w20' and wins[0]['full']['text'].split()[0] == 'w0'


def test_search_abstract_as_head_gives_the_opening_back_to_the_windows(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    monkeypatch.setattr(rank, 'HEAD', 10)
    rank.main(['--out', str(project / 'runs/h'), '--abstracts', str(search_file(project))])
    docs = [d for e, b in offline.calls if e == 'rerank' for d in b['documents'] if '\n\n[p.' in d]
    body = lambda start: [d.split('\n\n[p.', 1)[1] for d in docs if d.startswith(start)]
    assert all('Age based scheduling' in d for d in body('Abstract: Which user receives'))   # search abstract is the head
    ocean = [d for d in docs if 'Underwater optical' in d.split('\n\n[p.', 1)[0]]
    assert ocean and all('Underwater optical' not in d.split('\n\n[p.', 1)[1] for d in ocean)  # opening is the head


def test_trimmed_window_overlap_and_pages_count_only_what_is_left(project, monkeypatch):
    from conftest import make_pdf
    wins = [{'spans': [(50, 60)]}, {'spans': [(50, 110)]}, {'spans': [(110, 160)]}]   # first: a window cut by the head
    assert rank.pick(wins, np.array([3, 2, 1])) == [0, 2]                 # the second holds all the first has left
    monkeypatch.setattr(rank, 'WIN', 60)
    monkeypatch.setattr(rank, 'STEP', 50)
    monkeypatch.setattr(rank, 'HEAD', 20)
    p = project / 'pages.pdf'
    make_pdf(p, [[f'a{i}' for i in range(20)], [' '.join(f'b{i}' for i in range(k, k + 10)) for k in range(0, 80, 10)]])
    wins, *_ = rank.windows(p, WordTokenizer())
    assert wins[0]['pages'] == 'p. 2' and wins[0]['full']['pages'] == 'p. 1-2'
    assert wins[0]['spans'] == [(20, 60)] and wins[1]['spans'] == [(50, 100)]


def test_too_long_rerank_pair_stops_before_any_call(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    monkeypatch.setattr(rank, 'RERANK_PAIR', 30)
    with pytest.raises(SystemExit, match='no API call made: rerank-3 takes at most 30 tokens'):
        rank.main(['--out', str(project / 'runs/long')])
    assert offline.calls == []


def test_cache_ties_each_vector_to_its_pdf_window_or_query(project, offline, monkeypatch, tmp_path):
    import sqlite3
    monkeypatch.chdir(project)
    rank.main(['--out', str(project / 'runs/t')])
    run = json.load(open(project / 'runs/t_paper-lector_rank_run.json'))
    db = sqlite3.connect(tmp_path / 'cache' / 'embeddings.sqlite')
    rows = db.execute('select key, kind, ref, part, pages, tokens from src').fetchall()
    docs = [r for r in rows if r[1] == 'document']
    assert len(docs) == run['corpus']['windows']
    assert {r[2] for r in docs} == {f['sha256'] for f in run['corpus']['files']}
    assert all(r[4].startswith('p.') and r[5] > 0 for r in docs)
    assert sorted(r[3] for r in rows if r[1] == 'query') == sorted(run['queries'])
    assert {r[2] for r in rows if r[1] == 'query'} == {run['queries_sha']}
    keys = {k for k, in db.execute('select key from emb')}
    assert {r[0] for r in rows} <= keys                                    # every src row has its vector
    rank.main(['--out', str(project / 'runs/t2')])                         # a rerun adds no rows
    assert db.execute('select count(*) from src').fetchone()[0] == len(rows)


def test_one_out_prefix_holds_one_queries_name(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    rank.main(['--out', str(project / 'runs/q'), '--provider', 'local'])
    q2 = project / 'queries/other.json'
    q2.write_text((project / 'queries/queries.json').read_text().replace('{\n "question": "Which', '{\n "name": "other",\n "question": "Whom'))
    with pytest.raises(SystemExit, match='already holds a run of "paper-lector"'):
        rank.main(['--out', str(project / 'runs/q'), '--provider', 'local', '--queries', str(q2)])
    rank.main(['--out', str(project / 'runs/q_2'), '--provider', 'local', '--queries', str(q2)])   # q_2 is not q
    rank.main(['--out', str(project / 'runs/q-[x]'), '--provider', 'local', '--queries', str(q2)])  # glob characters
    (project / 'runs/old_run.json').write_text('{}')                     # a run record from before the _rank names
    with pytest.raises(SystemExit, match='older paper-lector'):
        rank.main(['--out', str(project / 'runs/old'), '--provider', 'local'])


@pytest.mark.parametrize('search_abstract, kept', [
    ('A short summary that never names the measured detail.', True),         # different abstract: PDF text comes back
    ('pdfonlyclaim measured on the testbed ' * 10, False),                                         # covers the PDF abstract: still left out
])
def test_pdf_abstract_the_search_abstract_misses_goes_back_to_the_windows(project, offline, monkeypatch, search_abstract, kept):
    from conftest import make_pdf
    monkeypatch.chdir(project)
    make_pdf(project / 'papers/topic/Claim2025.pdf', [['Fidelity bounds for stored pairs', 'Abstract']
             + ['pdfonlyclaim measured on the testbed'] * 9 + ['1. Introduction'] + ['body text here'] * 60])
    recs = [{'doi': '10.4/c', 'title': 'Fidelity bounds for stored pairs', 'abstract': search_abstract}]
    (project / 's.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in recs))
    rank.main(['--out', str(project / 'runs/c'), '--abstracts', str(project / 's.jsonl')])
    head = 'Abstract: ' + search_abstract                                 # the search abstract is the head
    docs = [d.split('\n\n[p.', 1)[1] for e, b in offline.calls if e == 'rerank' for d in b['documents'] if d.startswith(head + '\n\n[p.')]
    assert docs
    assert any('measured on the testbed' in d for d in docs) == kept


def test_one_questions_log_per_project(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    base = (project / 'queries/queries.json').read_text()
    (project / 'old').mkdir()
    moved = project / 'old/q.json'
    moved.write_text(base)
    rank.main(['--out', str(project / 'runs/a'), '--provider', 'local', '--queries', 'old/q.json'])
    log = [json.loads(l) for l in open(project / 'queries/questions.jsonl')]           # the project's one log
    assert log[-1]['queries'] == '../old/q.json' and not (project / 'old/questions.jsonl').exists()
    other = project / 'queries/renamed.json'                                   # same question, other name, other folder
    other.write_text(base.replace('{\n "question"', '{\n "name": "renamed",\n "question"'))
    with pytest.raises(SystemExit, match='ranked before as "paper-lector"'):
        rank.main(['--out', str(project / 'runs/b'), '--provider', 'local', '--queries', str(other)])
    moved.write_text(base.replace('"question"', '"fuse": ["Q0", "Q3"], "question"'))
    monkeypatch.chdir(project / 'papers')                                      # another folder, a relative path
    with pytest.raises(SystemExit, match='ranked before with a different question'):
        rank.main(['--out', str(project / 'runs/c'), '--provider', 'local', '--queries', '../old/q.json',
                   '--config', str(project / 'literature.json')])


def test_older_log_beside_the_queries_file_still_counts(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    (project / 'literature').mkdir()
    q = project / 'literature/queries.json'
    q.write_text((project / 'queries/queries.json').read_text())
    (project / 'literature/questions.jsonl').write_text(json.dumps({'queries': 'queries.json', 'queries_sha': 'older',
                                                                     'question': 'x'}) + '\n')
    with pytest.raises(SystemExit, match='ranked before with a different question'):
        rank.main(['--out', str(project / 'runs/l'), '--provider', 'local', '--queries', str(q)])


def test_start_pages_votes_once_per_query_skips_overlaps_and_breaks_ties_by_page():
    assert rank.unique_pages('p. 7-8; p. 4-5; p. 7-8') == 'p. 7-8; p. 4-5' and rank.unique_pages('') == ''
    # p. 7-8 twice in one cell counts once; p. 4-5 is in two cells, so it leads
    assert rank.start_pages(['p. 7-8; p. 4-5; p. 7-8', 'p. 4-5; p. 10']) == 'p. 4-5; p. 7-8; p. 10'
    # inclusive overlap: p. 5-6 touches p. 4-5 and is skipped, scanning goes on; ranges are never widened
    assert rank.start_pages(['p. 4-5; p. 5-6', 'p. 4-5; p. 12; p. 1']) == 'p. 4-5; p. 1; p. 12'
    # equal counts ordered by page number, not as strings (p. 9 before p. 10); at most k
    assert rank.start_pages(['p. 10; p. 9; p. 2-3; p. 20']) == 'p. 2-3; p. 9; p. 10'
    assert rank.start_pages(['p. 3']) == 'p. 3' and rank.start_pages(['', None]) == ''


FILLER = ' '.join(f'sentence{i} about networks and scheduling of requests.' for i in range(60))
REFS = lambda n: '\n'.join(f'[{i}] A. Author{i}, Title number {i}, Journal {i}, 20{i % 20:02d}.' for i in range(1, n + 1))


def test_bibliography_before_the_middle_is_cut_and_appendices_stay():
    text = 'Title\nAbstract\n' + FILLER * 3 + '\nReferences\n' + REFS(40) + '\nAppendix A: Proofs\n' + FILLER * 6
    assert text.index('References') < 0.5 * len(text)                 # a long appendix puts the list in the first half
    out, cut, _ = rank.clean(text)
    assert cut and 'Title number 7' not in out and 'Appendix A: Proofs' in out
    text = 'Title\n' + FILLER * 6 + '\nReferences\n' + REFS(30) + '\n\nA\n\nProof of Theorem 1\n\nWe restate Theorem 1. ' + FILLER * 2
    out, cut, _ = rank.clean(text)
    assert cut and 'Title number 7' not in out and 'We restate Theorem 1' in out      # lettered appendix, no heading word


def test_running_bibliography_header_and_chapter_bibliographies():
    entry = '[Aco+{i}] Name Surname{i}. "A title {i}". In: Journal {i} (2024), pp. 1-2.'
    pages = ''.join('\nBibliography\n' + '\n'.join(entry.format(i=10 * p + k) for k in range(8)) for p in range(6))
    out, cut, shifts = rank.clean(FILLER * 8 + pages + '\nBibliography\n[@Fit23] P. Fittipaldi. Simulator.\n')
    assert cut and 'A title 12' not in out and len(shifts) == 1       # one list, though every page repeats its header
    text = FILLER * 4 + '\nReferences\n' + REFS(20) + '\nChapter 2\nsecond chapter body. ' + FILLER * 4 + '\nReferences\n' + REFS(20)
    out, cut, shifts = rank.clean(text)
    assert cut and 'second chapter body' in out and 'Title number 3' not in out and len(shifts) == 2
    for at, n in shifts:                                               # positions map back to the original text
        assert out[at:at + 20] == text[at + sum(k for a, k in shifts if a < at) + n:][:20]


def test_misplaced_heading_starts_the_cut_at_the_first_entry():
    gap = 'The success probability of the strategy is given by a closed form expression. ' * 25
    text = FILLER * 6 + '\nR EFERENCES\n' + gap + '\n' + REFS(30) + '\n'
    out, cut, _ = rank.clean(text)
    assert cut and gap.strip() in out and 'Title number 1,' not in out


def test_numbered_dated_body_is_not_a_bibliography():
    lead = 'Introduction and method.\n' * 100
    events = ('Milestones:\n1. Prototype deployed in 2019 with passive sensing.\n2. Network expanded in 2020 to relay '
              'nodes.\n3. Scheduler redesigned in 2021 for active sensing.\nConclusion\nOur main result stays.\n')
    out, cut, _ = rank.clean(lead + events)
    assert not cut and 'Our main result stays.' in out
    refs = '\n'.join(f'{i}. Wehner S, Elkouss D ({2000 + i}) Quantum internet part {i}. Science {i}.' for i in range(1, 6))
    out, cut, _ = rank.clean(lead + 'conclusion stays\n' + refs)            # "Surname AB," authors, no heading
    assert cut and 'conclusion stays' in out and 'Wehner' not in out


def test_ligatures_match_plain_letters():
    assert rank.bm25_scores(['puriﬁcation raises ﬁdelity', 'unrelated text'], 'purification fidelity')[0] > 0
    lead = rank.words('Efﬁcient puriﬁcation for high ﬁdelity entanglement distribution J. Doe').split()
    assert rank.title_cover(rank.words('Efficient purification for high fidelity entanglement distribution'), lead) == 1.0


def test_short_abstract_and_the_word_introduction_inside_one():
    short = 'We study scheduling of stored entangled pairs. Our policy reduces waiting time under noisy quantum memories.'
    text = 'T\nAbstract\n' + short + '\n1. Introduction\nbody'
    assert rank.abstract(text) == (short, (11, 11 + len(short) + 1))    # 113 characters, under the old 300 minimum
    ab = 'We study ' + 'quantum memories ' * 12 + 'since the introduction of cutoffs, a threshold policy is optimal. END.'
    assert rank.abstract('T\nAbstract\n' + ab + '\n1. Introduction\nbody')[0].endswith('END.')


def test_watermark_only_scan_is_skipped(project, offline, monkeypatch, capsys):
    from conftest import make_pdf
    make_pdf(project / 'papers/topic/Scan1970.pdf', [['Downloaded from IEEE Xplore. Restrictions apply.', f'{i}'] for i in range(5)])
    assert rank.windows(project / 'papers/topic/Scan1970.pdf', WordTokenizer())[0] == []
    monkeypatch.chdir(project)
    rank.main(['--out', str(project / 'runs/w')])
    run = json.load(open(project / 'runs/w_paper-lector_rank_run.json'))
    assert [x['id'] for x in run['corpus']['skipped']] == ['Scan1970']


def test_uppercase_extension_missing_source_and_download_dir(project, offline, monkeypatch, capsys):
    from conftest import make_pdf
    make_pdf(project / 'papers/topic/Upper.PDF', [['Upper case title', 'Abstract', 'stored pairs ' * 30]])
    known = {'gone': {'pdf': project / 'nowhere.pdf', 'doi': '10.1/g'}}
    assert 'Upper' in rank.find_pdfs([project / 'papers'], known)
    assert 'sources key gone' in capsys.readouterr().err
    cfg = json.loads((project / 'literature.json').read_text())
    (project / 'literature.json').write_text(json.dumps(dict(cfg, download_dir='downloads')))
    (project / 'downloads').mkdir()
    make_pdf(project / 'downloads/New2026.pdf', [['New result', 'Abstract', 'stored pairs ' * 30]])
    monkeypatch.chdir(project)
    rank.main(['--out', str(project / 'runs/d')])
    assert 'outside pdf_dirs; ranked too' in capsys.readouterr().err
    assert 'New2026' in json.load(open(project / 'runs/d_paper-lector_rank_run.json'))['corpus']['ids']


def test_versions_parts_and_retitled_records(tmp_path):
    w = rank.words
    assert not rank.same_title(w('Optimal policies in repeater chains with cutoffs: Part I'), w('Optimal policies in repeater chains with cutoffs: Part II'))
    ab = 'We schedule entanglement purification and route flows under fidelity constraints in quantum networks.'
    pre = {'doi': '10.48550/arxiv.2408.08243', 'title': 'From Entanglement Purification Scheduling to Fidelity-constrained Multi-Flow Routing',
           'first_author': 'Ziyue Jia', 'year': 2024, 'abstract': ab}
    pub = dict(pre, doi='10.1109/icnp.1', title='From Entanglement Purification Scheduling to Fidelity-Constrained Entanglement Routing')
    assert rank.retitled(pre, pub) and not rank.retitled(pre, dict(pub, first_author='Other Person'))
    assert not rank.retitled(pre, dict(pub, abstract='A different study of satellite links and optical ground stations.'))
    s = tmp_path / 's.jsonl'
    s.write_text(''.join(json.dumps(r) + '\n' for r in [pre, pub]))
    assert len(rank.abstract_corpus([s], [], [], None, [])) == 1


def test_repeated_record_fills_the_missing_abstract(tmp_path):
    s = tmp_path / 's.jsonl'
    s.write_text(json.dumps({'openalex': 'W1', 'title': 'Quantum scheduling methods', 'abstract': ''}) + '\n'
                 + json.dumps({'openalex': 'W1', 'doi': '10.1/a', 'title': 'Other', 'abstract': 'The abstract.'}) + '\n')
    a = rank.abstract_corpus([s], [], [], None, [])
    assert len(a) == 1 and a[0]['text'] == 'The abstract.' and a[0]['title'] == 'Quantum scheduling methods'


def test_record_naming_two_pdfs_goes_to_its_doi_and_logged_copy_found_by_sha(project, capsys):
    (project / 'sources.csv').write_text('key,pdf_path,doi\npre,,10.48550/arxiv.2205.06300\nprint,,10.1/published\n')
    cfg = rank.common.load_config(start=project)
    P = [{'id': k, 'path': str(project / f'{k}.pdf'), 'sha256': k, 'head': '', 'abstract_found': False, 'wins': [i]}
         for i, k in enumerate(['pre', 'print'])]
    W = [{'full': {'text': 'unrelated opening'}}] * 2
    s = project / 's.jsonl'
    s.write_text(json.dumps({'doi': '10.1/published', 'arxiv': '2205.06300', 'title': 'Q', 'abstract': 'Shared.'}) + '\n')
    A = {x['id']: x for x in rank.abstract_corpus([s], P, W, cfg, [])}
    assert A['print']['text'] == 'Shared.' and A['pre']['text'] == '' and 'two versions' in capsys.readouterr().err
    (project / 'sources.csv').write_text('key,pdf_path,doi\n')
    (project / 'papers/new').mkdir()
    (project / 'papers/new/fetch_log.jsonl').write_text(json.dumps({'id': '10.1/published', 'status': 'HAVE',
                                                                   'file': 'gone.pdf', 'sha256': 'print'}) + '\n')
    A = {x['id']: x for x in rank.abstract_corpus([s], P, W, rank.common.load_config(start=project), [project / 'papers'])}
    assert A['print']['text'] == 'Shared.'                            # the log's file is gone; its SHA-256 still ties it


def test_embeddings_follow_the_response_index_and_refuse_zero_vectors(offline, monkeypatch):
    from collections import Counter
    monkeypatch.setattr(rank, 'call', lambda ep, b, n: {'data': [{'index': 1, 'embedding': [0., 1.]}, {'index': 0, 'embedding': [1., 0.]}],
                                                    'usage': {'total_tokens': 2}})
    got = rank.embed([('alpha', 1), ('beta', 1)], 'document', Counter(), [('s', 0, 'p. 1'), ('s', 1, 'p. 1')])
    assert np.array_equal(got, np.eye(2))
    monkeypatch.setattr(rank, 'call', lambda ep, b, n: {'data': [{'index': 0, 'embedding': [0., 0.]}], 'usage': {'total_tokens': 1}})
    with pytest.raises(SystemExit, match='zero'):
        rank.embed([('gamma', 1)], 'document', Counter(), [('s', 2, 'p. 1')])


def test_every_text_cell_is_escaped_and_escapes_never_collide(project, offline, monkeypatch):
    from conftest import make_pdf
    assert rank.cell('=x') != rank.cell("'=x") and rank.cell("'x") == "''x"
    make_pdf(project / 'papers/topic/=formula.pdf', [['first distinct body ' * 10]])
    make_pdf(project / "papers/topic/'=formula.pdf", [['second distinct body ' * 10]])
    s = project / 's.jsonl'
    s.write_text(json.dumps({'doi': '10.1/q', 'title': 'LIFO', 'authors': ['=HYPERLINK("x")'], 'abstract': 'A.'}) + '\n')
    monkeypatch.chdir(project)
    rank.main(['--out', str(project / 'runs/c'), '--abstracts', str(s)])
    rows = list(csv.DictReader(open(project / 'runs/c_paper-lector_rank.csv')))
    assert len({r['paper'] for r in rows}) == len(rows)
    assert all(not v or v[0] not in '=+-@' for r in rows for v in r.values())
    rank.main(['--out', str(project / 'runs/c2'), '--ids', str(project / 'runs/c_paper-lector_rank.csv')])   # reads back


def test_expect_with_no_full_text_paper(project, offline, monkeypatch, capsys):
    monkeypatch.chdir(project)
    (project / 'empty').mkdir()
    (project / 'sources.csv').write_text('key,pdf_path,doi\n')
    s = project / 's.jsonl'
    s.write_text(json.dumps({'openalex': 'W1', 'title': 'No PDF', 'abstract': 'A quantum switch study.'}) + '\n')
    rank.main(['--out', str(project / 'runs/e'), '--dirs', str(project / 'empty'), '--abstracts', str(s), '--expect', 'x'])
    assert 'sanity check skipped' in capsys.readouterr().out and (project / 'runs/e_paper-lector_rank_run.json').exists()


def test_page_labels_after_a_mid_text_cut(project, offline):
    from conftest import make_pdf
    p = project / 'chapters.pdf'
    make_pdf(p, [['chapter one body'] * 30, ['References'] + REFS(20).split('\n'), ['chapter two body'] * 30])
    wins, *_ = rank.windows(p, WordTokenizer())
    assert any('two' in w['text'] and w['pages'] == 'p. 3' for w in wins)
    assert not any('Title number' in w['text'] for w in wins)


def test_author_year_bibliography_is_cut_and_its_cited_appendix_stays():
    refs = '\n'.join(f'Name{i} Surname, Other Author, and Third Person. 20{i % 20:02d}. A title about topic {i}. In '
                     f'Proceedings of the Annual Meeting, pages {i}-{i + 9}.' for i in range(1, 40))
    appendix = 'We follow the set-up of (Karpukhin et al., 2020) and use Adam (Kingma and Ba, 2014), as Galley et al. (2018) did. ' * 30
    out, cut, _ = rank.clean(FILLER * 6 + '\nReferences\n' + refs + '\n' + appendix)
    assert cut and 'topic 7.' not in out and appendix.strip() in out   # ACL style; in-text citation years are no list


def test_abstract_heading_forms_and_ends():
    ab = 'We study ' + 'stored pairs at a switch ' * 10
    assert rank.abstract('Title\nA BSTRACT\n' + ab + '\n1 I NTRODUCTION\nbody')[0].startswith('We study')    # ICLR
    assert rank.abstract('Here we abstract the network as a graph ' + ab + '\n1. Introduction\nbody')[0] is None
    assert rank.abstract('see ieeexplore.ieee.org/abstract/document/1 ' + ab + '\nI. INTRODUCTION\nbody')[0] is None
    got = rank.abstract('T\nAbstract—' + ab + '\nIndex Terms—quantum networks, scheduling\nI. INTRODUCTION\nbody')[0]
    assert got.endswith('switch') and 'Index' not in got
    long = 'We study ' + 'stored pairs at a quantum switch with memories. ' * 70                     # about 3,400 characters
    assert rank.abstract('T\nAbstract\n' + long + '\n1. Introduction\nbody')[0] is not None


def test_entries_printed_above_the_heading_are_cut_too():
    above = '\n'.join(f'[{i}] A. Author{i}, Leaked title {i}, Journal {i}, 20{i % 20:02d}.' for i in range(18, 30))
    out, cut, _ = rank.clean(FILLER * 6 + '\nconclusion stays here.\n' + above + '\nReferences\n' + REFS(17) + '\n')
    assert cut and 'conclusion stays here.' in out and 'Leaked title' not in out and 'Title number 3' not in out


def test_body_between_heading_and_first_entry_stays_and_algorithm_lines_are_no_entry():
    gap = 'CONCLUSION\nOur top down inventory of design requirements stays in the text.\n' + 'x' * 400 + '\n'
    out, cut, _ = rank.clean(FILLER * 6 + '\nReferences\n' + gap + REFS(40) + '\n')
    assert cut and 'Our top down inventory' in out and 'Title number 3' not in out
    algo = '\n'.join(f'{i}.\nfor each request r do update the queue' for i in range(1, 6))
    nature = '\n'.join(f'Author{i}, B. Title number {i}. Nature {i}, 1-2 (20{i % 20:02d}).' for i in range(1, 40))
    out, cut, _ = rank.clean(FILLER * 6 + '\nReferences\n' + 'Theorem 1 holds. ' * 120 + '\n' + algo + '\n' + nature)
    assert cut and 'for each request r do' in out and 'Title number 3.' not in out


def test_lettered_appendix_and_bibliography_styles():
    acl = '\n'.join(f'Name{i} Surname and Other Person. 20{i % 20:02d}. A title about topic {i}. In Proceedings, '
                    f'pages {i}-{i + 9}.' for i in range(1, 40))
    appendix = '\n\nA\n\nModels Set-Up\n\nWe train with Adam as in Sennrich et al.\n(2017) for 2048 steps. ' + FILLER
    out, cut, _ = rank.clean(FILLER * 6 + '\nReferences\n' + acl + appendix)
    assert cut and 'topic 7.' not in out and 'Models Set-Up' in out and 'We train with Adam' in out
    apa = '\n'.join(f'Smith{i} ({2000 + i % 20}). A title {i}. Journal of Things, {i}, 1-9.' for i in range(1, 40))
    out, cut, _ = rank.clean(FILLER * 6 + '\nReferences\n' + apa + '\n')
    assert cut and 'A title 7.' not in out                            # "Surname (2020)." is an entry, not a citation
    plain = '\n'.join(f'{i} L. K. Grover{i}, Phys. Rev. Lett. {i}, 325 (19{90 + i % 9}).' for i in range(1, 30))
    out, cut, _ = rank.clean(FILLER * 6 + '\n' + plain + '\n')
    assert cut and 'Grover7' not in out                               # no heading, no bracket or period
    alpha = '\n'.join(f'[Aco+{i:02d}] Name Surname. "A title {i}". In: Journal (20{i % 20:02d}).' for i in range(1, 40))
    out, cut, _ = rank.clean(FILLER * 6 + '\nBibliography\n' + alpha + '\n')
    assert cut and 'A title 7"' not in out


def test_a_list_numbered_on_after_an_appendix_page_is_cut_again():
    first = '\n'.join(f'[{i}] A. Author{i}, Title number {i}, Journal, 20{i % 20:02d}.' for i in range(1, 56))
    rest = '\n'.join(f'[{i}] A. Author{i}, Title number {i}, Journal, 20{i % 20:02d}.' for i in range(56, 73))
    out, cut, shifts = rank.clean(FILLER * 6 + '\nReferences\n' + first + '\nAppendix A\nproof text. ' + FILLER + '\n' + rest + '\n')
    assert cut and len(shifts) == 2 and 'proof text' in out and 'Title number 60' not in out


def test_two_pages_of_the_same_text_are_no_scan(tmp_path):
    from conftest import make_pdf
    make_pdf(tmp_path / 'Twice.pdf', [['The same substantive text about scheduling.', f'{i}'] for i in (1, 2)])
    assert rank.windows(tmp_path / 'Twice.pdf', WordTokenizer())[0]


def test_quote_prefixed_ids_read_back_to_their_own_pdf(project, offline, monkeypatch):
    from conftest import make_pdf
    make_pdf(project / "papers/topic/'paper.pdf", [['first body ' * 10]])
    make_pdf(project / "papers/topic/''paper.pdf", [['second body ' * 10]])
    monkeypatch.chdir(project)
    rank.main(['--out', str(project / 'runs/q')])
    rank.main(['--out', str(project / 'runs/q2'), '--ids', str(project / 'runs/q_paper-lector_rank.csv')])
    run = json.load(open(project / 'runs/q2_paper-lector_rank_run.json'))
    assert {f['id']: f['path'].rsplit('/', 1)[1] for f in run['corpus']['files'] if 'paper' in f['id']} == \
        {"'paper": "'paper.pdf", "''paper": "''paper.pdf"}


def test_merged_record_keeps_doi_first_and_full_author_names(project, tmp_path):
    (project / 'sources.csv').write_text('key,pdf_path,doi\npre,,10.48550/arxiv.2205.06300\nprint,,10.1/published\n')
    cfg = rank.common.load_config(start=project)
    P = [{'id': k, 'path': str(project / f'{k}.pdf'), 'sha256': k, 'head': '', 'abstract_found': False, 'wins': [i]}
         for i, k in enumerate(['pre', 'print'])]
    s = tmp_path / 's.jsonl'
    s.write_text(json.dumps({'arxiv': '2205.06300', 'title': 'Q', 'abstract': ''}) + '\n'
                 + json.dumps({'arxiv': '2205.06300', 'doi': '10.1/published', 'title': 'Q', 'abstract': 'Shared.'}) + '\n')
    A = {x['id']: x for x in rank.abstract_corpus([s], P, [{'full': {'text': 'x'}}] * 2, cfg, [])}
    assert A['print']['text'] == 'Shared.' and A['pre']['text'] == ''
    ab = 'We schedule entanglement purification and route flows under fidelity constraints in quantum networks.'
    a = {'title': 'Efficient scheduling of entangled pairs in quantum switch networks', 'first_author': 'Alice Smith', 'year': 2024, 'abstract': ab}
    b = dict(a, title='Efficient routing of entangled pairs in quantum switch networks', first_author='Bob Smith')
    assert not rank.retitled(a, b) and rank.retitled(a, dict(b, first_author='Alice Smith'))


@needs(rank.TOK_PATH, 'rank.py --setup')
@needs(rank.LOCAL_DIR / 'model.safetensors', 'rank.py --setup --provider local')
def test_end_to_end_local_run_with_the_real_tokenizer_and_model(project, monkeypatch):
    """A first run as a new user makes it: real tokenizer, real local model, real pdftotext, no fakes."""
    monkeypatch.chdir(project)
    rank.main(['--provider', 'local'])
    run = next((project / 'runs').glob('*_paper-lector_rank_run.json'))
    rows = list(csv.DictReader(open(next((project / 'runs').glob('*_rank-local.csv')), encoding='utf-8')))
    assert sorted(r['paper'] for r in rows) == ['Ocean2023', 'Switch2024', 'queue2022']
    ranks = {r['paper']: int(r['fused_rank']) for r in rows}
    assert ranks['Switch2024'] == 1                           # the quantum switch paper leads a quantum switch question
    assert json.loads(run.read_text())['models']['provider'] == 'local'
