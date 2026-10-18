#!/bin/sh
# Rank each question's 20-PDF subset with voyage (hybrid); outputs go to <question>/runs/.
PY=$(cd ../.. && pwd)/.venv/bin/python
for f in */subset20.csv; do
  q=${f%/subset20.csv}
  (cd "$q" && $PY ../../../scripts/rank.py --ids subset20.csv > rank20.out 2>&1; echo "$q exit $? $(grep -i 'tokens' rank20.out | tail -1)")
done
