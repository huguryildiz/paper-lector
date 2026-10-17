import json
import re
import urllib.error
from pathlib import Path
import fetch_pdf
import openalex_search


def test_record_rebuilds_abstract_and_marks_known_doi():
    w = {'id': 'https://openalex.org/W1', 'doi': 'https://doi.org/10.1/Q', 'display_name': 'T', 'publication_year': 2022,
         'primary_location': {'source': {'display_name': 'Venue'}}, 'best_oa_location': {'pdf_url': 'http://x/p.pdf'},
         'locations': [{'landing_page_url': 'https://arxiv.org/abs/2205.06300'}],
         'authorships': [{'author': {'display_name': 'A. Chandra'}}, {'author': {'display_name': 'B. Roy'}}],
         'biblio': {'volume': '12', 'issue': None, 'first_page': '3', 'last_page': '9'},
         'cited_by_count': 136, 'citation_normalized_percentile': {'value': 0.98353529},
         'abstract_inverted_index': {'world': [1], 'hello': [0]}}
    r = openalex_search.record(w, {'10.1/q': 'queue2022'})
    assert r['abstract'] == 'hello world' and r['in_sources'] == 'queue2022'
    assert r['arxiv'] == '2205.06300' and r['oa_pdf'] == 'http://x/p.pdf' and r['openalex'] == 'W1'
    assert (r['cited_by'], r['cited_pct']) == (136, 98.4) and len(r['cited_at']) == 10
    assert r['authors'] == ['A. Chandra', 'B. Roy'] and r['biblio'] == {'volume': '12', 'first_page': '3', 'last_page': '9'}


def test_pdf_name_and_candidate_order():
    w = {'authorships': [{'author': {'display_name': 'Aparimit Chandra'}}], 'publication_year': 2022,
         'display_name': 'Scheduling Quantum Teleportation with Noisy Memories',
         'best_oa_location': {'pdf_url': 'http://oa/p.pdf'},
         'locations': [{'landing_page_url': 'https://arxiv.org/abs/2205.06300', 'pdf_url': 'http://oa/p.pdf'}]}
    assert fetch_pdf.name_for(w, '10.1109/QCE.2022.1').startswith('Chandra2022_SchedulingQuantumTeleportationNoisyMemories_')
    assert fetch_pdf.name_for(w, '10.1109/QCE.2022.1') != fetch_pdf.name_for(w, '10.1109/QCE.2022.2')   # same title, other DOI
    assert fetch_pdf.candidates('10.1109/QCE.2022.1', w) == ['https://arxiv.org/pdf/2205.06300', 'http://oa/p.pdf']


def test_fetch_skips_held_doi_and_keeps_same_title_papers_apart(project, monkeypatch, capsys):
    monkeypatch.chdir(project)
    monkeypatch.setenv('OPENALEX_API_KEY', 'test')
    w = lambda doi: {'doi': 'https://doi.org/' + doi, 'display_name': 'Deep Routing', 'publication_year': 2023,
                     'authorships': [{'author': {'display_name': 'Li Zhang'}}],
                     'best_oa_location': {'pdf_url': 'http://oa/' + doi}, 'locations': []}
    fetched = []
    monkeypatch.setattr(fetch_pdf, 'openalex', lambda ident: w(ident))
    monkeypatch.setattr(fetch_pdf, 'fetch', lambda url: fetched.append(url) or b'%PDF-1.4 ' + url.encode())
    fetch_pdf.main(['10.1/q', '10.9/a', '10.9/b'])
    out = capsys.readouterr().out
    assert 'HAVE    10.1/q -> sources key queue2022' in out           # held DOI: no lookup, no download
    assert fetched == ['http://oa/10.9/a', 'http://oa/10.9/b']
    assert len(list((project / 'papers/new').glob('Zhang2023_DeepRouting_*.pdf'))) == 2


def test_fetch_does_not_save_a_byte_identical_copy(project, monkeypatch, capsys):
    monkeypatch.chdir(project)
    monkeypatch.setenv('OPENALEX_API_KEY', 'test')
    held = (project / 'papers/topic/Ocean2023.pdf').read_bytes()
    monkeypatch.setattr(fetch_pdf, 'openalex', lambda ident: {'doi': 'https://doi.org/' + ident, 'display_name': 'Ocean',
                                                              'best_oa_location': {'pdf_url': 'http://oa/x'}, 'locations': []})
    monkeypatch.setattr(fetch_pdf, 'fetch', lambda url: held)
    fetch_pdf.main(['10.9/ocean'])
    assert '(same file)' in capsys.readouterr().out
    assert not list((project / 'papers/new').glob('*.pdf'))


import pytest


@pytest.mark.parametrize('url', ['file:///etc/passwd', 'data:application/pdf,%PDF', 'http://127.0.0.1/x.pdf',
                                 'http://10.0.0.5/x.pdf', 'http://169.254.169.254/latest', 'http://[::1]/x.pdf'])
def test_fetch_refuses_local_and_non_http_urls(url):
    with pytest.raises(ValueError):
        fetch_pdf.fetch(url)


def test_redirect_to_private_address_is_refused():
    import urllib.request
    h = fetch_pdf.CheckedRedirect()
    with pytest.raises(ValueError):
        h.redirect_request(urllib.request.Request('https://example.org/a'), None, 302, 'Found', {}, 'http://192.168.1.1/x')


def test_fetch_stops_at_size_limit(monkeypatch):
    import io
    class R(io.BytesIO):
        headers = {}
    monkeypatch.setattr(fetch_pdf, 'check_url', lambda u: None)
    monkeypatch.setattr(fetch_pdf, 'MAX_BYTES', 10)
    monkeypatch.setattr(fetch_pdf.OPENER, 'open', lambda req, timeout: R(b'%PDF' + b'x' * 100))
    with pytest.raises(ValueError, match='larger than'):
        fetch_pdf.fetch('https://example.org/big.pdf')


def test_arxiv_doi_and_doi_url_candidates():
    assert fetch_pdf.candidates('10.48550/arxiv.2205.06300', None) == ['https://arxiv.org/pdf/2205.06300']
    assert fetch_pdf.candidates('https://doi.org/10.1109/X.1', None) == []


def test_jsonl_records_with_openalex_or_arxiv_only(project, monkeypatch, capsys, tmp_path):
    import json
    monkeypatch.chdir(project)
    monkeypatch.setenv('OPENALEX_API_KEY', 'test')
    src = tmp_path / 'r.jsonl'
    src.write_text('\n'.join(json.dumps(r) for r in [
        {'openalex': 'W9', 'title': 'No DOI'}, {'arxiv': '2205.06300', 'title': 'arXiv only'}, {'title': 'Nothing'}]) + '\n')
    seen = []
    monkeypatch.setattr(fetch_pdf, 'openalex', lambda ident: seen.append(ident) or {'display_name': ident, 'locations': []})
    monkeypatch.setattr(fetch_pdf, 'fetch', lambda url: b'%PDF-1.4 ' + url.encode())
    with pytest.raises(SystemExit):              # W9 has no PDF link: MANUAL, so exit status 1
        fetch_pdf.main(['--from', str(src)])
    out = capsys.readouterr().out
    assert seen == ['W9', '2205.06300']
    assert 'SKIP    line 3' in out and 'MANUAL  W9' in out and 'OK      2205.06300' in out
    log = (project / 'papers/new/fetch_log.jsonl').read_text()
    assert 'arxiv.org/pdf/2205.06300' in log and '"sha256"' in log


def test_manual_papers_are_logged_with_status(project, monkeypatch, capsys):
    import json
    monkeypatch.chdir(project)
    monkeypatch.setenv('OPENALEX_API_KEY', 'test')
    works = {'W9': {'display_name': 'Paywalled paper', 'locations': [],
                    'primary_location': {'landing_page_url': 'https://publisher.example/w9'}}}
    monkeypatch.setattr(fetch_pdf, 'openalex', lambda ident: works.get(ident, {'display_name': ident, 'locations': []}))
    monkeypatch.setattr(fetch_pdf, 'fetch', lambda url: b'%PDF-1.4 ' + url.encode())
    with pytest.raises(SystemExit):
        fetch_pdf.main(['W9', '2205.06300'])
    rows = [json.loads(l) for l in (project / 'papers/new/fetch_log.jsonl').read_text().splitlines()]
    manual = [r for r in rows if r['status'] == 'MANUAL']
    assert manual == [{'id': 'W9', 'status': 'MANUAL', 'title': 'Paywalled paper',
                       'url': 'https://publisher.example/w9', 'fetched': manual[0]['fetched']}]
    assert [r['id'] for r in rows if r['status'] == 'OK'] == ['2205.06300']


def test_lookup_error_is_not_reported_as_missing(project, monkeypatch, capsys):
    import urllib.error
    monkeypatch.chdir(project)
    monkeypatch.setenv('OPENALEX_API_KEY', 'test')
    def denied(ident):
        raise urllib.error.HTTPError('u', 401, 'Unauthorized', {}, None)
    monkeypatch.setattr(fetch_pdf, 'openalex', denied)
    with pytest.raises(SystemExit):
        fetch_pdf.main(['10.9/x'])
    assert 'ERROR   10.9/x: OpenAlex lookup failed' in capsys.readouterr().out


def test_save_never_replaces_a_file(tmp_path):
    out = tmp_path / 'a.pdf'
    assert fetch_pdf.save(out, b'%PDF one') and not fetch_pdf.save(out, b'%PDF two')
    assert out.read_bytes() == b'%PDF one' and [p.name for p in tmp_path.iterdir()] == ['a.pdf']


def test_refs_fetched_in_chunks_of_100(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv('OPENALEX_API_KEY', 'test')
    monkeypatch.setattr(openalex_search.common, 'load_config', lambda *a, **k: None)
    refs = [f'https://openalex.org/W{i}' for i in range(250)]
    calls = []
    def get(path, params):
        calls.append(params)
        if path.startswith('works/W'):
            return {'referenced_works': refs}
        ids = params['filter'].removeprefix('ids.openalex:').split('|')
        return {'results': [{'id': 'https://openalex.org/' + i} for i in ids]}
    monkeypatch.setattr(openalex_search, 'get', get)
    openalex_search.main(['--refs', 'W1', '--out', str(tmp_path / 'r.jsonl')])
    assert len((tmp_path / 'r.jsonl').read_text().splitlines()) == 250
    assert [len(c['filter'].split('|')) for c in calls[1:]] == [100, 100, 50]


def test_exact_uses_unstemmed_search(monkeypatch, tmp_path):
    monkeypatch.setenv('OPENALEX_API_KEY', 'test')
    monkeypatch.setattr(openalex_search.common, 'load_config', lambda *a, **k: None)
    calls = []
    monkeypatch.setattr(openalex_search, 'get', lambda path, params: calls.append(params) or
                        {'results': [], 'meta': {'count': 0}})
    openalex_search.main(['--exact', 'rout* AND energy', '--out', str(tmp_path / 'e.jsonl')])
    assert calls[0]['search.title_and_abstract.exact'] == 'rout* AND energy' and 'filter' not in calls[0]


def test_cut_off_download_is_retried_not_saved(monkeypatch):
    import http.client, io
    class R(io.BytesIO):
        headers = {'Content-Length': '1000'}
    bodies = [b'%PDF', b'%PDF' + b'x' * 996]
    monkeypatch.setattr(fetch_pdf, 'check_url', lambda u: None)
    monkeypatch.setattr(fetch_pdf.common.time, 'sleep', lambda s: None)
    monkeypatch.setattr(fetch_pdf.OPENER, 'open', lambda req, timeout: R(bodies.pop(0)))
    assert len(fetch_pdf.fetch('https://example.org/p.pdf')) == 1000


def test_arxiv_fetched_even_when_openalex_fails(project, monkeypatch, capsys):
    import urllib.error
    monkeypatch.chdir(project)
    monkeypatch.setenv('OPENALEX_API_KEY', 'test')
    def denied(ident):
        raise urllib.error.HTTPError('u', 401, 'Unauthorized', {}, None)
    monkeypatch.setattr(fetch_pdf, 'openalex', denied)
    monkeypatch.setattr(fetch_pdf, 'fetch', lambda url: b'%PDF-1.4 ' + url.encode())
    fetch_pdf.main(['2205.06300'])
    assert 'OK      2205.06300' in capsys.readouterr().out


def test_only_skipped_records_exit_with_failure(project, monkeypatch, tmp_path):
    monkeypatch.chdir(project)
    monkeypatch.setenv('OPENALEX_API_KEY', 'test')
    src = tmp_path / 'r.jsonl'
    src.write_text('{"title": "no id"}\n')
    with pytest.raises(SystemExit) as e:
        fetch_pdf.main(['--from', str(src)])
    assert e.value.code == 1


def test_search_without_key_stops_after_first_page(project, monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(project)
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.delenv('OPENALEX_API_KEY', raising=False)
    calls = []

    def fake(url, key, timeout):
        calls.append(key)
        return {'results': [{'id': 'https://openalex.org/W1'}], 'meta': {'count': 500, 'next_cursor': 'abc'}}
    monkeypatch.setattr(openalex_search.common, 'openalex_json', fake)
    openalex_search.main(['--exact', 'quantum switch', '--out', str(tmp_path / 's.jsonl')])
    assert calls == [None]                                  # one keyless request, no second page
    assert 'only the first 1 of 500 were written' in capsys.readouterr().err


def _raise(err):
    def urlopen(*a, **k):
        raise err
    return urlopen


def test_spent_daily_budget_stops_search_with_reset_time(monkeypatch):
    import io, urllib.error
    err = urllib.error.HTTPError('u', 429, 'Too Many', {'Retry-After': '11400'}, io.BytesIO(b''))
    monkeypatch.setattr(openalex_search.common.urllib.request, 'urlopen', _raise(err))
    monkeypatch.setattr(openalex_search.common.time, 'sleep', lambda s: pytest.fail('waited for a spent budget'))
    monkeypatch.setattr(openalex_search, 'KEY', None)
    with pytest.raises(SystemExit, match='resets in about 4 h.*free OPENALEX_API_KEY'):
        openalex_search.get('works', {})


def test_long_retry_after_on_503_is_still_retried(monkeypatch):
    import io, urllib.error
    calls = []

    def fn():
        calls.append(1)
        if len(calls) == 1:
            raise urllib.error.HTTPError('u', 503, 'Busy', {'Retry-After': '180'}, io.BytesIO(b''))
        return 'ok'
    monkeypatch.setattr(openalex_search.common.time, 'sleep', lambda s: None)
    assert openalex_search.common.retry(fn) == 'ok' and len(calls) == 2


@pytest.mark.parametrize('q,bad', [
    ('"quantum switch" scheduling OR "operations research"', 'mixed'),
    ('"quantum switch" AND scheduling OR "operations research"', 'mixed'),
    ('(a OR b) AND c d', None), ('((a OR b) AND c) d', None),
    ('(a OR b) c', None), ('c (a OR b)', None), ('c ((a OR b))', None),   # live 2026-10-18: read as AND
    ('"quantum switch" (a OR (b c))', None), ('c AND (a OR b)', None), ('c (a b)', None),
    ('(a OR b OR c) AND (d OR e OR f OR g)', '6 AND/OR/NOT'),
    ('(a OR b', 'unbalanced'), ('a OR b)', 'unbalanced'), ('"a b', 'unbalanced'),
    ('', 'empty query'), ('  ', 'empty query'), ('()', 'empty group'), ('a AND ()', 'empty group'),
    ('a OR', 'no term after'), ('OR a', 'no term before'), ('a OR OR b', 'no term before'),
    ('("quantum switch" OR "quantum network*") AND schedul*', 'inside quotes'),
    ('"quantum network*"', None), ('("quantum network*")', None),
    ('("quantum switch" OR "quantum network") AND (schedul* OR "operations research")', None),
    ('quantum switch scheduling', None), ('(a OR b) NOT c', None), ('a AND NOT b', None),
    ('a AND (b OR c d)', 'mixed'), ('a AND (b AND (c OR d e))', 'mixed'), ('((a OR b) AND (c d OR e))', 'mixed'),
    ('""', 'empty quotes'), ('a AND " "', 'empty quotes'),
    ('(' * 1000 + 'a' + ')' * 1000, 'nested 1000 deep'), ('(' * 10 + 'a' + ')' * 10, None),
    ('a NOT NOT b', 'NOT NOT'), ('a AND NOT NOT b', 'NOT NOT'), ('a NOT (b OR c)', None),
    ('"quantum switch" or "quantum network"', 'or in lower case'), ('a and b', 'and in lower case'),
    ('\u201cquantum switch\u201d OR c', None), ('(\u201cquantum network*\u201d OR a) AND b', 'inside quotes'),
    ('\u201ca', 'unbalanced quotes')])
def test_query_issues(q, bad):
    issues = openalex_search.query_issues(q)
    assert (not issues) if bad is None else any(bad in i for i in issues)


def test_misread_query_is_not_sent_and_query_record_is_written(project, monkeypatch, tmp_path):
    monkeypatch.chdir(project)
    monkeypatch.setenv('OPENALEX_API_KEY', 'test')
    sent = []
    monkeypatch.setattr(openalex_search.common, 'openalex_json', lambda url, key, timeout: sent.append(url) or
                        {'results': [{'id': 'https://openalex.org/W1'}], 'meta': {'count': 1, 'next_cursor': None}})
    with pytest.raises(SystemExit, match='query not sent'):
        openalex_search.main(['--exact', 'switch scheduling OR routing', '--out', str(tmp_path / 'bad.jsonl')])
    assert sent == [] and not (tmp_path / 'bad.query.json').exists()
    openalex_search.main(['--exact', 'switch AND (scheduling OR routing)', '--out', str(tmp_path / 's.jsonl')])
    rec = json.loads((tmp_path / 's.query.json').read_text())
    assert rec['mode'] == 'exact' and rec['query'] == 'switch AND (scheduling OR routing)'
    assert rec['count'] == 1 and rec['written'] == 1 and rec['keyless'] is False


def test_openalex_400_shows_its_message_in_search_but_not_in_fetch(monkeypatch):
    import io, urllib.error
    body = b'{"message": "Wildcards do not work here"}'
    monkeypatch.setattr(openalex_search.common.urllib.request, 'urlopen',
                        _raise(urllib.error.HTTPError('u', 400, 'Bad', {}, io.BytesIO(body))))
    monkeypatch.setattr(openalex_search, 'KEY', 'k')
    with pytest.raises(SystemExit, match='OpenAlex refused the request: Wildcards do not work here'):
        openalex_search.get('works', {})
    monkeypatch.setattr(fetch_pdf, 'KEY', 'k')
    with pytest.raises(urllib.error.HTTPError):        # fetch catches it and tries the direct links
        fetch_pdf.openalex('10.1/q')


def test_out_is_never_overwritten_and_must_be_jsonl(project, monkeypatch, tmp_path):
    monkeypatch.chdir(project)
    monkeypatch.setenv('OPENALEX_API_KEY', 'test')
    sent = []
    monkeypatch.setattr(openalex_search.common, 'openalex_json', lambda url, key, timeout: sent.append(url) or
                        {'results': [], 'meta': {'count': 0, 'next_cursor': None}})
    (tmp_path / 'old.jsonl').write_text('')
    (tmp_path / 'side.query.json').write_text('{}')
    for out in ('old.jsonl', 'side.jsonl', 'r.csv', 'r.JSONL'):
        with pytest.raises(SystemExit, match='must be a'):
            openalex_search.main(['--exact', 'switch', '--out', str(tmp_path / out)])
    with pytest.raises(SystemExit, match='--semantic is empty'):
        openalex_search.main(['--semantic', ' ', '--out', str(tmp_path / 'e.jsonl')])
    assert sent == []


def test_keyless_cut_reported_with_max_and_not_for_semantic(project, monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(project)
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.delenv('OPENALEX_API_KEY', raising=False)
    page = {'results': [{'id': f'https://openalex.org/W{i}'} for i in range(200)], 'meta': {'count': 500, 'next_cursor': 'c'}}
    monkeypatch.setattr(openalex_search.common, 'openalex_json', lambda url, key, timeout: page)
    openalex_search.main(['--exact', 'routing', '--max', '500', '--out', str(tmp_path / 'm.jsonl')])
    assert 'only the first 200 of 500' in capsys.readouterr().err
    assert json.loads((tmp_path / 'm.query.json').read_text())['keyless_first_page_only'] is True
    openalex_search.main(['--exact', 'routing', '--max', '100', '--out', str(tmp_path / 'm100.jsonl')])
    assert 'only the first' not in capsys.readouterr().err   # the user asked for 100 and got them
    page['results'] = page['results'][:50]
    openalex_search.main(['--semantic', 'routing in networks', '--out', str(tmp_path / 's.jsonl')])
    assert 'only the first' not in capsys.readouterr().err   # semantic stops at 50 with or without a key
    assert json.loads((tmp_path / 's.query.json').read_text())['keyless_first_page_only'] is False


def test_search_default_out_is_dated_by_mode(project, monkeypatch):
    monkeypatch.chdir(project / 'papers')
    monkeypatch.setenv('OPENALEX_API_KEY', 'test')
    monkeypatch.setattr(openalex_search, 'get', lambda path, params: {'results': [], 'meta': {'count': 0}})
    openalex_search.main(['--semantic', 'switch scheduling'])
    out = list((project / 'runs').glob('*_semantic.jsonl'))
    assert len(out) == 1 and re.fullmatch(r'\d{4}-\d\d-\d\d_\d{4}_semantic\.jsonl', out[0].name)
    assert json.loads(out[0].with_suffix('.query.json').read_text())['mode'] == 'semantic'
    openalex_search.main(['--semantic', 'switch scheduling'])          # same minute: a second file, not an overwrite
    assert len(list((project / 'runs').glob('*_semantic.jsonl'))) == 2


def test_search_name_goes_into_default_out(project, monkeypatch):
    monkeypatch.chdir(project)
    monkeypatch.setenv('OPENALEX_API_KEY', 'test')
    monkeypatch.setattr(openalex_search, 'get', lambda path, params: {'results': [], 'meta': {'count': 0}})
    openalex_search.main(['--exact', 'switch AND scheduling', '--name', 'switch-scheduling'])
    out, = (project / 'runs').glob('*_switch-scheduling_exact.jsonl')
    assert json.loads(out.with_suffix('.query.json').read_text())['name'] == 'switch-scheduling'
    with pytest.raises(SystemExit, match='--name'):
        openalex_search.main(['--exact', 'switch', '--name', 'Switch Scheduling'])


def test_a_second_run_on_the_same_out_is_refused_while_the_first_runs(project, monkeypatch, tmp_path):
    monkeypatch.chdir(project)
    monkeypatch.setenv('OPENALEX_API_KEY', 'test')
    out = str(tmp_path / 'x.jsonl')
    refused = []

    def fake(url, key, timeout):
        if not refused:                                   # the first run is between reserving and writing
            with pytest.raises(SystemExit, match='must be a new file'):
                openalex_search.main(['--exact', 'other', '--out', out])
            refused.append(1)
        return {'results': [{'id': 'https://openalex.org/W1'}], 'meta': {'count': 1, 'next_cursor': None}}
    monkeypatch.setattr(openalex_search.common, 'openalex_json', fake)
    openalex_search.main(['--exact', 'first', '--out', out])
    assert refused and json.loads(Path(out).with_suffix('.query.json').read_text())['query'] == 'first'


def test_failed_search_removes_its_reserved_files(project, monkeypatch, tmp_path):
    monkeypatch.chdir(project)
    monkeypatch.setenv('OPENALEX_API_KEY', 'test')
    monkeypatch.setattr(openalex_search.common, 'openalex_json', _raise(ConnectionError('down')))
    with pytest.raises(ConnectionError):
        openalex_search.main(['--exact', 'x', '--out', str(tmp_path / 'f.jsonl')])
    assert not list(tmp_path.glob('f.*'))


def test_retry_after_as_http_date_stops_on_spent_budget(monkeypatch):
    import datetime, email.utils, io
    later = email.utils.format_datetime(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=3), usegmt=True)
    err = urllib.error.HTTPError('u', 429, 'Too Many', {'Retry-After': later}, io.BytesIO(b''))
    assert 10700 < openalex_search.common.retry_after(err) <= 10800
    monkeypatch.setattr(openalex_search.common.urllib.request, 'urlopen', _raise(err))
    monkeypatch.setattr(openalex_search.common.time, 'sleep', lambda s: pytest.fail('waited for a spent budget'))
    monkeypatch.setattr(openalex_search, 'KEY', 'k')
    with pytest.raises(SystemExit, match='resets in about 3 h'):
        openalex_search.get('works', {})


@pytest.mark.parametrize('body,msg', [(b'{"message": null}', 'refused the request$'), (b'{"message": 42}', 'refused the request$'),
                                      (b'{"message": []}', 'refused the request$'), (b'[1]', None), (b'oops', None)])
def test_openalex_error_bodies(body, msg):
    import io
    got = openalex_search.common.openalex_error(urllib.error.HTTPError('u', 400, 'Bad', {}, io.BytesIO(body)), 'k')
    assert got is None if msg is None else re.search(msg, got)
