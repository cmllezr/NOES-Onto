#!/bin/bash
#SBATCH --job-name=hermit-semi
#SBATCH --cpus-per-task=2
#SBATCH --mem=12G
#SBATCH --time=00:30:00
#SBATCH --output=logs/hermit-semi.log

cd "$SLURM_SUBMIT_DIR"

/usr/bin/time -v python codes/ebsd2rdf.py --stage reason \
    --owl-ontology-url "file:///$(pwd)/KGs/tbox/minimal_module.owl" \
    --texture-ttl "$(pwd)/KGs/abox/abox_semi.ttl" \
    --reasoned-ttl "$(pwd)/KGs/reasoned/texture_semi_hermit.ttl" \
    --java-memory 8000
