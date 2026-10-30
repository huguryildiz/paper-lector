"""Offline regressions for nested source tables and publication/PDF version separation."""
import json
from pathlib import Path

import pytest

import common
import fetch_pdf
import rank
from conftest import make_pdf


@pytest.fixture
def nested(tmp_path):
    (tmp_path / '.git').mkdir()
    config = tmp_path / 'literature/paper-lector-results/literature.json'
    config.parent.mkdir(parents=True)
    table = tmp_path / 'literature/sources.csv'
    config.write_text(json.dumps({'pdf_dirs': ['../pdfs'], 'sources': '../sources.csv'}))
    pdf = tmp_path / 'literature/pdfs/selected/Paper.pdf'
    pdf.parent.mkdir(parents=True)
    make_pdf(pdf, [['A paper']])
    table.write_text('key,pdf_path,doi\nknown,literature/pdfs/selected/Paper.pdf,10.1/known\n', encoding='utf-8-sig')
    return config, table, pdf


def test_nested_repo_path_is_held_without_fetch(nested, monkeypatch, capsys):
    config, _, pdf = nested
    assert common.sources(common.load_config(config))['known']['pdf'] == pdf
    monkeypatch.setattr(fetch_pdf, 'openalex', lambda _: pytest.fail('held PDF triggered lookup'))
    fetch_pdf.main(['--config', str(config), '10.1/known'])
    assert 'HAVE' in capsys.readouterr().out


@pytest.mark.parametrize('base', ['config', 'source', 'repo'])
def test_automatic_path_bases(nested, base):
    config, table, pdf = nested
    roots = {'config': config.parent, 'source': table.parent, 'repo': config.parents[2]}
    import os
    table.write_text(f'key,pdf_path,doi\nk,{os.path.relpath(pdf, roots[base])},10.1/k\n', encoding='utf-8-sig')
    assert common.sources(common.load_config(config))['k']['pdf'] == pdf


def test_ambiguous_path_requires_explicit_base(nested):
    config, table, pdf = nested
    table.write_text('key,pdf_path,doi\nk,paper.pdf,10.1/k\n', encoding='utf-8-sig')
    for root in (config.parent, table.parent):
        make_pdf(root / 'paper.pdf', [['Different paper']])
    with pytest.raises(SystemExit, match='ambiguous.*sources_path_base'):
        common.sources(common.load_config(config))
    settings = json.loads(config.read_text())
    settings['sources_path_base'] = 'source'
    config.write_text(json.dumps(settings))
    assert common.sources(common.load_config(config))['k']['pdf'] == table.parent / 'paper.pdf'


def test_multiple_paths_keep_first_existing_and_include_external_pdf(nested):
    config, table, pdf = nested
    extra = config.parents[2] / 'extra.pdf'
    make_pdf(extra, [['A second version']])
    table.write_text('key,pdf_path,doi\nk,missing.pdf; literature/pdfs/selected/Paper.pdf; extra.pdf,10.1/k\n', encoding='utf-8-sig')
    known = common.sources(common.load_config(config))
    assert known['k']['pdf'] == pdf
    assert known['k']['pdfs'][-1] == extra
    found = rank.find_pdfs([pdf.parent], known)
    assert found['k'] == pdf and extra in found.values()


def ballance_work():
    return {'doi': 'https://doi.org/10.1103/PhysRevLett.117.060504',
            'display_name': 'High-Fidelity Quantum Logic Gates Using Trapped-Ion Hyperfine Qubits',
            'publication_year': 2016, 'authorships': [{'author': {'display_name': 'C. J. Ballance'}}],
            'locations': [{'landing_page_url': 'https://arxiv.org/abs/1406.5473', 'version': 'submittedVersion'}]}


def test_early_pdf_version_separate_from_requested_publication(project, monkeypatch, capsys):
    early = project / 'early.pdf'
    make_pdf(early, [['Early report', 'arXiv:1406.5473v1 [quant-ph] 20 Jun 2014'], ['Second page']])
    monkeypatch.chdir(project)
    monkeypatch.setattr(fetch_pdf, 'openalex', lambda _: ballance_work())
    monkeypatch.setattr(fetch_pdf, 'fetch', lambda _: early.read_bytes())
    fetch_pdf.main(['10.1103/PhysRevLett.117.060504'])
    rec = json.loads((project / 'papers/new/fetch_log.jsonl').read_text())
    assert rec['requested_id'] == '10.1103/PhysRevLett.117.060504'
    assert rec['publication']['year'] == 2016
    assert rec['pdf_version'] == 'arxiv_v1'
    assert rec['pdf_arxiv_id'] == '1406.5473v1'
    assert rec['pdf_date'] == '20 Jun 2014'
    assert rec['identity_status'] == 'arxiv_header_matches_source'
    assert 'arxiv-1406.5473v1' in rec['file']
    assert 'arxiv_v1' in capsys.readouterr().out


def test_unknown_pdf_not_promoted_by_published_location(project, monkeypatch, capsys):
    pdf = project / 'unknown.pdf'
    make_pdf(pdf, [['Unidentified manuscript']])
    monkeypatch.chdir(project)
    work = ballance_work()
    work['locations'] = [{'pdf_url': 'https://example.org/paper.pdf', 'version': 'publishedVersion'}]
    monkeypatch.setattr(fetch_pdf, 'openalex', lambda _: work)
    monkeypatch.setattr(fetch_pdf, 'fetch', lambda _: pdf.read_bytes())
    fetch_pdf.main(['10.1103/PhysRevLett.117.060504'])
    rec = json.loads((project / 'papers/new/fetch_log.jsonl').read_text())
    assert rec['pdf_version'] == 'unknown' and rec['identity_status'] == 'unknown'
    assert rec['location_version'] == 'publishedVersion'
    assert 'version-unknown' in rec['file']
    assert 'version=unknown' in capsys.readouterr().out


def test_explicit_arxiv_version_not_dropped():
    assert fetch_pdf.candidates('1406.5473v1', None) == ['https://arxiv.org/pdf/1406.5473v1']


def test_absolute_missing_and_symlink_paths(nested):
    config, table, pdf = nested
    table.write_text(f'key,pdf_path,doi\nk,{pdf},10.1/k\nm,missing.pdf,10.1/m\n', encoding='utf-8-sig')
    known = common.sources(common.load_config(config))
    assert known['k']['pdf'] == pdf
    assert known['m']['pdf'] == config.parent / 'missing.pdf'
    (config.parent / 'same.pdf').symlink_to(pdf)
    (table.parent / 'same.pdf').symlink_to(pdf)
    table.write_text('key,pdf_path,doi\nk,same.pdf,10.1/k\n', encoding='utf-8-sig')
    assert common.sources(common.load_config(config))['k']['pdf'] == pdf


def test_repo_base_requires_repository(nested):
    config, table, pdf = nested
    (config.parents[2] / '.git').rmdir()
    cfg = common.load_config(config)
    cfg['sources_path_base'] = 'repo'
    with pytest.raises(SystemExit, match='requires a .git'):
        common.sources(cfg)


@pytest.mark.parametrize('url', ['https://arxiv.org/pdf/9999.12345v1', 'https://arxiv.org/pdf/1406.5473v2'])
def test_conflicting_arxiv_url_stays_unknown(project, url):
    pdf = project / 'stamp.pdf'
    make_pdf(pdf, [['arXiv:1406.5473v1 [quant-ph] 20 Jun 2014']])
    rec = fetch_pdf.pdf_provenance(pdf.read_bytes(), '10.1/p', ballance_work(), url)
    assert rec['pdf_version'] == 'unknown'
    assert rec['identity_status'] == 'conflicting_arxiv_identifiers'


def test_redirect_url_and_extraction_failure_are_recorded(project, monkeypatch):
    pdf = project / 'stamp.pdf'
    make_pdf(pdf, [['arXiv:1406.5473v1 [quant-ph] 20 Jun 2014']])
    data = fetch_pdf.Download(pdf.read_bytes(), 'https://arxiv.org/pdf/1406.5473v1')
    rec = fetch_pdf.pdf_provenance(data, '10.1/p', url='https://example.org/download')
    assert rec['source_url'] == 'https://example.org/download'
    assert rec['resolved_url'] == data.final_url
    assert rec['pdf_version'] == 'arxiv_v1'
    def unavailable(*args, **kwargs):
        raise FileNotFoundError('pdftotext unavailable')
    monkeypatch.setattr(fetch_pdf.subprocess, 'run', unavailable)
    rec = fetch_pdf.pdf_provenance(data, '10.1/p', url=data.final_url)
    assert rec['pdf_version'] == 'unknown' and rec['version_basis'] == 'text_extraction_unavailable'


def test_multiple_stamps_do_not_establish_identity(project):
    pdf = project / 'ambiguous.pdf'
    make_pdf(pdf, [['arXiv:1406.5473v1 [quant-ph] 20 Jun 2014',
                   'arXiv:1406.5473v2 [quant-ph] 20 Jun 2016']])
    assert fetch_pdf.pdf_provenance(pdf.read_bytes(), '10.1/p')['pdf_version'] == 'unknown'


def test_existing_legacy_filename_reports_real_version(project, monkeypatch, capsys):
    monkeypatch.chdir(project)
    dest = project / 'papers/new'
    dest.mkdir()
    work = ballance_work()
    ident = '10.1103/PhysRevLett.117.060504'
    pdf = dest / fetch_pdf.name_for(work, ident)
    make_pdf(pdf, [['arXiv:1406.5473v1 [quant-ph] 20 Jun 2014']])
    monkeypatch.setattr(fetch_pdf, 'openalex', lambda _: work)
    monkeypatch.setattr(fetch_pdf, 'fetch', lambda _: pytest.fail('legacy copy fetched twice'))
    fetch_pdf.main([ident])
    rec = json.loads((dest / 'fetch_log.jsonl').read_text())
    assert rec['pdf_version'] == 'arxiv_v1' and rec['status'] == 'HAVE'
    assert pdf.exists() and 'arxiv_v1' in capsys.readouterr().out


def test_distinct_unknown_versions_saved_and_repeat_deduplicated(project, monkeypatch):
    monkeypatch.chdir(project)
    pdf = project / 'temp.pdf'
    work = ballance_work()
    work['locations'] = [{'pdf_url': 'https://example.org/p.pdf'}]
    monkeypatch.setattr(fetch_pdf, 'openalex', lambda _: work)
    monkeypatch.setattr(fetch_pdf, 'fetch', lambda _: pdf.read_bytes())
    ident = '10.1103/PhysRevLett.117.060504'
    for text in ('First manuscript', 'Second manuscript', 'Second manuscript'):
        make_pdf(pdf, [[text]])
        fetch_pdf.main([ident])
    dest = project / 'papers/new'
    records = [json.loads(x) for x in (dest / 'fetch_log.jsonl').read_text().splitlines()]
    assert [r['status'] for r in records] == ['OK', 'OK', 'HAVE']
    assert len(list(dest.glob('*.pdf'))) == 2
    assert all(r['pdf_version'] == 'unknown' for r in records)


def test_pinned_version_rejects_unverified_pdf(project, monkeypatch):
    monkeypatch.chdir(project)
    monkeypatch.setattr(fetch_pdf, 'openalex', lambda _: None)
    pdf = project / 'temp.pdf'
    make_pdf(pdf, [['No identity stamp']])
    monkeypatch.setattr(fetch_pdf, 'fetch', lambda _: pdf.read_bytes())
    with pytest.raises(SystemExit):
        fetch_pdf.main(['1406.5473v1'])
    assert not list((project / 'papers/new').glob('*.pdf'))


def test_fetch_uses_second_valid_source_pdf(nested, monkeypatch, capsys):
    config, table, pdf = nested
    table.write_text('key,pdf_path,doi\nk,missing.pdf; literature/pdfs/selected/Paper.pdf,10.1/k\n', encoding='utf-8-sig')
    monkeypatch.setattr(fetch_pdf, 'openalex', lambda _: pytest.fail('existing second PDF ignored'))
    fetch_pdf.main(['--config', str(config), '10.1/k'])
    assert 'sources key k' in capsys.readouterr().out


def test_fetch_retains_actual_redirect_target(monkeypatch):
    import io
    class Response(io.BytesIO):
        headers = {}
        def geturl(self):
            return 'https://arxiv.org/pdf/1406.5473v1'
    monkeypatch.setattr(fetch_pdf, 'check_url', lambda _: None)
    monkeypatch.setattr(fetch_pdf.OPENER, 'open', lambda *a, **kw: Response(b'%PDF bytes'))
    data = fetch_pdf.fetch('https://example.org/download')
    assert data == b'%PDF bytes' and data.final_url == 'https://arxiv.org/pdf/1406.5473v1'
