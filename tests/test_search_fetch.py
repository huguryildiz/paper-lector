import fetch_pdf
import openalex_search


def test_record_rebuilds_abstract_and_marks_known_doi():
    w = {'id': 'https://openalex.org/W1', 'doi': 'https://doi.org/10.1/Q', 'display_name': 'T', 'publication_year': 2022,
         'primary_location': {'source': {'display_name': 'Venue'}}, 'best_oa_location': {'pdf_url': 'http://x/p.pdf'},
         'locations': [{'landing_page_url': 'https://arxiv.org/abs/2205.06300'}],
         'authorships': [{'author': {'display_name': 'A. Chandra'}}],
         'abstract_inverted_index': {'world': [1], 'hello': [0]}}
    r = openalex_search.record(w, {'10.1/q': 'queue2022'})
    assert r['abstract'] == 'hello world' and r['in_sources'] == 'queue2022'
    assert r['arxiv'] == '2205.06300' and r['oa_pdf'] == 'http://x/p.pdf' and r['openalex'] == 'W1'


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
    monkeypatch.setattr(fetch_pdf, 'fetch', lambda url: fetched.append(url) or b'%PDF-1.4 x')
    fetch_pdf.main(['10.1/q', '10.9/a', '10.9/b'])
    out = capsys.readouterr().out
    assert 'HAVE    10.1/q -> sources key queue2022' in out           # held DOI: no lookup, no download
    assert fetched == ['http://oa/10.9/a', 'http://oa/10.9/b']
    assert len(list((project / 'papers/new').glob('Zhang2023_DeepRouting_*.pdf'))) == 2
