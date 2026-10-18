"""Failure paths: a full disk, bad API answers, retries against the budget, broken input files, no hard links."""
import errno, io, json, os, subprocess, urllib.error

import pytest

import common
import fetch_pdf
import openalex_search
import rank
from conftest import FakeVoyage, WordTokenizer, local_vecs


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


def full_disk(*a, **k):
    raise OSError(errno.ENOSPC, 'No space left on device')


def leftovers(project):
    runs = project / 'runs'
    return sorted(p.name for p in runs.iterdir()) if runs.is_dir() else []


@pytest.mark.parametrize('answer', [
    lambda docs: [{'index': i, 'relevance_score': float('nan')} for i in range(len(docs))],
    lambda docs: [{'index': 0, 'relevance_score': 0.5}],                                  # documents missing
    lambda docs: [{'index': 0, 'relevance_score': 0.5} for _ in docs],                     # one index repeated
    lambda docs: [{'index': i, 'relevance_score': '0.5'} for i in range(len(docs))],
])
def test_invalid_rerank_answer_stops_the_run_and_writes_nothing(project, offline, monkeypatch, answer):
    monkeypatch.chdir(project)
    real = offline.__call__

    def bad(ep, body, n=None):
        r = real(ep, body, n)
        if ep == 'rerank':
            r['data'] = answer(body['documents'])
        return r
    monkeypatch.setattr(rank, 'call', bad)
    with pytest.raises(SystemExit, match='invalid rerank answer'):
        rank.main(['--out', str(project / 'runs/r')])
    assert leftovers(project) == []
    assert not (project / 'queries/questions.jsonl').exists()


def test_full_disk_while_writing_outputs_leaves_no_partial_run(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    real, calls = common.write_new, []

    def second_fails(path, data):                    # the CSV goes in, the run record hits a full disk
        calls.append(path)
        if len(calls) == 2:
            full_disk()
        return real(path, data)
    monkeypatch.setattr(common, 'write_new', second_fails)
    with pytest.raises(SystemExit, match='nothing of this run was kept'):
        rank.main(['--out', str(project / 'runs/r')])
    assert len(calls) == 2 and leftovers(project) == []                 # no CSV, no record, no lock
    assert not (project / 'queries/questions.jsonl').exists()
    monkeypatch.setattr(common, 'write_new', real)
    rank.main(['--out', str(project / 'runs/r')])                       # the same --out works afterwards
    assert (project / 'runs/r_paper-lector_rank_run.json').is_file()


class HalfThenFull:
    """os.write as on a disk that fills up mid-line: the first call writes half, every later one fails."""
    def __init__(self):
        self.real, self.calls = os.write, 0

    def __call__(self, fd, data):
        self.calls += 1
        if self.calls == 1:
            return self.real(fd, data[:len(data) // 2])
        full_disk()


def test_full_disk_on_the_questions_log_removes_the_outputs(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    log = project / 'queries/questions.jsonl'
    log.write_text('{"earlier": 1}\n')
    real = common.append_line

    def append(path, line):                          # only the log's write meets the full disk
        common.os.write = HalfThenFull()
        try:
            real(path, line)
        finally:
            common.os.write = common.os.write.real
    monkeypatch.setattr(common, 'append_line', append)
    with pytest.raises(SystemExit, match='outputs were removed again'):
        rank.main(['--out', str(project / 'runs/r')])
    assert log.read_text() == '{"earlier": 1}\n' and leftovers(project) == []


def test_append_line_cuts_a_half_written_line_back(tmp_path, monkeypatch):
    f = tmp_path / 'fetch_log.jsonl'
    f.write_text('{"id": "a"}\n')
    monkeypatch.setattr(common.os, 'write', HalfThenFull())
    with pytest.raises(OSError):
        common.append_line(f, '{"id": "10.1/long-enough-to-be-cut"}')
    monkeypatch.undo()
    assert f.read_text() == '{"id": "a"}\n'
    common.append_line(f, '{"id": "b"}')
    assert f.read_text() == '{"id": "a"}\n{"id": "b"}\n'


def test_retries_count_against_the_budget(monkeypatch):
    sent = []
    monkeypatch.setattr(rank, 'KEY', 'k')
    monkeypatch.setattr(rank, 'SENT', 0)
    monkeypatch.setattr(rank, 'BUDGET', 100)
    monkeypatch.setattr(common.time, 'sleep', lambda s: None)
    monkeypatch.setattr(rank.urllib.request, 'urlopen', lambda *a, **k: sent.append(1) or full_timeout())
    with pytest.raises(SystemExit, match='above --budget 100'):
        rank.call('rerank', {}, 40)
    assert len(sent) == 2 and rank.SENT == 80        # a third attempt would have sent 120 tokens


def full_timeout():
    raise TimeoutError('timed out')


def test_voyage_errors_stop_with_a_message(monkeypatch):
    monkeypatch.setattr(rank, 'KEY', 'k')
    monkeypatch.setattr(rank, 'SENT', 0)
    monkeypatch.setattr(rank, 'BUDGET', 10**9)
    monkeypatch.setattr(common.time, 'sleep', lambda s: None)
    err = urllib.error.HTTPError('u', 401, 'Unauthorized', {}, io.BytesIO(b'{"detail": "bad key"}'))
    monkeypatch.setattr(rank.urllib.request, 'urlopen', lambda *a, **k: (_ for _ in ()).throw(err))
    with pytest.raises(SystemExit, match='VOYAGE_API_KEY is wrong'):
        rank.call('embeddings', {}, 1)
    err = urllib.error.HTTPError('u', 400, 'Bad', {}, io.BytesIO(b'{"detail": "input too long"}'))
    monkeypatch.setattr(rank.urllib.request, 'urlopen', lambda *a, **k: (_ for _ in ()).throw(err))
    with pytest.raises(SystemExit, match='HTTP 400 on embeddings: input too long'):
        rank.call('embeddings', {}, 1)
    monkeypatch.setattr(rank.urllib.request, 'urlopen', lambda *a, **k: (_ for _ in ()).throw(urllib.error.URLError('dns')))
    with pytest.raises(SystemExit, match='cannot get an answer from api.voyageai.com'):
        rank.call('embeddings', {}, 1)


def test_write_new_without_hard_links_and_on_a_full_disk(tmp_path, monkeypatch):
    out = tmp_path / 'a.pdf'
    monkeypatch.setattr(common.os, 'link', lambda *a: (_ for _ in ()).throw(PermissionError(1, 'not supported')))
    assert common.write_new(out, b'%PDF one') and out.read_bytes() == b'%PDF one'
    assert common.write_new(out, b'%PDF two') is False and out.read_bytes() == b'%PDF one'
    monkeypatch.setattr(type(out), 'write_bytes', full_disk)
    with pytest.raises(OSError):
        common.write_new(tmp_path / 'b.pdf', b'%PDF')
    assert sorted(p.name for p in tmp_path.iterdir()) == ['a.pdf']


def test_fetch_on_a_full_disk_keeps_no_pdf_without_its_log_line(project, monkeypatch, capsys):
    monkeypatch.chdir(project)
    monkeypatch.setenv('OPENALEX_API_KEY', 'test')
    monkeypatch.setattr(fetch_pdf, 'openalex', lambda i: {'doi': 'https://doi.org/' + i, 'display_name': 'New paper',
                                                          'best_oa_location': {'pdf_url': 'http://oa/' + i}, 'locations': []})
    monkeypatch.setattr(fetch_pdf, 'fetch', lambda url: b'%PDF-1.4 ' + url.encode())
    real = fetch_pdf.log_line
    monkeypatch.setattr(fetch_pdf, 'log_line', full_disk)
    with pytest.raises(SystemExit, match='removed again'):
        fetch_pdf.main(['10.9/a'])
    assert not list((project / 'papers/new').glob('*.pdf'))
    monkeypatch.setattr(fetch_pdf, 'log_line', real)
    monkeypatch.setattr(common, 'write_new', full_disk)
    with pytest.raises(SystemExit, match='cannot save'):
        fetch_pdf.main(['10.9/a'])
    assert not list((project / 'papers/new').glob('*'))


def test_search_on_a_full_disk_keeps_nothing(project, monkeypatch, tmp_path):
    monkeypatch.chdir(project)
    monkeypatch.setenv('OPENALEX_API_KEY', 'test')
    monkeypatch.setattr(openalex_search.common, 'openalex_json',
                        lambda *a, **k: {'results': [], 'meta': {'count': 0, 'next_cursor': None}})
    monkeypatch.setattr(openalex_search, 'replace', full_disk)
    with pytest.raises(SystemExit, match='nothing kept'):
        openalex_search.main(['--exact', 'x', '--out', str(tmp_path / 'f.jsonl')])
    assert not list(tmp_path.glob('f*'))
    real_open = open
    monkeypatch.setattr('builtins.open', lambda p, m='r', *a, **k: full_disk() if str(p).endswith('.query.json')
                        else real_open(p, m, *a, **k))
    with pytest.raises(SystemExit, match='cannot create'):
        openalex_search.main(['--exact', 'x', '--out', str(tmp_path / 'g.jsonl')])
    monkeypatch.setattr('builtins.open', real_open)
    assert not list(tmp_path.glob('g*'))


def test_openalex_key_refused_and_no_network(monkeypatch):
    monkeypatch.setattr(openalex_search, 'KEY', 'k')
    err = urllib.error.HTTPError('u', 403, 'Forbidden', {}, io.BytesIO(b''))
    monkeypatch.setattr(openalex_search.common, 'openalex_json', lambda *a, **k: (_ for _ in ()).throw(err))
    with pytest.raises(SystemExit, match='OPENALEX_API_KEY is wrong'):
        openalex_search.get('works', {})


@pytest.mark.parametrize('text', ['[]', 'null', '"pdfs"', '3'])
def test_config_that_is_not_an_object(project, text):
    (project / 'literature.json').write_text(text)
    with pytest.raises(SystemExit, match='must be one JSON object'):
        common.load_config(start=project)


def test_broken_input_lines_name_their_file(project, offline, monkeypatch, tmp_path):
    monkeypatch.chdir(project)
    with pytest.raises(SystemExit, match='--abstracts: file not found'):
        rank.main(['--out', str(project / 'runs/a'), '--abstracts', str(tmp_path / 'none.jsonl')])
    s = tmp_path / 's.jsonl'
    s.write_text('{"doi": "10.1/q", "title": "Q", "abstract": "a"}\n{"doi": \n')
    with pytest.raises(SystemExit, match='s.jsonl line 2: not a JSON record'):
        rank.main(['--out', str(project / 'runs/a'), '--abstracts', str(s)])
    s.write_text('{"doi": "10.1/q", "title": "Q", "abstract": "a"}\n')
    (project / 'papers/new').mkdir()
    (project / 'papers/new/fetch_log.jsonl').write_text('{"id": "10.1/q"}\n{"id"\n')
    with pytest.raises(SystemExit, match='fetch_log.jsonl line 2'):
        rank.main(['--out', str(project / 'runs/a'), '--abstracts', str(s)])
    with pytest.raises(SystemExit, match='--from .*not found'):
        fetch_pdf.main(['--from', str(tmp_path / 'none.jsonl')])
    s.write_text('not json\n')
    with pytest.raises(SystemExit, match='line 1: not a JSON record'):
        fetch_pdf.main(['--from', str(s)])
    assert leftovers(project) == []


def test_cut_logs_and_records_are_named(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    (project / 'queries/questions.jsonl').write_text('{"created": "x", "quest')
    with pytest.raises(SystemExit, match='questions.jsonl line 1 is not a JSON record'):
        rank.main(['--out', str(project / 'runs/r')])
    (project / 'queries/questions.jsonl').unlink()
    (project / 'runs').mkdir()
    (project / 'runs/r_paper-lector_rank_run.json').write_text('{"created": "x", "que')
    with pytest.raises(SystemExit, match='not a complete run record'):
        rank.main(['--out', str(project / 'runs/r')])


def test_slow_extraction_is_skipped(project, offline, monkeypatch, capsys):
    monkeypatch.chdir(project)
    real = subprocess.run

    def slow(cmd, **kw):
        if cmd[0] == 'pdftotext' and 'Ocean2023' in cmd[-2]:
            raise subprocess.TimeoutExpired(cmd, kw.get('timeout'))
        return real(cmd, **kw)
    monkeypatch.setattr(rank.subprocess, 'run', slow)
    rank.main(['--out', str(project / 'runs/s'), '--provider', 'local'])
    run = json.load(open(project / 'runs/s_paper-lector_rank_run.json'))
    assert run['corpus']['skipped'][0]['id'] == 'Ocean2023' and 'more than 300 s' in run['corpus']['skipped'][0]['reason']


def test_pdftotext_output_is_read_as_utf8(project, monkeypatch):
    seen = {}
    real = subprocess.run

    def spy(cmd, **kw):
        seen.update(cmd=cmd, encoding=kw.get('encoding'))
        return real(cmd, **kw)
    monkeypatch.setattr(rank.subprocess, 'run', spy)
    rank.pdf_pages(project / 'papers/topic/Ocean2023.pdf')
    assert seen['cmd'][1:3] == ['-enc', 'UTF-8'] and seen['encoding'] == 'utf-8'


@pytest.mark.parametrize('addr', ['64:ff9b::7f00:1', '64:ff9b::a00:5', '64:ff9b::a9fe:a9fe'])
def test_nat64_addresses_of_private_hosts_are_refused(monkeypatch, addr):
    monkeypatch.setattr(fetch_pdf.socket, 'getaddrinfo', lambda *a: [(None, None, None, None, (addr, 80, 0, 0))])
    with pytest.raises(ValueError, match='not a public address'):
        fetch_pdf.check_url('http://example.org/x.pdf')


def test_run_record_holds_version_argv_and_input_hashes(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    rank.main(['--out', str(project / 'runs/v')])
    run = json.load(open(project / 'runs/v_paper-lector_rank_run.json'))
    assert run['paper_lector_version'] == common.VERSION and run['argv'] == ['--out', str(project / 'runs/v')]
    ins = run['inputs']
    assert ins['config']['path'] == 'literature.json' and ins['sources']['path'] == 'sources.csv'
    assert ins['queries_file']['sha256'] == common.sha256_file(project / 'queries/queries.json')
    assert ins['fetch_logs'] == []
    assert sum(offline.sent) <= run['estimate']      # every request's tokens, as counted against the budget


def test_key_file_readable_by_others_gets_a_note(project, monkeypatch, capsys):
    monkeypatch.delenv('VOYAGE_API_KEY', raising=False)
    env = project / '.env'
    env.write_text('VOYAGE_API_KEY=abc\n')
    os.chmod(env, 0o644)
    cfg = common.load_config(start=project)
    assert common.api_key('VOYAGE_API_KEY', cfg) == 'abc'
    assert 'chmod 600' in capsys.readouterr().err
    os.chmod(env, 0o600)
    common.api_key('VOYAGE_API_KEY', cfg)
    assert 'chmod' not in capsys.readouterr().err


def test_malformed_embeddings_are_never_cached(project, offline, monkeypatch):
    import sqlite3
    monkeypatch.chdir(project)
    real = offline.__call__

    def scalar(ep, body, n=None):
        r = real(ep, body, n)
        if ep == 'embeddings':
            r['data'] = [{'index': i, 'embedding': 1.0} for i in range(len(body['input']))]
        return r
    monkeypatch.setattr(rank, 'call', scalar)
    with pytest.raises(SystemExit, match='invalid embedding batch'):
        rank.main(['--out', str(project / 'runs/e')])
    db = sqlite3.connect(rank.CACHE)
    assert db.execute('select count(*) from emb').fetchone()[0] == 0
    monkeypatch.setattr(rank, 'call', offline)
    rank.main(['--out', str(project / 'runs/e')])                       # a valid rerun just works
    assert (project / 'runs/e_paper-lector_rank_run.json').is_file()


def test_cached_vectors_of_another_size_are_fetched_again(project, offline, monkeypatch, capsys):
    import sqlite3
    monkeypatch.chdir(project)
    rank.main(['--out', str(project / 'runs/a')])
    db = sqlite3.connect(rank.CACHE)
    k = db.execute('select key from emb limit 1').fetchone()[0]
    db.execute('update emb set vec = ? where key = ?', (b'\0\0\x80?' * 3, k)); db.commit(); db.close()
    rank.main(['--out', str(project / 'runs/b')])
    assert '1 cached embeddings were unusable' in capsys.readouterr().err
    a, b = (open(project / f'runs/{x}_paper-lector_rank.csv').read() for x in 'ab')
    assert a == b


def test_query_vectors_must_match_the_windows(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    real = offline.__call__

    def short_queries(ep, body, n=None):
        r = real(ep, body, n)
        if ep == 'embeddings' and body['input_type'] == 'query':
            for x in r['data']:
                x['embedding'] = x['embedding'][:32]
        return r
    monkeypatch.setattr(rank, 'call', short_queries)
    with pytest.raises(SystemExit, match='invalid embedding batch'):
        rank.main(['--out', str(project / 'runs/q')])


def test_embedding_cache_errors_stop_with_a_message(project, offline, monkeypatch):
    import sqlite3
    monkeypatch.chdir(project)
    monkeypatch.setattr(rank.sqlite3, 'connect', lambda *a: (_ for _ in ()).throw(sqlite3.OperationalError('database or disk is full')))
    with pytest.raises(SystemExit, match='embedding cache .* cannot be read or written'):
        rank.main(['--out', str(project / 'runs/c')])
    assert leftovers(project) == []


@pytest.mark.parametrize('answer', [None, [], {'data': {}}, {'data': [None]}, {'data': [[0, 0.5]]}])
def test_rerank_answers_of_the_wrong_shape(answer):
    with pytest.raises(SystemExit, match='invalid rerank answer'):
        rank.rerank_scores(answer, 1)
    assert rank.tokens_used(answer) == 0


def test_non_object_lines_name_their_file(project, offline, monkeypatch, tmp_path):
    import search_overlap
    monkeypatch.chdir(project)
    s = tmp_path / 's.jsonl'
    s.write_text('{"doi": "10.1/q", "title": "Q", "abstract": "a"}\nnull\n')
    with pytest.raises(SystemExit, match='s.jsonl line 2: not a JSON record'):
        rank.main(['--out', str(project / 'runs/a'), '--abstracts', str(s)])
    with pytest.raises(SystemExit, match='line 2: not a JSON record'):
        fetch_pdf.main(['--from', str(s)])
    with pytest.raises(SystemExit, match='s.jsonl line 2: not a JSON record'):
        search_overlap.main([str(s), str(s)])
    s.write_text('{"doi": "10.1/q", "title": "Q", "abstract": "a"}\n')
    with pytest.raises(SystemExit, match='file not found'):
        search_overlap.main([str(s), str(tmp_path / 'none.jsonl')])
    (project / 'papers/new').mkdir()
    (project / 'papers/new/fetch_log.jsonl').write_text('[1, 2]\n')
    with pytest.raises(SystemExit, match='fetch_log.jsonl line 1'):
        rank.main(['--out', str(project / 'runs/a'), '--abstracts', str(s)])
    (project / 'queries/questions.jsonl').write_text('null\n')
    with pytest.raises(SystemExit, match='questions.jsonl line 1 is not a JSON record'):
        rank.main(['--out', str(project / 'runs/a')])


def test_leading_line_break_is_escaped_and_reads_back(project, offline, monkeypatch):
    assert rank.cell('\n=1+1') == "'\n=1+1" and rank.cell('\r=1') == "'\r=1"
    import shutil
    monkeypatch.chdir(project)
    shutil.copy(project / 'papers/topic/Ocean2023.pdf', project / 'papers/topic/\n=1+1.pdf')
    (project / 'papers/topic/Ocean2023.pdf').unlink()
    rank.main(['--out', str(project / 'runs/n'), '--provider', 'local'])
    csvp = project / 'runs/n_paper-lector_rank-local.csv'
    import csv
    ids = [r['paper'] for r in csv.DictReader(open(csvp, encoding='utf-8', newline=''))]
    assert "'\n=1+1" in ids
    rank.main(['--out', str(project / 'runs/m'), '--provider', 'local', '--ids', str(csvp)])
    run = json.load(open(project / 'runs/m_paper-lector_rank_run.json'))
    assert '\n=1+1' in run['corpus']['ids']


def test_fetch_stops_when_the_network_is_down(project, monkeypatch, capsys):
    monkeypatch.chdir(project)
    monkeypatch.setenv('OPENALEX_API_KEY', 'test')
    looked = []
    monkeypatch.setattr(fetch_pdf, 'openalex', lambda i: looked.append(i) or (_ for _ in ()).throw(urllib.error.URLError('dns')))
    with pytest.raises(SystemExit, match='network looks down. Stopped with 2 of 5 not tried'):
        fetch_pdf.main(['10.9/a', '10.9/b', '10.9/c', '10.9/d', '10.9/e'])
    assert len(looked) == 3


def test_download_deadline_counts_a_stalled_last_read(monkeypatch):
    clock = iter([0, 10, 400, 400, 400])
    monkeypatch.setattr(fetch_pdf.time, 'monotonic', lambda: next(clock))
    monkeypatch.setattr(fetch_pdf, 'check_url', lambda u: None)

    class Resp:
        headers = {}
        chunks = [b'%PDF-1.4 x', b'']
        def __enter__(self):
            return self
        def __exit__(self, *e):
            pass
        def read(self, n):
            return self.chunks.pop(0)
    monkeypatch.setattr(fetch_pdf.OPENER, 'open', lambda *a, **k: Resp())
    monkeypatch.setattr(common.time, 'sleep', lambda s: None)
    with pytest.raises(ValueError, match='more than 300 s'):
        fetch_pdf.fetch('https://example.org/x.pdf')


def test_voyage_rate_limit_names_the_payment_method(monkeypatch):
    monkeypatch.setattr(rank, 'KEY', 'k')
    monkeypatch.setattr(rank, 'SENT', 0)
    monkeypatch.setattr(rank, 'BUDGET', 10**9)
    monkeypatch.setattr(common.time, 'sleep', lambda s: None)
    err = lambda: urllib.error.HTTPError('u', 429, 'Too Many', {}, io.BytesIO(b''))
    monkeypatch.setattr(rank.urllib.request, 'urlopen', lambda *a, **k: (_ for _ in ()).throw(err()))
    with pytest.raises(SystemExit, match='payment method'):
        rank.call('embeddings', {}, 1)


def test_run_record_holds_cwd_and_os(project, offline, monkeypatch):
    monkeypatch.chdir(project / 'papers')
    rank.main(['--out', str(project / 'runs/w')])
    run = json.load(open(project / 'runs/w_paper-lector_rank_run.json'))
    assert run['cwd'] == 'papers' and run['versions']['os']


def test_matching_many_search_records_stays_fast(tmp_path):
    import random, time
    random.seed(1)
    vocab = [''.join(random.choice('abcdefghijklmnop') for _ in range(random.randint(4, 10))) for _ in range(3000)]
    f = tmp_path / 'r.jsonl'
    f.write_text(''.join(json.dumps({'openalex': f'W{i}', 'title': ' '.join(random.choices(vocab, k=10)),
                                     'year': 2020 + i % 5, 'first_author': random.choice(['A Smith', 'B Jones']),
                                     'abstract': ' '.join(random.choices(vocab, k=150))}) + '\n' for i in range(500)))
    t = time.monotonic()
    assert len(rank.abstract_corpus([str(f)], [], [], None, [])) == 500
    assert time.monotonic() - t < 20               # 36 s before the word sets were cached; about 2 s now


def test_keys_are_redacted_and_not_sent_on_redirects(monkeypatch):
    key = 'pa-SECRETKEY123'
    assert common.redact(f'bad key {key} given', key) == 'bad key *** given'
    req = common.authorized(rank.urllib.request.Request('https://api.voyageai.com/v1/x'), key)
    assert req.unredirected_hdrs == {'Authorization': f'Bearer {key}'} and 'Authorization' not in req.headers
    monkeypatch.setattr(rank, 'KEY', key)
    monkeypatch.setattr(rank, 'SENT', 0)
    monkeypatch.setattr(rank, 'BUDGET', 10**9)
    err = urllib.error.HTTPError('u', 400, 'Bad', {}, io.BytesIO(json.dumps({'detail': f'key {key} invalid'}).encode()))
    monkeypatch.setattr(rank.urllib.request, 'urlopen', lambda *a, **k: (_ for _ in ()).throw(err))
    with pytest.raises(SystemExit) as e:
        rank.call('embeddings', {}, 1)
    assert key not in str(e.value) and '***' in str(e.value)


def test_overlong_query_stops_before_any_call(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    q = json.loads((project / 'queries/queries.json').read_text())
    q['queries']['Q0']['text'] = 'word ' * 8001
    (project / 'queries/long.json').write_text(json.dumps(q))
    with pytest.raises(SystemExit, match='query of at most 8,000 tokens'):
        rank.main(['--out', str(project / 'runs/l'), '--queries', str(project / 'queries/long.json')])
    assert offline.calls == []


def test_ipv4_compatible_address_of_loopback_is_refused(monkeypatch):
    monkeypatch.setattr(fetch_pdf.socket, 'getaddrinfo', lambda *a: [(None, None, None, None, ('::7f00:1', 80, 0, 0))])
    with pytest.raises(ValueError, match='not a public address'):
        fetch_pdf.check_url('http://example.org/x.pdf')


def test_write_new_without_hard_links_never_leaves_a_half_file(tmp_path, monkeypatch):
    monkeypatch.setattr(common.os, 'link', lambda *a: (_ for _ in ()).throw(PermissionError(1, 'not supported')))
    monkeypatch.setattr(common.os, 'rename', lambda *a: (_ for _ in ()).throw(KeyboardInterrupt()))   # killed there
    with pytest.raises(KeyboardInterrupt):
        common.write_new(tmp_path / 'a.pdf', b'%PDF data')
    assert list(tmp_path.iterdir()) == []


def test_unwritable_folders_stop_with_a_message(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    real = rank.Path.mkdir
    monkeypatch.setattr(rank.Path, 'mkdir', lambda self, *a, **k: full_disk() if self.name in ('runs', 'new') else real(self, *a, **k))
    with pytest.raises(SystemExit, match='cannot create .*lock'):
        rank.main(['--out', str(project / 'runs/u')])
    with pytest.raises(SystemExit, match='cannot create the download folder'):
        fetch_pdf.main(['10.9/a'])


def test_openalex_answer_that_is_not_json(monkeypatch):
    monkeypatch.setattr(openalex_search.common, 'openalex_json', lambda *a, **k: (_ for _ in ()).throw(json.JSONDecodeError('x', 'y', 0)))
    with pytest.raises(SystemExit, match='not JSON'):
        openalex_search.get('works', {})


def test_an_embedding_index_given_twice_is_refused(offline, monkeypatch):
    from collections import Counter
    import sqlite3
    monkeypatch.setattr(rank, 'call', lambda ep, b, n: {'data': [{'index': 0, 'embedding': [1., 0.]},
                                                                 {'index': 0, 'embedding': [0., 1.]}]})
    with pytest.raises(SystemExit, match='invalid embedding batch'):
        rank.embed([('alpha', 1)], 'document', Counter(), [('s', 0, 'p. 1')])
    assert sqlite3.connect(rank.CACHE).execute('select count(*) from emb').fetchone()[0] == 0


def test_two_papers_that_share_a_title_stay_apart(tmp_path):
    t = 'A Survey of Hallucination Detection in Generated Text'
    f = tmp_path / 's.jsonl'
    f.write_text(json.dumps({'doi': '10.1/a', 'title': t, 'year': 2019, 'first_author': 'Ann Lee', 'abstract': 'one'}) + '\n'
                 + json.dumps({'doi': '10.2/b', 'title': t, 'year': 2024, 'first_author': 'Bo Chen', 'abstract': 'two'}) + '\n'
                 + json.dumps({'doi': '10.3/c', 'title': t + 's', 'year': 2020, 'first_author': 'LEE, Ann', 'abstract': 'three'}) + '\n')
    A = rank.abstract_corpus([str(f)], [], [], None, [])
    assert sorted(x['text'] for x in A) == ['one', 'two']          # the third is Lee's own other version


def test_a_failed_write_prints_no_ranking(project, offline, monkeypatch, capsys):
    monkeypatch.chdir(project)
    monkeypatch.setattr(common, 'write_new', full_disk)
    with pytest.raises(SystemExit):
        rank.main(['--out', str(project / 'runs/p'), '--expect', 'Switch2024'])
    assert 'fused top 10' not in capsys.readouterr().out


def test_ctrl_c_while_writing_keeps_no_output(project, offline, monkeypatch):
    monkeypatch.chdir(project)
    real, calls = common.write_new, []

    def second(path, data):
        calls.append(path)
        if len(calls) == 2:
            raise KeyboardInterrupt
        return real(path, data)
    monkeypatch.setattr(common, 'write_new', second)
    with pytest.raises(KeyboardInterrupt):
        rank.main(['--out', str(project / 'runs/k')])
    assert leftovers(project) == []


def test_a_broken_file_under_the_pdf_name_is_not_counted_as_held(project, monkeypatch, capsys):
    monkeypatch.chdir(project)
    monkeypatch.setenv('OPENALEX_API_KEY', 'test')
    w = {'doi': 'https://doi.org/10.9/a', 'display_name': 'New paper', 'best_oa_location': {'pdf_url': 'http://oa/a'}, 'locations': []}
    monkeypatch.setattr(fetch_pdf, 'openalex', lambda i: w)
    (project / 'papers/new').mkdir()
    (project / 'papers/new' / fetch_pdf.name_for(w, '10.9/a')).write_bytes(b'<html>blocked</html>')
    with pytest.raises(SystemExit):
        fetch_pdf.main(['10.9/a'])
    assert 'exists but is not a PDF' in capsys.readouterr().out


def test_missing_ids_file_and_unknown_seed(project, offline, monkeypatch, tmp_path):
    monkeypatch.chdir(project)
    with pytest.raises(SystemExit, match='--ids .*file not found'):
        rank.main(['--out', str(project / 'runs/i'), '--ids', str(tmp_path / 'none.csv')])
    monkeypatch.setenv('OPENALEX_API_KEY', 'test')
    err = urllib.error.HTTPError('u', 404, 'Not Found', {}, io.BytesIO(b''))
    monkeypatch.setattr(openalex_search.common, 'openalex_json', lambda *a, **k: (_ for _ in ()).throw(err))
    with pytest.raises(SystemExit, match='W1: not found in OpenAlex'):
        openalex_search.main(['--refs', 'W1', '--out', str(tmp_path / 'r.jsonl')])
    assert not list(tmp_path.glob('r*'))


def test_config_that_is_not_utf8(project):
    (project / 'literature.json').write_bytes(b'{"pdf_dirs": ["\xff"]}')
    with pytest.raises(SystemExit, match='not valid JSON in UTF-8'):
        common.load_config(start=project)


@pytest.mark.parametrize('work', [None, {'doi': '10.1/x'}, {'id': 'W1', 'authorships': [{'author': None}]}])
def test_openalex_work_of_an_unexpected_shape(project, monkeypatch, tmp_path, work):
    monkeypatch.chdir(project)
    monkeypatch.setenv('OPENALEX_API_KEY', 'test')
    monkeypatch.setattr(openalex_search.common, 'openalex_json',
                        lambda *a, **k: {'results': [work], 'meta': {'count': 1, 'next_cursor': None}})
    with pytest.raises(SystemExit, match='unexpected shape'):
        openalex_search.main(['--exact', 'x', '--out', str(tmp_path / 'o.jsonl')])
    assert not list(tmp_path.glob('o*'))
