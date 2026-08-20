#!/bin/bash
#SBATCH --job-name=hermit-bisect
#SBATCH --cpus-per-task=2
#SBATCH --mem=12G
#SBATCH --time=01:00:00
#SBATCH --output=logs/hermit-bisect.log

cd "$SLURM_SUBMIT_DIR"

for n in 10 50 200 500; do
    echo "=== bisect_$n (minimal_module.owl, chains: PMD_0025999 + NOES_0000068) ==="
    timeout 300 /usr/bin/time -v python codes/ebsd2rdf.py --stage reason \
        --owl-ontology-url "file:///$(pwd)/KGs/tbox/minimal_module.owl" \
        --texture-ttl "$(pwd)/KGs/abox/abox_semi_bisect_$n.ttl" \
        --reasoned-ttl "$(pwd)/KGs/reasoned/texture_semi_bisect_${n}_hermit.ttl" \
        --java-memory 8000
    echo "exit code: $?"
done

echo "=== full semi, 1083 grains (minimal_module_nochains.owl, all chains stripped) ==="
timeout 1800 /usr/bin/time -v python codes/ebsd2rdf.py --stage reason \
    --owl-ontology-url "file:///$(pwd)/KGs/tbox/minimal_module_nochains.owl" \
    --texture-ttl "$(pwd)/KGs/abox/abox_semi.ttl" \
    --reasoned-ttl "$(pwd)/KGs/reasoned/texture_semi_nochains_hermit.ttl" \
    --java-memory 8000
echo "exit code: $?"
