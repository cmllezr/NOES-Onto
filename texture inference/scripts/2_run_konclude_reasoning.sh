#!/bin/bash
# Runs the full Konclude pipeline at each filter level -- none (unfiltered),
# semi (grain-level filter), full (pair-level filter) -- and reports how many
# of the 8 GRAIN_TYPES got classified at each level. Only "full" is expected
# to succeed (1644/1644); "none" and "semi" are expected to return 0/N -- a
# Konclude v0.7.0 scale threshold unrelated to ABox composition, see
# scripts/3_run_583_bisection.sh.
#
# Every step below is a codes/ebsd2rdf.py --stage call -- filter,
# merge-tbox, and merge-konclude are the same steps
# codes/filter_relevant_pairs.py, codes/merge_for_konclude.py, and
# codes/merge_konclude_results.py used to be as standalone scripts, now
# consolidated as EBSD2RDFPipeline methods so the whole pipeline (HermiT and
# Konclude paths alike) lives in one file.
#
# Per level:
#   1. Filter crystallites_texture.ttl to this level (skipped for "none" --
#      crystallites_texture.ttl is used directly).
#   2. Merge the (filtered) ABox with the TBox (KGs/tbox/minimal_module.owl).
#   3. Run Konclude realisation.
#   4. Print how many GRAIN_TYPES class assertions came back.
#   5. Merge Konclude's classifications back into the FULL ABox
#      (KGs/abox/crystallites_full.ttl -- has area triples, unlike the
#      texture-only file merged in step 2) -- this is the Konclude-path
#      equivalent of what ebsd2rdf.py's reason() does for HermiT, producing
#      a reasoned_ttl usable by --stage populations.
#   6. Run `ebsd2rdf.py --stage populations` on that reasoned ABox to build
#      the actual final graph -- grain populations + area fractions attached
#      to the material/microstructure individuals, mirroring Stage C of the
#      HermiT path (ebsd_texture_inferred.ttl).
#
# Requires (already in KGs/ before running):
#   - KGs/abox/crystallites_texture.ttl   (build with scripts/1_build_full_kg.sh)
#   - KGs/abox/crystallites_full.ttl      (built alongside it, same script)
#   - KGs/tbox/minimal_module.owl         (build with KGs/tbox/generate_minimal_tbox.sh)
#
# Logs go to texture inference/logs/.
#
# Run from anywhere -- this script cds to "texture inference/" itself:
#   bash scripts/2_run_konclude_reasoning.sh

set -e
cd "$(dirname "$0")/.."
mkdir -p logs

CLASSES="NOES_0000167\|NOES_0000144\|NOES_0000135\|NOES_0000151\|NOES_0000162\|NOES_0000158\|NOES_0000157\|NOES_0000152"

for level in none semi full; do
    echo "=== Level: $level ==="

    if [ "$level" = "none" ]; then
        abox="KGs/abox/crystallites_texture.ttl"
    else
        abox="KGs/abox/abox_${level}.ttl"
        echo "--- 1. Filtering (level=$level) ---"
        python codes/ebsd2rdf.py --stage filter --filter-level "$level" --filtered-ttl "$abox"
    fi

    echo "--- 2. Merging with TBox ---"
    python codes/ebsd2rdf.py --stage merge-tbox --merge-source "$abox" --merged-ttl "KGs/merged/merged_${level}.ttl"

    echo "--- 3. Running Konclude realisation ---"
    /usr/bin/time -v realisation -i "KGs/merged/merged_${level}.ttl" -o "KGs/reasoned/reasoned_${level}.owl" \
        2> "logs/konclude_${level}.log"
    grep -E "User time|System time|Elapsed|Maximum resident" "logs/konclude_${level}.log"

    echo "--- 4. Classification count ---"
    n=$(grep -c "$CLASSES" "KGs/reasoned/reasoned_${level}.owl" || true)
    echo "$level: $n GRAIN_TYPES class-assertion lines"

    echo "--- 5. Merging classifications into the full ABox (reasoned checkpoint) ---"
    python codes/ebsd2rdf.py --stage merge-konclude \
        --konclude-output "KGs/reasoned/reasoned_${level}.owl" \
        --reasoned-ttl "KGs/reasoned/reasoned_abox_${level}.ttl"

    echo "--- 6. Building the final graph (populations + area fractions) ---"
    python codes/ebsd2rdf.py --stage populations \
        --reasoned-ttl "KGs/reasoned/reasoned_abox_${level}.ttl" \
        --output "KGs/reasoned/ebsd_texture_inferred_${level}.ttl"
done
