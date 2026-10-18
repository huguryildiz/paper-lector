#!/bin/sh
# Download every question's PDFs with fetch_pdf.py; already held PDFs are not fetched twice, so rerun after failures.
PY=$(cd ../.. && pwd)/.venv/bin/python
for d in ls*/; do
  (cd "$d" && $PY ../../../scripts/fetch_pdf.py $(cat ids.txt) > fetch.out 2>&1; echo "$d $(grep -c '^OK' fetch.out) ok, $(grep -c '^MANUAL\|^ERROR' fetch.out) missing")
done
