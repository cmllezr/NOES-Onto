#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ONT="$SCRIPT_DIR/../noes-full.owl"
SPARQL="$SCRIPT_DIR/../src/sparql/noes_terms.sparql"
OUT="$SCRIPT_DIR"          # or a dedicated $SCRIPT_DIR/reports

echo "Running expressivity measure..."
robot measure \
  --input "$ONT" \
  --metrics extended \
  --output "$OUT/expressivity.txt"

echo "Filtering NOES-only terms..."
robot query \
  --input "$ONT" \
  --query "$SPARQL" "$OUT/noes_terms.csv"

echo "Counting NOES terms and assessing quality..."
robot filter \
  --input "$ONT" \
  --term-file "$OUT/noes_terms.csv" \
  --select "self annotations" \
  measure \
  --output "$OUT/metrics-full-noes-only.tsv" \
  report \
  --fail-on none \
  --labels true \
  --output "$OUT/noes-report.html"

echo "All checks completed successfully!"