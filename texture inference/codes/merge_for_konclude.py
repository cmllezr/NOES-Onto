"""
Merges the NOES TBox with an ABox Turtle file (e.g. crystallites_texture.ttl)
into a single Turtle file, for koncludix.py / Konclude's sparqlfile mode --
unlike HermitReasoner's owlready2 setup, which loads the TBox (from a URL)
and ABox (from a local file) as two separate documents, koncludix.py parses
one ontology file and expects everything in it.

The source ABox's own owl:imports/owl:Ontology annotation (added by
ebsd2rdf.py's _dump_abox()) is dropped before merging -- it's now redundant
(the TBox is inlined, not imported) and, more importantly, having it in the
merged file gives Konclude/Redland a live URL it might try to resolve at
load time, which is something to avoid on a compute node without outbound
network access.

Usage:
    python merge_for_konclude.py <abox.ttl> <merged_output.ttl>
"""
import sys

import rdflib
from rdflib.namespace import OWL, RDF

TBOX_URL = "../noes-base.owl"
EX = rdflib.Namespace("http://example.org/")


def main() -> None:
	if len(sys.argv) != 3:
		print("Usage: python merge_for_konclude.py <abox.ttl> <merged_output.ttl>")
		sys.exit(1)
	abox_path, output_path = sys.argv[1], sys.argv[2]

	g = rdflib.Graph()
	print(f"Loading TBox from {TBOX_URL} ...")
	g.parse(TBOX_URL, format="xml")
	print(f"  {len(g)} triples after TBox")

	print(f"Loading ABox from {abox_path} ...")
	g.parse(abox_path, format="turtle")
	print(f"  {len(g)} triples after merge")

	ontology_iri = EX.ontology
	g.remove((ontology_iri, RDF.type, OWL.Ontology))
	g.remove((ontology_iri, OWL.imports, None))

	g.serialize(destination=output_path, format="turtle")
	print(f"Wrote merged TBox+ABox to {output_path}")


if __name__ == "__main__":
	main()
