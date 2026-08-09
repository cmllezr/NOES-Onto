#!/usr/bin/env bash

# Exit immediately if any command fails
set -e

echo "Starting ROBOT quality checks..."

# 1. Measure expressivity and base metrics
echo "Running expressivity measure..."
robot measure \
  --input noes-full.owl \
  --metrics extended \
  --output expressivity.txt

# 2. Extract ontology terms using SPARQL query
echo "Filtering NOES-only terms..."
robot query \
  --input noes-full.owl \
  --query ../src/sparql/noes_terms.sparql \
  noes_terms.csv

# 3. Filter ontology terms and generate metrics for NOES terms only
echo "Counting NOES terms and assessing quality..."
robot filter \
  --input noes-full.owl \
  --term-file noes_terms.csv \
  --select "self annotations" \
  measure \
  --output metrics-full-noes-only.tsv \
  report \
  --fail-on none \
  --labels true \
  --output noes-report.html 

echo "All checks completed successfully!"