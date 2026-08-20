#!/bin/bash
# Step 0 of the pipeline: runs euler2hkl.py on EBSD.txt to compute, per
# grain, the misorientation angle to each of the 8 ideal textures (orix).
# Writes data/grain_misorientation.csv (consumed by
# scripts/1_build_full_kg.sh) and data/grain_texture_classification.csv.
#
# euler2hkl.py uses paths relative to codes/ (DATA_FILE = "../EBSD.txt",
# OUT_DIR = "../data/"), so this script runs it from there rather than
# passing CLI args -- it doesn't take any.
#
# Run from anywhere -- this script cds to "texture inference/codes/" itself:
#   bash scripts/0_run_euler2hkl.sh

set -e
cd "$(dirname "$0")/../codes"

python euler2hkl.py

echo "=== data/grain_misorientation.csv and data/grain_texture_classification.csv built ==="
wc -l ../data/grain_misorientation.csv ../data/grain_texture_classification.csv
