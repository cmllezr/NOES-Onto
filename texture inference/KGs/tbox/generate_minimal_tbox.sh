#!/bin/bash
# Reproduces KGs/tbox/minimal_module.owl -- the minimal, reasoning-capable
# TBox module used by scripts/2_run_konclude_reasoning.sh,
# scripts/3_run_583_bisection.sh, and the HermiT scripts.
#
# One chained ROBOT invocation, two commands:
#   1. `extract --method BOT` (a locality-based module extractor) pulls the
#      8 GRAIN_TYPES + 8 IDEAL_GRAIN_TYPES classes and their supporting
#      terms, listed in minimal_module_terms.txt, out of noes-full.owl (the
#      release artifact -- NOT noes-base.owl, which is ROBOT `relax`-ed for
#      Protege editing and has had its owl:equivalentClass definitions
#      rewritten to plain rdfs:subClassOf, which makes classification
#      impossible: no reasoner can derive new class membership from
#      subClassOf alone).
#   2. `remove --term PMD_0025998 --axioms SubPropertyChainOf --axioms
#      InverseObjectProperties` strips just those two axiom types where they
#      mention PMD_0025998 ("has relational quality") -- ROBOT's `remove`
#      only touches an axiom if it's BOTH one of the given --axioms types
#      AND has one of the given --term IRIs in its signature, so this keeps
#      PMD_0025998's own declaration/domain/range (still used as a
#      predicate in the ABox) while dropping only the chain + inverse-role
#      construct. PMD_0025998 isn't in the --term-file seed at all -- it's
#      pulled in as BOT-locality collateral, sharing rdfs:range
#      (BFO_0000145) with a seeded term -- so this remove step always has
#      something to do regardless of what's in the term file. That chain
#      (BFO_0000051 o PMD_0025998 subOf PMD_0025998) combined with the
#      inverse-role declaration is what caused Konclude's semi-filtered/full
#      ABox classification to return 0/N with no visible error -- see
#      scripts/3_run_583_bisection.sh for the scale-dependent version of the
#      same underlying issue (the chain being *present* is a correctness
#      bug; the 582/583 threshold is a separate, orthogonal scale bug in
#      Konclude itself, reproducible even with the chain already stripped).
#
# Requires: `robot` (https://robot.obolibrary.org/) on PATH.
#
# Run from anywhere -- this script cds to "texture inference/" itself:
#   bash KGs/tbox/generate_minimal_tbox.sh

set -e
cd "$(dirname "$0")/../.."

SRC="../noes-full.owl"
TERMS="KGs/tbox/minimal_module_terms.txt"
OUT="KGs/tbox/minimal_module.owl"

echo "=== Extracting minimal module from $SRC, stripping PMD_0025998's chain/inverse ==="
robot extract --method BOT --input "$SRC" --term-file "$TERMS" \
  remove --term "https://w3id.org/pmd/co/PMD_0025998" \
         --axioms SubPropertyChainOf --axioms InverseObjectProperties \
  --output "$OUT"

echo "=== Sanity check ==="
grep -c "owl:equivalentClass" "$OUT" | xargs echo "equivalentClass axioms (should be > 0 -- confirms noes-full.owl, not noes-base.owl, was used):"
grep -c "propertyChainAxiom" "$OUT" | xargs echo "propertyChainAxiom occurrences (should be 0):"
grep -c "PMD_0025998" "$OUT" | xargs echo "PMD_0025998 occurrences (should be > 0 -- confirms the property itself, just not its chain/inverse, survived):"
echo "=== Wrote $OUT ==="
