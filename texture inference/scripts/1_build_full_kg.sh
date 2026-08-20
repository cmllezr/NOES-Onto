#!/bin/bash
# Step 1 of the pipeline: build the dense, unfiltered ABox. ebsd2rdf.py's
# --stage crystallites writes two checkpoints from the same build:
#   - KGs/abox/crystallites_texture.ttl -- every grain x all 8 ideal
#     textures, no area triples (2290 grains, 18320 misorientation-angle
#     pairs). This is the single source scripts/2_run_konclude_reasoning.sh
#     derives the none/semi/full filter-level variants from, and what gets
#     merged with the TBox for reasoning.
#   - KGs/abox/crystallites_full.ttl -- the same grains + misorientation
#     angles, PLUS area triples. Never reasoned over directly (no reasoning
#     needed for area), but this is what a reasoner's classification results
#     get merged back into afterward (see ebsd2rdf.py's --stage
#     merge-konclude / reason()) -- --stage populations needs the area
#     triples to compute area fractions.
#
# Run from anywhere -- this script cds to "texture inference/" itself:
#   bash scripts/1_build_full_kg.sh

set -e
cd "$(dirname "$0")/.."

python codes/ebsd2rdf.py --stage crystallites

echo "=== KGs/abox/crystallites_texture.ttl built ==="
wc -l KGs/abox/crystallites_texture.ttl
n_pairs=$(grep -c "PMD_0025998" KGs/abox/crystallites_texture.ttl || true)
echo "PMD_0025998 (has relational quality) subject lines: $n_pairs"

echo "=== KGs/abox/crystallites_full.ttl built ==="
wc -l KGs/abox/crystallites_full.ttl
