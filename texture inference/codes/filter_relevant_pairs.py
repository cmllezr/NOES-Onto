"""
One-off Konclude-scoped experiment -- NOT part of the regular pipeline and
not what --relevant-only does. Takes an already-built texture-subgraph
Turtle file (crystallites_texture.ttl, built WITHOUT --relevant-only so it
has all 8 texture relations per grain) and filters it down to only the
(grain, misorientation-angle) pairs whose angle actually satisfies the
ontology's tolerance restriction (<= 15 deg) -- i.e. only the pairs that
could ever contribute to a GRAIN_TYPES inference, dropping every relation
that's structurally present but numerically inert.

This is strictly smaller than what --relevant-only produces: that flag
keeps a grain's *entire* 8-relation set if any one of them qualifies; this
script keeps only the qualifying relation(s) themselves. Kept separate
from ebsd2rdf.py deliberately (see conversation: --relevant-only is meant
to preserve full per-grain orientation data, this is a scoped test of
whether a much smaller ABox is something Konclude can actually reason over
correctly).

Usage:
    python filter_relevant_pairs.py <crystallites_texture.ttl> <output.ttl>
"""
import sys
from pathlib import Path

import rdflib

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ebsd2rdf import (  # noqa: E402
	CRYSTALLITE_CLASS,
	HAS_NUMERIC_VALUE,
	HAS_RELATIONAL_QUALITY,
	MISORIENTATION_ANGLE_TOLERANCE,
	SPECIFIED_BY_VALUE,
)
from rdflib.namespace import RDF  # noqa: E402


def filter_relevant_pairs(source: rdflib.Graph) -> rdflib.Graph:
	kept = rdflib.Graph()
	for grain, _, miso in source.triples((None, HAS_RELATIONAL_QUALITY, None)):
		svs = next(source.objects(miso, SPECIFIED_BY_VALUE), None)
		if svs is None:
			continue
		angle = next(source.objects(svs, HAS_NUMERIC_VALUE), None)
		if angle is None or float(angle) > MISORIENTATION_ANGLE_TOLERANCE:
			continue

		kept.add((grain, RDF.type, CRYSTALLITE_CLASS))
		kept.add((grain, HAS_RELATIONAL_QUALITY, miso))
		for p, o in source.predicate_objects(miso):
			kept.add((miso, p, o))
			if p == SPECIFIED_BY_VALUE:
				for svs_p, svs_o in source.predicate_objects(o):
					kept.add((o, svs_p, svs_o))
	return kept


def main() -> None:
	if len(sys.argv) != 3:
		print("Usage: python filter_relevant_pairs.py <crystallites_texture.ttl> <output.ttl>")
		sys.exit(1)
	source_path, output_path = sys.argv[1], sys.argv[2]

	source = rdflib.Graph()
	source.parse(source_path, format="turtle")
	print(f"Loaded {len(source)} triples from {source_path}")

	all_pairs = len(list(source.triples((None, HAS_RELATIONAL_QUALITY, None))))
	kept = filter_relevant_pairs(source)
	kept_pairs = len(list(kept.triples((None, HAS_RELATIONAL_QUALITY, None))))
	print(f"Kept {kept_pairs}/{all_pairs} (grain, misorientation-angle) pairs "
	      f"({len(kept)} triples total)")

	# Carry over the ideal-texture individuals' own rdf:type triples --
	# needed so HermiT/Konclude can see the "towards some <IDEAL_X>"
	# restriction is satisfied, same reason extract_texture_subgraph() does
	# this. Cheap to just grab every ex:ideal_* type triple from source
	# rather than re-deriving which ones are actually referenced.
	for s, p, o in source.triples((None, RDF.type, None)):
		if str(s).startswith("http://example.org/ideal_"):
			kept.add((s, p, o))

	kept.serialize(destination=output_path, format="turtle")
	print(f"Wrote {len(kept)} triples to {output_path}")


if __name__ == "__main__":
	main()
