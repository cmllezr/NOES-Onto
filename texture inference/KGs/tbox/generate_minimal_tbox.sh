#!/bin/bash
# Reproduces KGs/tbox/minimal_module.owl -- the minimal, reasoning-capable
# TBox module used by scripts/2_run_konclude_reasoning.sh,
# scripts/3_run_583_bisection.sh, and the HermiT scripts.
#
# Two steps:
#   1. ROBOT `extract --method BOT` (a locality-based module extractor) pulls
#      the 8 GRAIN_TYPES + 8 IDEAL_GRAIN_TYPES classes and their supporting
#      terms out of noes-full.owl (the release artifact -- NOT noes-base.owl,
#      which is ROBOT `relax`-ed for Protege editing and has had its
#      owl:equivalentClass definitions rewritten to plain rdfs:subClassOf,
#      which makes classification impossible: no reasoner can derive new
#      class membership from subClassOf alone).
#   2. A Python post-process strips the owl:inverseOf/owl:propertyChainAxiom
#      construct that ROBOT drags in on PMD_0025998 ("has relational
#      quality") as collateral -- it's not in the --term seed at all, but it
#      shares rdfs:range (BFO_0000145) with a seeded term, so BOT-locality
#      pulls in its full axiomatization anyway. That chain
#      (BFO_0000051 o PMD_0025998 subOf PMD_0025998) combined with the
#      inverse-role declaration is what caused Konclude's semi-filtered/full
#      ABox classification to return 0/N with no visible error -- see
#      scripts/3_run_583_bisection.sh for the scale-dependent version of the
#      same underlying issue (the chain being *present* is a correctness
#      bug; the 582/583 threshold is a separate, orthogonal scale bug in
#      Konclude itself, reproducible even with the chain already stripped).
#
# Requires: `robot` (https://robot.obolibrary.org/) on PATH, python3.
#
# Run from anywhere -- this script cds to "texture inference/" itself:
#   bash KGs/tbox/generate_minimal_tbox.sh

set -e
cd "$(dirname "$0")/../.."

SRC="../noes-full.owl"
OUT="KGs/tbox/minimal_module.owl"

echo "=== Extracting minimal module from $SRC ==="
robot extract --method BOT --input "$SRC" \
  --term "https://w3id.org/pmd/noes/NOES_0000167" \
  --term "https://w3id.org/pmd/noes/NOES_0000144" \
  --term "https://w3id.org/pmd/noes/NOES_0000135" \
  --term "https://w3id.org/pmd/noes/NOES_0000151" \
  --term "https://w3id.org/pmd/noes/NOES_0000162" \
  --term "https://w3id.org/pmd/noes/NOES_0000158" \
  --term "https://w3id.org/pmd/noes/NOES_0000157" \
  --term "https://w3id.org/pmd/noes/NOES_0000152" \
  --term "https://w3id.org/pmd/noes/NOES_0000058" \
  --term "https://w3id.org/pmd/noes/NOES_0000064" \
  --term "https://w3id.org/pmd/noes/NOES_0000060" \
  --term "https://w3id.org/pmd/noes/NOES_0000071" \
  --term "https://w3id.org/pmd/noes/NOES_0000139" \
  --term "https://w3id.org/pmd/noes/NOES_0000138" \
  --term "https://w3id.org/pmd/noes/NOES_0000113" \
  --term "https://w3id.org/pmd/noes/NOES_0000112" \
  --term "https://w3id.org/pmd/noes/NOES_0000141" \
  --term "https://w3id.org/pmd/noes/NOES_0000052" \
  --term "http://purl.obolibrary.org/obo/RO_0002503" \
  --term "https://w3id.org/pmd/co/PMD_0000077" \
  --term "https://w3id.org/pmd/co/PMD_0000663" \
  --term "http://purl.obolibrary.org/obo/OBI_0001931" \
  --term "http://purl.obolibrary.org/obo/OBI_0001937" \
  --term "http://purl.obolibrary.org/obo/IAO_0000039" \
  --output "$OUT"

echo "=== Stripping PMD_0025998's inverseOf/propertyChainAxiom (collateral from BOT locality via shared range BFO_0000145) ==="
python3 - "$OUT" <<'EOF'
import re
import sys

path = sys.argv[1]
with open(path, encoding="utf-8") as f:
    content = f.read()

before = content.count("propertyChainAxiom")

block_pattern = re.compile(
    r'<owl:ObjectProperty rdf:about="https://w3id\.org/pmd/co/PMD_0025998">.*?</owl:ObjectProperty>',
    re.DOTALL,
)
m = block_pattern.search(content)
assert m, "PMD_0025998 ObjectProperty block not found"
block = m.group(0)

cleaned = re.sub(r'\s*<owl:inverseOf rdf:resource="https://w3id\.org/pmd/co/PMD_0025999"/>', '', block)
cleaned = re.sub(r'\s*<owl:propertyChainAxiom rdf:parseType="Collection">.*?</owl:propertyChainAxiom>', '', cleaned, flags=re.DOTALL)

content = content[:m.start()] + cleaned + content[m.end():]

after = content.count("propertyChainAxiom")
print(f"propertyChainAxiom occurrences: {before} -> {after}")

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
EOF

echo "=== Sanity check ==="
grep -c "owl:equivalentClass" "$OUT" | xargs echo "equivalentClass axioms (should be > 0 -- confirms noes-full.owl, not noes-base.owl, was used):"
grep -c "propertyChainAxiom" "$OUT" | xargs echo "propertyChainAxiom occurrences (should be 0):"
echo "=== Wrote $OUT ==="
