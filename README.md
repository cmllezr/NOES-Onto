![Build Status](https://github.com/cmllezr/NOES-Onto/actions/workflows/qc.yml/badge.svg)

# NOES-Onto: Nonoriented Electrical Steel Ontology

NOES-Onto is an application-level ontology in the Materials Science and Engineering domain, focused on semantic modeling of **Process–Structure–Property (PSP)** dependencies of nonoriented electrical steels (NOES). It is built on the [Platform Material Digital Core Ontology (PMDco)](https://github.com/materialdigital/core-ontology) and developed with the [Ontology Development Kit (ODK)](https://github.com/INCATools/ontology-development-kit).

Beyond the ontology itself, this repository includes a full **EBSD-to-RDF texture inference pipeline** (`texture inference/`) that builds knowledge graphs from real crystallographic texture measurements, reasons over them with [Konclude](https://github.com/konclude/Konclude), and documents a reproducible Konclude scale-threshold bug found along the way.

## Table of contents

- [What's in this repository](#whats-in-this-repository)
- [Ontology releases](#ontology-releases)
- [Competency questions & usage examples](#competency-questions--usage-examples)
- [Texture inference pipeline](#texture-inference-pipeline)
- [Quality checks](#quality-checks)
- [Setup](#setup)
- [Contributing](#contributing)
- [License](#license)
- [Contact](#contact)

## What's in this repository

| Path | What it is |
|---|---|
| `src/ontology/` | ODK-managed editors' workspace. `noes-edit.owl` is **the** file to edit; `components/` holds the modular axiom files (manufacturing, characterization, texture, materials, shared); `Makefile`/`noes.Makefile` build the release artifacts; `imports/` and `mirror/` hold generated/cached import modules. |
| `noes.owl`, `noes-full.owl/ttl`, `noes-base.owl/ttl`, `noes-simple.owl/ttl` | Release artifacts mirrored to repo root from `src/ontology/` (see [Ontology releases](#ontology-releases)). |
| `SPARQL queries/` | One `.ttl`-embedded SPARQL query per competency question (CQ) the ontology is designed to answer (chemical composition, manufacturing history, grain size, texture components, property interplay, ...). |
| `usage examples/` | Worked example ABox graphs per domain area (chemical composition, magnetic/mechanical properties, manufacturing process, crystallographic texture, anisotropy of properties), each paired with a `... reasoned.ttl` counterpart showing the reasoner's inferred facts. Several areas have multiple numbered examples. |
| `texture inference/` | Standalone pipeline: EBSD grain-orientation data → RDF knowledge graph → reasoning (HermiT/Konclude) → texture classification + area fractions. See [below](#texture-inference-pipeline). |
| `quality checks/` | Ontology quality assessment: `quality_checks.sh` runs ROBOT's `measure`/`report`; `foops.py` runs the [FOOPS!](https://foops.linkeddata.es/) ontology pitfall assessment. |
| `pages/` | Generated documentation site (WIDOCO/ODK docs), published via GitHub Pages. Not hand-edited. |
| `.github/workflows/` | CI: quality checks (`qc.yml`), releases (`release.yml`), docs build (`docs.yml`), ontology metrics (`onto_metrics.yml`), ODK repo sync (`update_repo.yml`, `seed-odk.yml`). |
| `requirements.txt` | Python dependencies for the texture inference pipeline and quality checks (`rdflib`, `owlready2`, `orix`, `numpy`, `pandas`, `requests`). |
| `CONTRIBUTING.md` | How to report issues, request terms, and submit edits. |
| `LICENSE.txt` | CC BY 4.0. |

## Ontology releases

| File | Contents |
|---|---|
| `noes-full.owl/ttl` | Complete ontology with all imports and full axiomatization. |
| `noes-base.owl/ttl` | Core entities without extended imports. Note: built with ROBOT's `relax`, so class definitions here are `rdfs:subClassOf`-only (`owl:equivalentClass` axioms are rewritten out) — good for browsing/editing, **not sufficient on its own for reasoner-driven classification**. |
| `noes-simple.owl/ttl` | Simplified version with basic subclass and existential axioms. |
| `noes.owl/ttl` | Main ontology file; currently the full version. |

The latest stable release is published at **https://w3id.org/pmd/noes.owl** (pending [OBO Foundry](http://obofoundry.org) approval).

Editors should only ever touch **`src/ontology/noes-edit.owl`** — see [CONTRIBUTING.md](CONTRIBUTING.md) for the full edit → branch → PR workflow.

## Competency questions & usage examples

`SPARQL queries/` holds one query per competency question the ontology is meant to answer (e.g. *CQ1: chemical composition*, *CQ6: grain size*, *CQ8: texture components*, *CQ13: interplay between magnetic and mechanical properties*). The images show the outputs of selected queriees. `usage examples/` holds hand-built example ABox graphs these queries can be run against, each with a `reasoned` counterpart so you can compare asserted vs. inferred facts.

## Texture inference pipeline

`texture inference/` turns raw EBSD grain-orientation measurements (per grain, not per pixel) into a reasoned NOES-Onto knowledge graph, classifying each grain into one of 8 texture components (cube, Goss, rotated cube, rotated Goss, alpha/gamma/eta/lambda fiber) by misorientation angle, then computing area fractions per texture. The examplary dataset can be found [here](https://data.mendeley.com/datasets/d24fmr56db/1).

```
texture inference/
├── data/                 CSVs computed from .txt input file (euler2hkl.py's output)
├── codes/                 the whole pipeline: ebsd2rdf.py (build/filter/merge/reason/populate
│                          stages), euler2hkl.py (misorientation-angle computation via orix),
│                          extract_grain_slice.py (bisection tooling)
├── sparql/                SPARQL CONSTRUCT queries ebsd2rdf.py runs
├── scripts/                orchestration: build → filter → reason → populate, plus Konclude setup
├── KGs/
│   ├── abox/               ABox-only graphs (unfiltered and filtered variants)
│   ├── tbox/                minimal, reasoning-capable TBox module + its ROBOT generation script
│   ├── merged/              TBox+ABox merged files, ready for Konclude
│   └── reasoned/            reasoner outputs and the final texture-inferred graphs
└── logs/                   Konclude/HermiT run logs
```

### Running it

```bash
cd "texture inference"
bash scripts/setup_konclude.sh          # one-time: installs Konclude, persists $KONCLUDE_BIN in ~/.bashrc
bash scripts/0_run_euler2hkl.sh         # EBSD.txt -> data/*.csv (misorientation angles per grain)
bash scripts/1_build_full_kg.sh         # CSV -> KGs/abox/crystallites_texture.ttl + crystallites_full.ttl
bash scripts/2_run_konclude_reasoning.sh  # filter -> merge -> Konclude -> merge results -> final graph,
                                           # at each of 3 filter levels (none/semi/full)
```

Every step above is also callable directly via `python codes/ebsd2rdf.py --stage {crystallites,filter,merge-tbox,reason,classify-direct,merge-konclude,populations,all}` — see its `--help` for the full flag set.

### A known Konclude limitation, reproduced here

While validating this pipeline, we found that [Konclude](https://github.com/konclude/Konclude) v0.7.0-1138 silently returns **0 classifications** (no error) once the reasoned ABox crosses **exactly 583 grains** in this workload — 582 grains classifies correctly, 583 does not. This was isolated to be independent of grain composition (a different 580-grain subset still succeeds), thread count (`-w AUTO` fails identically), and ABox serialization. `scripts/3_run_583_bisection.sh` reproduces the exact bisection that found this threshold, corroborated by an [open, unaddressed Konclude issue](https://github.com/konclude/Konclude/issues/19) reporting a related symptom. `KGs/tbox/generate_minimal_tbox.sh` also documents a separate, now-fixed correctness bug: a `PMD_0025998` property chain + inverse-role combination inherited from PMDco that made classification fail regardless of scale, until stripped.

## Quality checks

```bash
cd "quality checks"
bash quality_checks.sh   # ROBOT measure (expressivity) + ROBOT report, against noes-full.owl
python foops.py          # FOOPS! ontology pitfall assessment (needs `requests`, network access)
```

Both also run in CI via `.github/workflows/qc.yml`.

## Setup

```bash
pip install -r requirements.txt   # rdflib, owlready2, orix, numpy, pandas, requests
```

You'll also need [ROBOT](https://robot.obolibrary.org/) on `PATH` for anything that builds ontology releases or the minimal TBox module, and Konclude (`texture inference/scripts/setup_konclude.sh` installs it) if you want to reproduce the Konclude side of the texture inference pipeline.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to report problems, request new terms, or submit an edit. Please use the GitHub [Issue Tracker](https://github.com/cmllezr/NOES-Onto/issues) rather than emailing maintainers directly.

## License

Released under [CC BY 4.0](LICENSE.txt).

## Contact

Please use this repository's [Issue tracker](https://github.com/cmllezr/NOES-Onto/issues) to request new terms/classes or report errors or specific concerns related to the ontology.

## Acknowledgements

This ontology repository was created using the [Ontology Development Kit (ODK)](https://github.com/INCATools/ontology-development-kit).
