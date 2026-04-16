
![Build Status](https://github.com/cmllezr/NOES-Onto/actions/workflows/qc.yml/badge.svg)
# NOES Onto: Nonoriented Electrical Steel Ontology

Description: NOES-Onto is an application-level ontology in Material Science and Engineering domain focusing on semantic modeling of Process-Structure-Property (PSP) dependencies of nonoriented electrical steels (NOES). NOES-Onto is based on the third version of the [Platform Material Digital Core Ontology (PMDco)](https://github.com/materialdigital/core-ontology).

## File Structure

This folder provides the modular implementation of ImageTransformation, developed and maintained using the [Ontology Development Kit (ODK)](https://github.com/INCATools/ontology-development-kit).

### Directories
* **src/:** Main development folder generated and managed through ODK.
  * **ontology/components/:** – Modular ontology components (manufacturing, characterization, texture).
  * **ontology/noes-edit.owl:** – Primary editable ontology file used during development (ontology editors' version).

### Ontology versions
* **noes-full.owl/ttl:** Complete ontology with all imports and full axiomatization.
* **noes-base.owl/ttl:** Core entities without extended imports.
* **noes-simple.owl/ttl:** Simplified version with basic subclass and existential axioms.
* **noes.owl/ttl:** Main ontology file contains the full version.

### Other files
* README.md, LICENSE.txt, CONTRIBUTING.md – Project overview, license, and contribution guidelines.

## Versions

### Stable release versions

The latest version of the ontology can always be found at:

https://w3id.org/pmd/noes.owl

(note this will not show up until the request has been approved by obofoundry.org)

### Editors' version

Editors of this ontology should use the edit version, [src/ontology/noes-edit.owl](src/ontology/noes-edit.owl)

## Contact

Please use this GitHub repository's [Issue tracker](https://github.com/cmllezr/NOES-Onto/issues) to request new terms/classes or report errors or specific concerns related to the ontology.

## Acknowledgements

This ontology repository was created using the [Ontology Development Kit (ODK)](https://github.com/INCATools/ontology-development-kit).
