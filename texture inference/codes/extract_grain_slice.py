"""
Extracts a size-limited slice of grains (and their full 8-relation
misorientation-angle subgraphs) from an already-built texture ABox, for
Konclude scale-threshold bisection testing.

Grains are ordered by sorted(str(uri)) -- lexicographic string sort on
"http://example.org/grain_N", NOT numeric grain-ID order -- so "first N" is
a deterministic but essentially arbitrary subset with respect to grain
properties. This was confirmed not to bias the bisection results: a 580-grain
slice that skips the first 10 (via --skip) and a 580-grain slice that takes
the first 580 both classify correctly, ruling out "one specific pathological
grain" as the cause of the >=583 failure.

Usage:
    python extract_grain_slice.py <source.ttl> <output.ttl> --count N [--skip S]
"""
import argparse
import sys
from pathlib import Path

import rdflib
from rdflib.namespace import RDF

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ebsd2rdf import CRYSTALLITE_CLASS, HAS_RELATIONAL_QUALITY, SPECIFIED_BY_VALUE  # noqa: E402


def main() -> None:
	parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	parser.add_argument("source")
	parser.add_argument("output")
	parser.add_argument("--count", type=int, required=True, help="Number of grains to keep.")
	parser.add_argument("--skip", type=int, default=0, help="Number of leading grains (by sort order) to skip first.")
	args = parser.parse_args()

	g = rdflib.Graph()
	g.parse(args.source, format="turtle")

	grains = sorted({s for s, _, _ in g.triples((None, HAS_RELATIONAL_QUALITY, None))}, key=str)
	subset = set(grains[args.skip : args.skip + args.count])
	print(f"{len(grains)} grains available, taking {len(subset)} (skip={args.skip}, count={args.count})")

	out = rdflib.Graph()
	for grain in subset:
		out.add((grain, RDF.type, CRYSTALLITE_CLASS))
		for _, _, miso in g.triples((grain, HAS_RELATIONAL_QUALITY, None)):
			out.add((grain, HAS_RELATIONAL_QUALITY, miso))
			for p, o in g.predicate_objects(miso):
				out.add((miso, p, o))
				if p == SPECIFIED_BY_VALUE:
					for svs_p, svs_o in g.predicate_objects(o):
						out.add((o, svs_p, svs_o))
	for s, p, o in g.triples((None, RDF.type, None)):
		if str(s).startswith("http://example.org/ideal_"):
			out.add((s, p, o))

	out.serialize(destination=args.output, format="turtle")
	print(f"Wrote {len(out)} triples to {args.output}")


if __name__ == "__main__":
	main()
