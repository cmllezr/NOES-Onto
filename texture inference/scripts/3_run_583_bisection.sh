#!/bin/bash
# Reproduces the Konclude scale-threshold bisection on the semi-filtered
# ABox: 582 grains classify correctly (matching the pure-Python baseline),
# 583 grains give 0/N -- an exact, single-grain, composition- and
# thread-count-independent threshold in Konclude v0.7.0-1138.
#
# Per grain count N, 4 steps:
#   1. Create a semi-filtered graph with N grains (slice of the full
#      semi-filtered ABox, KGs/abox/abox_semi.ttl).
#   2. Merge with the TBox.
#   3. Run Konclude realisation.
#   4. Print how many of the 8 GRAIN_TYPES got classified.
#
# Also includes:
#   - A composition-independence ("swap") check: a different 580-grain
#     subset (skipping the first 10, including the whole 580-590 suspect
#     window instead) still succeeds -- ruling out "one bad grain" in favor
#     of a genuine count threshold.
#   - A thread-count-independence check: 583 with -w AUTO (multi-threaded)
#     still fails identically to the default single-threaded run.
#
# Requires (already in KGs/ before running):
#   - KGs/abox/abox_semi.ttl   (build with scripts/2_run_konclude_reasoning.sh)
#   - KGs/tbox/minimal_module.owl
#
# Logs go to texture inference/logs/.
#
# Run from anywhere -- this script cds to "texture inference/" itself:
#   bash scripts/3_run_583_bisection.sh

set -e
cd "$(dirname "$0")/.."
mkdir -p logs

CLASSES="NOES_0000167\|NOES_0000144\|NOES_0000135\|NOES_0000151\|NOES_0000162\|NOES_0000158\|NOES_0000157\|NOES_0000152"

run_slice() {
    # $1 = name suffix (e.g. "bisect_583"), $2 = --count, $3 = extra extract_grain_slice.py args (e.g. --skip 10)
    local name="$1" count="$2" extra="$3"
    local abox="KGs/abox/abox_semi_${name}.ttl"

    echo "--- 1. Slicing $count grains ($name) ---"
    python codes/extract_grain_slice.py KGs/abox/abox_semi.ttl "$abox" --count "$count" $extra

    echo "--- 2. Merging with TBox ---"
    python codes/ebsd2rdf.py --stage merge-tbox --merge-source "$abox" --merged-ttl "KGs/merged/merged_semi_${name}.ttl"

    echo "--- 3. Running Konclude realisation ---"
    $KONCLUDE_BIN realisation -i "KGs/merged/merged_semi_${name}.ttl" -o "KGs/reasoned/reasoned_semi_${name}.owl" \
        2> "logs/konclude_semi_${name}.log"

    echo "--- 4. Classification count ---"
    local n
    n=$(grep -c "$CLASSES" "KGs/reasoned/reasoned_semi_${name}.owl" || true)
    echo "$name ($(wc -l < "$abox") ABox lines): $n"
}

echo "=== 1. Coarse bisection ==="
for n in 10 50 200 500 550 560 570 580 590 600 700 900; do
    run_slice "bisect_$n" "$n" ""
done

echo "=== 2. Fine bisection around 580-590 ==="
for n in 581 582 583 585 587; do
    run_slice "bisect_$n" "$n" ""
done

echo "=== 3. Composition-independence check (swap test) ==="
echo "580 grains total, but skipping the first 10 (includes the 580-590 window instead of excluding it)"
run_slice "swap_580" 580 "--skip 10"

echo "=== 4. Thread-count independence check (n=583 with -w AUTO) ==="
$KONCLUDE_BIN realisation -w AUTO -i KGs/merged/merged_semi_bisect_583.ttl -o KGs/reasoned/reasoned_semi_bisect_583_multithread.owl \
    2> logs/konclude_semi_bisect_583_multithread.log
n=$(grep -c "$CLASSES" KGs/reasoned/reasoned_semi_bisect_583_multithread.owl || true)
echo "bisect_583 (-w AUTO, multi-threaded): $n"

echo "=== Summary: expect 582 and below to succeed, 583 and above (any composition, any thread count) to fail ==="
