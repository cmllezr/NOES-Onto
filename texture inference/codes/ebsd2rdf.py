"""
Builds an inferred ABox graph of EBSD crystallographic texture from
grain_misorientation.csv against the NOES ontology.

Three checkpointed stages, each reading/writing its own Turtle file so the
(slow, fragile) reasoning step can be re-run in isolation without repeating
grain construction, and so intermediate results are inspectable:

Stage A -- build_crystallites() (plain rdflib, no owlready2/SQLite)
    1.  GrainCsvReader reads grain_id / area / misorientation_<slug>_deg /
        is_relevant from the CSV (see euler2hkl.py).
    2.  IdealTextureNodes mints one shared, named node per ideal texture
        (e.g. ex:ideal_cube, deterministic from the slug -- not a blank
        node) and asserts its rdf:type directly -- every grain's
        misorientation angle for that texture points at the same node via
        PMD_0025999 ("relational quality of").
    3.  CrystalliteBuilder stages the grains as temp: triples and runs
        crystallite_orientation.rq (a single generic SPARQL CONSTRUCT, not
        one block per texture) once to build every grain's crystallite +
        area, and its misorientation-angle relational quality to each of
        the 8 ideal textures (all 8 by default; only for grains where
        CSV's is_relevant is true if --relevant-only is set).
    4.  extract_texture_subgraph() carves the texture-relevant subgraph
        straight out of that CONSTRUCT result with a plain graph walk (no
        second SPARQL query -- see its docstring for why re-querying was
        both redundant and, empirically, pathologically slow).
    5.  The self-contained TBox+ABox graph is dumped to crystallites_ttl,
        ready for HermitReasoner to load.

Stage B -- reason() (the only stage touching owlready2/SQLite)
    HermitReasoner loads crystallites_ttl into an owlready2 World (Turtle
    isn't a format owlready2 can parse natively, so it's re-serialized to
    RDF/XML first), runs the HermiT reasoner to classify each crystallite
    into whichever of GRAIN_TYPES it satisfies, and dumps just the ABox
    (including the reasoner's newly-inferred rdf:type facts) together with
    an owl:imports statement back to the source ontology to reasoned_ttl.

Stage C -- build_populations_and_fractions() (plain rdflib again)
    1.  GrainPopulationBuilder runs grain_population.rq once per
        (GRAIN_TYPES, ORIENTATION_TYPES) pair to group the classified
        grains into a persistent ex:grain_population_<slug> individual with
        a texture quality of the matching ORIENTATION_TYPES class.
    2.  AreaFractionCalculator sums crystallite areas per population and in
        total, then TextureFractionBuilder runs texture_fraction.rq to
        attach each population's area fraction to the single, persistent
        material and microstructure individuals.
    3.  The result is serialized to output_path.
"""
from __future__ import annotations

import argparse
import csv
import os
import tempfile
import time
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

import owlready2
import rdflib
from rdflib import Literal, URIRef
from rdflib.namespace import OWL, RDF, XSD

CODES_DIR = Path(__file__).resolve().parent
TEXTURE_DIR = CODES_DIR.parent

DEFAULT_ONTOLOGY_URL = "https://cmllezr.github.io/NOES-Onto/1.0.4/doc/ontology.ttl"
# RDF/XML mirror of the same ontology -- owlready2 can load this natively
# (no rdflib round-trip needed), unlike the Turtle URL above, which is only
# used as the owl:imports target written into every output file (and, in
# classify_directly(), as the source of the ontology's asserted has-member
# edges the direct-classification query joins against).
DEFAULT_OWL_ONTOLOGY_URL = "https://raw.githubusercontent.com/cmllezr/NOES-Onto/refs/heads/main/src/ontology/noes-full.owl"
DEFAULT_CSV = TEXTURE_DIR / "grain_misorientation.csv"
# The full ABox -- every grain's crystallite + area -- never fed to
# owlready2 (no reasoning needed for area fractions).
DEFAULT_CRYSTALLITES_TTL = TEXTURE_DIR / "crystallites_with_tbox.ttl"
# Just the texture-relevant subgraph (crystallites with at least one
# misorientation angle, no area triples) -- this, not the full ABox, is
# what actually gets reasoned over in Stage B, since HermiT's cost tracks
# total ABox size and the area/SVS individuals are the bulk of it but are
# irrelevant to GRAIN_TYPES classification.
DEFAULT_TEXTURE_TTL = TEXTURE_DIR / "crystallites_texture.ttl"
DEFAULT_REASONED_TTL = TEXTURE_DIR / "crystallites_reasoned_abox.ttl"
# Output of classify_directly() -- the reasoner-free alternative to Stage B,
# written to its own file rather than reasoned_ttl so both can be compared
# side by side.
DEFAULT_DIRECT_CLASSIFIED_TTL = TEXTURE_DIR / "crystallites_classified_direct.ttl"
DEFAULT_OUTPUT = TEXTURE_DIR / "ebsd_texture_inferred.ttl"

CRYSTALLITE_QUERY_FILE = CODES_DIR / "crystallite_orientation.rq"
GRAIN_POPULATION_QUERY_FILE = CODES_DIR / "grain_population.rq"
TEXTURE_FRACTION_QUERY_FILE = CODES_DIR / "texture_fraction.rq"

EX = rdflib.Namespace("http://example.org/")
NOES = rdflib.Namespace("https://w3id.org/pmd/noes/")
OBO = rdflib.Namespace("http://purl.obolibrary.org/obo/")
CO = rdflib.Namespace("https://w3id.org/pmd/co/")
CRYO = rdflib.Namespace("https://w3id.org/pmd/cryo/")
TTO = rdflib.Namespace("https://w3id.org/pmd/tto/")
QUDT_UNIT = rdflib.Namespace("http://qudt.org/vocab/unit/")
TEMP = rdflib.Namespace("temp:")

# The single, persistent material and microstructure individuals for the
# whole graph (only referenced directly in Python -- via material_triple in
# build_crystallites() and by TextureFractionBuilder in Stage C).
MATERIAL = EX.some_material
MICROSTRUCTURE = EX.microstructure
MATERIAL_CLASS = NOES.NOES_0000180  # non-oriented electrical steel

CRYSTALLITE_CLASS = CO.PMD_0000663
HAS_QUALITY = OBO.RO_0000086
HAS_MEMBER = OBO.RO_0002351
SPECIFIED_BY_VALUE = CO.PMD_0000077
HAS_NUMERIC_VALUE = OBO.OBI_0001937
HAS_RELATIONAL_QUALITY = CO.PMD_0025998  # unique to misorientation angles -- area never uses this
RELATIONAL_QUALITY_OF = CO.PMD_0025999
MISORIENTATION_ANGLE_TOLERANCE = 15.0  # deg -- matches the ontology's xsd:float[<15.0] restriction

GRAIN_TYPES = [URIRef("https://w3id.org/pmd/noes/NOES_0000167"),  # crystallite with cube texture orientation
			   URIRef("https://w3id.org/pmd/noes/NOES_0000144"),  # crystallite with Goss texture orientation"
			   URIRef("https://w3id.org/pmd/noes/NOES_0000135"),  # crystallite with rotated cube texture orientation
			   URIRef("https://w3id.org/pmd/noes/NOES_0000151"),  # crystallite with rotated Goss texture orientation
			   URIRef("https://w3id.org/pmd/noes/NOES_0000162"),  # crystallite with alpha texture orientation
			   URIRef("https://w3id.org/pmd/noes/NOES_0000158"),  # crystallite with gamma texture orientation
			   URIRef("https://w3id.org/pmd/noes/NOES_0000157"),  # crystallite with eta texture orientation
			   URIRef("https://w3id.org/pmd/noes/NOES_0000152"),  # crystallite with lambda texture orientation
			   ]


IDEAL_GRAIN_TYPES = [URIRef("https://w3id.org/pmd/noes/NOES_0000058"),  # crystallite ideal with cube texture orientation
			   URIRef("https://w3id.org/pmd/noes/NOES_0000064"),  # crystallite with ideal Goss texture orientation"
			   URIRef("https://w3id.org/pmd/noes/NOES_0000060"),  # crystallite with ideal rotated cube texture orientation
			   URIRef("https://w3id.org/pmd/noes/NOES_0000071"),  # crystallite with ideal rotated Goss texture orientation
			   URIRef("https://w3id.org/pmd/noes/NOES_0000139"),  # crystallite with ideal alpha texture orientation
			   URIRef("https://w3id.org/pmd/noes/NOES_0000138"),  # crystallite with ideal gamma texture orientation
			   URIRef("https://w3id.org/pmd/noes/NOES_0000113"),  # crystallite with ideal eta texture orientation
			   URIRef("https://w3id.org/pmd/noes/NOES_0000112"),  # crystallite with ideal lambda texture orientation
			   ]

ORIENTATION_TYPES = [URIRef("https://w3id.org/pmd/noes/NOES_0000090"),  # cube texture
			   URIRef("https://w3id.org/pmd/noes/NOES_0000092"),  #  Goss texture
			   URIRef("https://w3id.org/pmd/noes/NOES_0000091"),  #  rotated cube texture
			   URIRef("https://w3id.org/pmd/noes/NOES_0000093"),  #  rotated Goss texture
			   URIRef("https://w3id.org/pmd/noes/NOES_0000086"),  #  alpha texture
			   URIRef("https://w3id.org/pmd/noes/NOES_0000095"),  #  gamma texture
			   URIRef("https://w3id.org/pmd/noes/NOES_0000088"),  #  eta texture
			   URIRef("https://w3id.org/pmd/noes/NOES_0000087"),  #  lambda texture
			   ]

# Slug used to build the persistent ex:grain_population_<slug> /
# ex:grain_population_<slug>_texture URIs, and to name the
# misorientation_<slug>_deg columns in grain_misorientation.csv, in the
# same order as GRAIN_TYPES / IDEAL_GRAIN_TYPES / ORIENTATION_TYPES above.
TEXTURE_SLUGS = ["cube", "goss", "rotated_cube", "rotated_goss", "alpha", "gamma", "eta", "lambda"]

TEXTURE_COMPONENTS: List[Tuple[URIRef, URIRef, str]] = list(zip(GRAIN_TYPES, ORIENTATION_TYPES, TEXTURE_SLUGS))

# (grain_type, ideal_grain_type, slug) -- the ideal_grain_type is the class
# whose single, graph-wide individual (a named node, see IdealTextureNodes)
# every grain's misorientation angle for that texture points at via
# PMD_0025999 ("relational quality of").
IDEAL_TEXTURE_COMPONENTS: List[Tuple[URIRef, URIRef, str]] = list(zip(GRAIN_TYPES, IDEAL_GRAIN_TYPES, TEXTURE_SLUGS))

# Inverse lookup used by classify_by_misorientation_angle(): the ideal
# texture individual's own rdf:type is what tells us which GRAIN_TYPE a
# sub-tolerance misorientation angle to it actually implies.
IDEAL_CLASS_TO_GRAIN_TYPE: Dict[URIRef, URIRef] = {
	ideal_type: grain_type for grain_type, ideal_type, _ in IDEAL_TEXTURE_COMPONENTS
}


def _bind_prefixes(graph: rdflib.Graph) -> None:
	graph.bind("ex", EX)
	graph.bind("noes", NOES)
	graph.bind("obo", OBO)
	graph.bind("pmd", CO)
	graph.bind("cryo", CRYO)
	graph.bind("tto", TTO)
	graph.bind("qudt-unit", QUDT_UNIT)


class GrainRecord:
	__slots__ = ("grain_id", "area", "misorientation_deg", "is_relevant")

	def __init__(self, grain_id: str, area: float, misorientation_deg: Dict[str, float], is_relevant: bool):
		self.grain_id = grain_id
		self.area = area
		self.misorientation_deg = misorientation_deg  # slug -> angle, one entry per TEXTURE_SLUGS
		self.is_relevant = is_relevant


class GrainCsvReader:
	"""Reads the grain_id / area / misorientation_<slug>_deg / is_relevant
	columns out of grain_misorientation.csv (see euler2hkl.py)."""

	def __init__(self, path: Path):
		self.path = path

	def __iter__(self) -> Iterator[GrainRecord]:
		with open(self.path, newline="", encoding="utf-8") as fh:
			for row in csv.DictReader(fh):
				yield GrainRecord(
					grain_id=row["grain_id"].strip(),
					area=float(row["area"]),
					misorientation_deg={
						slug: float(row[f"misorientation_{slug}_deg"]) for slug in TEXTURE_SLUGS
					},
					is_relevant=row["is_relevant"].strip().lower() == "true",
				)


class GraphStore:
	"""Thin CONSTRUCT-then-insert wrapper around a plain, in-memory rdflib
	Graph -- no owlready2/SQLite involved. (HermitReasoner is the one place
	in the pipeline that needs owlready2, and only for the reasoning call
	itself.) The CONSTRUCT half runs as genuine SPARQL (`graph.query`); the
	insert half is a direct `graph += triples` union rather than a SPARQL
	UPDATE INSERT DATA -- serializing the result to N-Triples text and
	re-parsing it through rdflib's SPARQL grammar just to add triples back
	to the same graph turned out to dominate runtime (measured at several
	hundred seconds for ~12-17k triples, independent of how large the graph
	already was), while a native graph union is a simple, fast set/addN
	operation."""

	def __init__(self, graph: Optional[rdflib.Graph] = None):
		self.graph = graph if graph is not None else rdflib.Graph()

	def insert_triples(self, triples: rdflib.Graph) -> int:
		if len(triples) == 0:
			return 0
		self.graph += triples
		return len(triples)

	def construct_and_insert(self, construct_query: str) -> int:
		result = self.graph.query(construct_query)
		new_triples = rdflib.Graph()
		new_triples += result
		return self.insert_triples(new_triples)

	def select(self, select_query: str):
		return self.graph.query(select_query)


class IdealTextureNodes:
	"""The 8 shared, graph-wide ideal-texture individuals (one named node
	per texture, e.g. ex:ideal_cube -- deterministic from the slug, not a
	blank node) that every grain's misorientation angle for that texture
	points at via PMD_0025999 ("relational quality of"). Because the IRI is
	a pure function of the slug, every grain that stages a reference to
	"cube" ends up pointing at the exact same node without any
	cross-grain coordination; their rdf:type triples are inserted directly,
	not through a query."""

	def __init__(self, components: Sequence[Tuple[URIRef, URIRef, str]] = IDEAL_TEXTURE_COMPONENTS):
		self.nodes: Dict[str, URIRef] = {slug: EX[f"ideal_{slug}"] for _, _, slug in components}
		self._ideal_class: Dict[str, URIRef] = {slug: ideal_type for _, ideal_type, slug in components}

	def __getitem__(self, slug: str) -> URIRef:
		return self.nodes[slug]

	def type_triples(self) -> rdflib.Graph:
		triples = rdflib.Graph()
		for slug, node in self.nodes.items():
			triples.add((node, RDF.type, self._ideal_class[slug]))
		return triples


def extract_texture_subgraph(new_triples: rdflib.Graph, ideal_nodes: IdealTextureNodes) -> rdflib.Graph:
	"""Carves the texture-relevant subgraph -- crystallites with at least
	one misorientation-angle relational quality, plus that angle's SVS and
	the ideal-texture individual it points at, no area triples -- straight
	out of `new_triples` (CrystalliteBuilder.build()'s own CONSTRUCT
	output), instead of re-deriving it with a second SPARQL query
	(formerly texture_subgraph.rq) over the full, much larger store graph.

	This used to be a standalone CONSTRUCT query re-matching the same
	grain->miso->svs->ideal chain from scratch, which is pure redundant
	work -- crystallite_orientation.rq already built exactly these triples
	moments earlier -- and turned out to be pathologically slow besides
	(rdflib's SPARQL planner does no cost-based join reordering, and this
	particular multi-hop chain triggered a near-cartesian join even on a
	graph of a few thousand triples). A plain graph walk anchored on
	PMD_0025998 ("has relational quality", unique to misorientation
	angles -- area never uses it) sidesteps SPARQL entirely and is exact by
	construction rather than by pattern-matching against predicates area
	also happens to use (e.g. PMD_0000077 "specified by value")."""
	texture = rdflib.Graph()
	for grain, _, miso in new_triples.triples((None, HAS_RELATIONAL_QUALITY, None)):
		texture.add((grain, RDF.type, CRYSTALLITE_CLASS))
		texture.add((grain, HAS_RELATIONAL_QUALITY, miso))
		for p, o in new_triples.predicate_objects(miso):
			texture.add((miso, p, o))
			if p == SPECIFIED_BY_VALUE:  # -> svs
				for svs_p, svs_o in new_triples.predicate_objects(o):
					texture.add((o, svs_p, svs_o))
	texture += ideal_nodes.type_triples()
	return texture


def classify_by_misorientation_angle(abox: rdflib.Graph) -> rdflib.Graph:
	"""Reasoner-free stand-in for HermiT's GRAIN_TYPES classification -- a
	plain graph walk, not a SPARQL query. Replicates exactly what each
	class's OWL equivalentClass restriction checks: a crystallite has a
	relational quality that is a misorientation angle, specified by a
	sub-15-degree value, whose relational-quality-of points at the class's
	ideal-texture individual.

	This used to be crystallite_classification_direct.rq, a SPARQL query
	with the same grain->miso->svs->ideal chain (x8, via UNION) as the
	now-removed texture_subgraph.rq -- and turned out to hit the exact same
	rdflib join-reordering pathology at full-dataset scale (never actually
	run against the full ~140k-triple ABox until this was diagnosed; fine
	on the small slice used while developing it). A plain walk anchored on
	PMD_0025998 sidesteps SPARQL entirely, same as
	extract_texture_subgraph()."""
	classified = rdflib.Graph()
	for grain, _, miso in abox.triples((None, HAS_RELATIONAL_QUALITY, None)):
		svs = next(abox.objects(miso, SPECIFIED_BY_VALUE), None)
		ideal = next(abox.objects(miso, RELATIONAL_QUALITY_OF), None)
		if svs is None or ideal is None:
			continue
		angle = next(abox.objects(svs, HAS_NUMERIC_VALUE), None)
		if angle is None or float(angle) >= MISORIENTATION_ANGLE_TOLERANCE:
			continue
		ideal_class = next(abox.objects(ideal, RDF.type), None)
		grain_type = IDEAL_CLASS_TO_GRAIN_TYPE.get(ideal_class)
		if grain_type is not None:
			classified.add((grain, RDF.type, grain_type))
	return classified


class CrystalliteBuilder:
	"""Stages every grain as temp: triples and runs
	crystallite_orientation.rq once -- a single generic CONSTRUCT, not one
	hand-written block per texture -- to build every grain's crystallite,
	area, and misorientation-angle relational quality to each of the 8
	shared ideal-texture individuals (see IdealTextureNodes) at once."""

	def __init__(self, store: GraphStore, ideal_nodes: IdealTextureNodes, query_path: Path, relevant_only: bool = False):
		self.store = store
		self.ideal_nodes = ideal_nodes
		self.query = query_path.read_text(encoding="utf-8")
		self.relevant_only = relevant_only

	@staticmethod
	def _grain_uri(grain_id: str) -> URIRef:
		return EX[f"grain_{grain_id}"]

	def _stage(self, records: Iterable[GrainRecord]) -> rdflib.Graph:
		staging = rdflib.Graph()
		for record in records:
			config = TEMP[f"config_{record.grain_id}"]
			staging.add((config, TEMP.grainID, Literal(record.grain_id)))
			staging.add((config, TEMP.areaValue, Literal(record.area)))

			if self.relevant_only and not record.is_relevant:
				continue

			grain = self._grain_uri(record.grain_id)
			# One ?entry per (grain, texture) pair, all under the same
			# temp: predicates (temp:grain/misoNode/svsNode/idealNode/
			# angleValue) regardless of which texture it's for -- this is
			# what lets crystallite_orientation.rq match all 8 textures
			# with one generic WHERE block instead of 8 near-duplicate
			# ones. The misorientation-angle and SVS individuals are named
			# (not blank), minted here deterministically from grain id +
			# texture slug -- each grain/texture pair gets its own
			# individual (unlike the shared ideal-texture nodes above).
			for slug in TEXTURE_SLUGS:
				entry = TEMP[f"miso_entry_{record.grain_id}_{slug}"]
				angle = record.misorientation_deg[slug]
				staging.add((entry, TEMP.grain, grain))
				staging.add((entry, TEMP.misoNode, EX[f"misorientation_{record.grain_id}_{slug}"]))
				staging.add((entry, TEMP.svsNode, EX[f"SVS_{record.grain_id}_{slug}_deg"]))
				staging.add((entry, TEMP.idealNode, self.ideal_nodes[slug]))
				staging.add((entry, TEMP.angleValue, Literal(angle, datatype=XSD.float)))
		return staging

	def build(self, records: Sequence[GrainRecord]) -> rdflib.Graph:
		# crystallite_orientation.rq only ever reads temp: predicates, so it
		# can run standalone against `staging` instead of inserting it into
		# store.graph first and then deleting the temp: triples back out
		# with a SPARQL DELETE WHERE afterward (the pattern this and
		# TextureFractionBuilder both used to follow) -- that DELETE scans
		# the *entire* accumulated store graph regardless of how few temp:
		# triples need removing, and by the time this runs in Stage A
		# that's already the full ~100k-triple staging graph merged in.
		# Querying `staging` directly avoids ever mixing that volume of
		# temp: triples into store.graph, so there's nothing to clean up
		# afterward.
		staging = self._stage(records)
		result = staging.query(self.query)
		new_triples = rdflib.Graph()
		new_triples += result
		self.store.insert_triples(new_triples)
		# Returned (not just inserted) so build_crystallites() can carve the
		# texture-only subgraph straight out of it -- see
		# extract_texture_subgraph() -- instead of re-deriving the same
		# triples with a second, much more expensive SPARQL query over the
		# whole (by then much larger) store graph.
		return new_triples


class HermitReasoner:
	"""The only class that touches owlready2/SQLite. Loads the TBox and the
	ABox as two separate documents into one owlready2 World, runs HermiT
	over their union, and returns just the ABox -- including newly-inferred
	rdf:type facts -- as a plain rdflib Graph.

	The TBox comes from `owl_ontology_url`, an RDF/XML mirror of the
	ontology that owlready2 can load directly. The ABox (`abox_graph`, our
	own constructed triples only -- no TBox mixed in) still has to go
	through a temp-file RDF/XML round-trip since owlready2 cannot parse
	Turtle, but it's now only ~11k triples instead of ~27k.

	"ABox" in the returned graph is identified as every triple whose
	subject falls under `abox_namespace` -- this excludes the ~16k
	base-ontology TBox triples that came along for HermiT to reason over.
	The misorientation-angle/SVS/ideal-texture individuals are also
	ex:-namespaced (named, not blank, nodes), so they pass this filter too
	and come back out alongside the fact Stage C actually cares about,
	each grain's inferred `?grain a <GRAIN_TYPE>` -- harmless, since
	reason() merges this into the already-identical crystallites_ttl
	content and RDF graph union is a set union (duplicates collapse)."""

	def __init__(self, owl_ontology_url: str, abox_namespace: str):
		self.owl_ontology_url = owl_ontology_url
		self.abox_namespace = abox_namespace

	def classify(self, abox_graph: rdflib.Graph) -> rdflib.Graph:
		world = owlready2.World()
		world.get_ontology(self.owl_ontology_url).load()

		fd, tmp_path = tempfile.mkstemp(suffix=".owl")
		os.close(fd)
		abox_graph.serialize(destination=tmp_path, format="xml")
		file_uri = "file://" + Path(tmp_path).as_posix()
		abox_onto = world.get_ontology(file_uri).load()

		with abox_onto:
			owlready2.sync_reasoner_hermit(world, infer_property_values=False, debug=0)

		store_graph = world.as_rdflib_graph()
		abox = rdflib.Graph()
		for s, p, o in store_graph:
			if str(s).startswith(self.abox_namespace):
				abox.add((s, p, o))
		return abox


class GrainPopulationBuilder:
	"""Runs grain_population.rq once per (grain_type, orientation_type)
	pair to group the grains HermiT classified into persistent, named
	grain-population individuals."""

	def __init__(self, store: GraphStore, query_path: Path, components: Sequence[Tuple[URIRef, URIRef, str]]):
		self.store = store
		self.template = query_path.read_text(encoding="utf-8")
		self.components = components

	def build(self, classified_grains: Dict[URIRef, List[URIRef]]) -> Dict[str, URIRef]:
		populations: Dict[str, URIRef] = {}
		for grain_type, orientation_type, slug in self.components:
			if not classified_grains.get(grain_type):
				continue  # no grain satisfied this GRAIN_TYPES class -- nothing to group
			population = EX[f"grain_population_{slug}"]
			texture = EX[f"grain_population_{slug}_texture"]
			query = (
				self.template.replace("%%GRAIN_TYPE%%", str(grain_type))
				.replace("%%POPULATION%%", str(population))
				.replace("%%TEXTURE%%", str(texture))
				.replace("%%ORIENTATION_TYPE%%", str(orientation_type))
			)
			self.store.construct_and_insert(query)
			populations[slug] = population
		return populations


class AreaFractionCalculator:
	"""Sums crystallite areas -- either every crystallite in the graph, or
	just the members of a given grain population -- by walking the
	crystallite -> area -> scalar-value-specification -> numeric-value path
	that crystallite_orientation.rq built."""

	def __init__(self, store: GraphStore):
		self.store = store

	def _sum_area(self, member_pattern: str) -> float:
		query = f"""
		SELECT (SUM(?val) AS ?total) WHERE {{
			{member_pattern}
			?grain <{HAS_QUALITY}> ?area .
			?area <{SPECIFIED_BY_VALUE}> ?areaSVS .
			?areaSVS <{HAS_NUMERIC_VALUE}> ?val .
		}}
		"""
		for row in self.store.select(query):
			return float(row.total) if row.total is not None else 0.0
		return 0.0

	def total_area(self) -> float:
		return self._sum_area(f"?grain a <{CRYSTALLITE_CLASS}> .")

	def population_area(self, population: URIRef) -> float:
		return self._sum_area(f"<{population}> <{HAS_MEMBER}> ?grain .")


class TextureFractionBuilder:
	"""Stages one (material, microstructure, grainPopulation, value) entry
	per population and runs texture_fraction.rq to attach its area
	fraction."""

	def __init__(self, store: GraphStore, query_path: Path):
		self.store = store
		self.query = query_path.read_text(encoding="utf-8")

	def build(self, population: URIRef, slug: str, fraction_percent: float) -> None:
		entry = TEMP[f"entry_{slug}"]
		staging = rdflib.Graph()
		staging.add((entry, TEMP.material, MATERIAL))
		staging.add((entry, TEMP.microstructure, MICROSTRUCTURE))
		staging.add((entry, TEMP.grainPopulation, population))
		staging.add((entry, TEMP.value, Literal(round(fraction_percent, 2))))

		# Query `staging` directly rather than insert-then-construct-then-
		# remove_temp_triples() (see CrystalliteBuilder.build() for the
		# full rationale) -- by Stage C the store graph already holds the
		# full ~140k-triple ABox, and remove_temp_triples() is a SPARQL
		# DELETE WHERE that rescans the *entire* graph regardless of how
		# few new temp: triples this call staged. Measured at ~18-20s per
		# call here, x8 populations, for a ~2.5 minute stage that should
		# take under a second.
		result = staging.query(self.query)
		new_triples = rdflib.Graph()
		new_triples += result
		self.store.insert_triples(new_triples)


def classify_grains(store: GraphStore, classes: Sequence[URIRef]) -> Dict[URIRef, List[URIRef]]:
	"""Reads which individuals HermiT (already run, in Stage B) classified
	under each of `classes` -- pure SELECT, no reasoning happens here."""
	classified: Dict[URIRef, List[URIRef]] = {}
	for cls in classes:
		rows = store.select(f"SELECT ?grain WHERE {{ ?grain a <{cls}> }}")
		classified[cls] = [row.grain for row in rows]
	return classified


class EBSD2RDFPipeline:
	"""Orchestrates the three checkpointed stages: build_crystallites (Stage
	A) -> reason (Stage B) -> build_populations_and_fractions (Stage C)."""

	def __init__(
		self,
		ontology_url: str = DEFAULT_ONTOLOGY_URL,
		owl_ontology_url: str = DEFAULT_OWL_ONTOLOGY_URL,
		csv_path: Path = DEFAULT_CSV,
		crystallites_ttl: Path = DEFAULT_CRYSTALLITES_TTL,
		texture_ttl: Path = DEFAULT_TEXTURE_TTL,
		reasoned_ttl: Path = DEFAULT_REASONED_TTL,
		direct_classified_ttl: Path = DEFAULT_DIRECT_CLASSIFIED_TTL,
		output_path: Path = DEFAULT_OUTPUT,
		limit: Optional[int] = None,
		relevant_only: bool = False,
	):
		self.ontology_url = ontology_url
		self.owl_ontology_url = owl_ontology_url
		self.csv_path = Path(csv_path)
		self.crystallites_ttl = Path(crystallites_ttl)
		self.texture_ttl = Path(texture_ttl)
		self.reasoned_ttl = Path(reasoned_ttl)
		self.direct_classified_ttl = Path(direct_classified_ttl)
		self.output_path = Path(output_path)
		self.limit = limit
		self.relevant_only = relevant_only

	def build_crystallites(self) -> None:
		"""Stage A: build every grain's crystallite (+ area, + misorientation
		angle to each of the 8 ideal textures where relevant) on a separate,
		initially empty rdflib Graph, and dump two checkpoints from it:

		- crystallites_ttl: the full ABox (every grain + its area, +
		  misorientation angles). Never fed to owlready2 -- no reasoning is
		  needed to compute area fractions.
		- texture_ttl: just the texture-relevant subgraph (crystallites
		  with at least one misorientation angle, no area triples), carved
		  out of the CONSTRUCT result via extract_texture_subgraph() rather
		  than re-derived with a second query. This, not the full ABox, is
		  what HermitReasoner actually reasons over in Stage B, since it's
		  a small fraction of the individual count.

		Both get the ontology owl:imports statement, added on their own
		graph instance right before serializing."""
		abox_graph = rdflib.Graph()
		store = GraphStore(abox_graph)
		ideal_nodes = IdealTextureNodes()
		store.insert_triples(ideal_nodes.type_triples())
		builder = CrystalliteBuilder(store, ideal_nodes, CRYSTALLITE_QUERY_FILE, relevant_only=self.relevant_only)

		records = list(GrainCsvReader(self.csv_path))
		if self.limit:
			records = records[: self.limit]
		print(f"Loaded {len(records)} grains from {self.csv_path}")
		if self.relevant_only:
			n_relevant = sum(1 for r in records if r.is_relevant)
			print(f"--relevant-only: staging misorientation angles for {n_relevant}/{len(records)} grains")

		new_triples = builder.build(records)
		print(f"Constructed {len(new_triples)} crystallite triples")

		material_triple = rdflib.Graph()
		material_triple.add((MATERIAL, RDF.type, MATERIAL_CLASS))
		store.insert_triples(material_triple)

		texture_graph = extract_texture_subgraph(new_triples, ideal_nodes)
		print(f"Extracted {len(texture_graph)} texture-relevant triples (no area triples) for Stage B")

		self._dump_abox(abox_graph, self.crystallites_ttl)
		self._dump_abox(texture_graph, self.texture_ttl)

	def _dump_abox(self, abox_graph: rdflib.Graph, path: Path) -> None:
		"""Writes an ABox graph plus the ontology owl:imports statement --
		added here, on its own graph instance -- to `path`. Never fed to
		owlready2 directly: owlready2 cannot resolve a Turtle owl:imports
		target (see HermitReasoner)."""
		output_graph = rdflib.Graph()
		_bind_prefixes(output_graph)
		ontology_iri = EX.ontology
		output_graph.add((ontology_iri, RDF.type, OWL.Ontology))
		output_graph.add((ontology_iri, OWL.imports, URIRef(self.ontology_url)))
		output_graph += abox_graph

		output_graph.serialize(destination=str(path), format="turtle")
		print(f"Wrote {len(output_graph)} triples (ABox + import statement) to {path}")

	def reason(self) -> None:
		"""Stage B: the only stage that touches owlready2/SQLite. Loads
		*just* texture_ttl (not the full ABox -- HermiT's cost tracks total
		ABox size, and the area/SVS individuals in the full ABox vastly
		outnumber the texture-relevant ones while contributing nothing to
		GRAIN_TYPES classification), strips its owl:imports/owl:Ontology
		annotation (owlready2 can't resolve a Turtle import target --
		HermitReasoner loads the real TBox itself, from owl_ontology_url),
		and runs HermiT over that small subgraph.

		The reasoner's output (the texture subgraph + its newly-inferred
		rdf:type facts) is then merged with the full ABox from
		crystallites_ttl -- same grain URIs, so the inferred types just
		attach onto the crystallites already there -- plus a single
		owl:imports statement, into reasoned_ttl."""
		texture_graph = rdflib.Graph()
		print(self.texture_ttl)
		texture_graph.parse(str(self.texture_ttl), format="turtle")
		print(f"Loaded {len(texture_graph)} triples from {self.texture_ttl}")

		ontology_iri = EX.ontology
		texture_graph.remove((ontology_iri, RDF.type, OWL.Ontology))
		texture_graph.remove((ontology_iri, OWL.imports, None))

		reasoner = HermitReasoner(owl_ontology_url=self.owl_ontology_url, abox_namespace=str(EX))
		print("Running the HermiT reasoner (this can take a while)...")
		t0 = time.time()
		reasoned_texture = reasoner.classify(texture_graph)
		print(f"Reasoner finished in {time.time() - t0:.1f}s, {len(reasoned_texture)} texture ABox triples kept")

		full_abox = rdflib.Graph()
		full_abox.parse(str(self.crystallites_ttl), format="turtle")
		print(f"Loaded {len(full_abox)} triples from {self.crystallites_ttl} to merge in")

		out = rdflib.Graph()
		_bind_prefixes(out)
		out += full_abox
		out += reasoned_texture
		# The ontology owl:imports statement already came in from
		# full_abox -- nothing else to add.

		out.serialize(destination=str(self.reasoned_ttl), format="turtle")
		print(f"Wrote {len(out)} triples (merged ABox) to {self.reasoned_ttl}")

	def classify_directly(self) -> None:
		"""Reasoner-free alternative to Stage B (reason()), for comparing
		against HermiT: runs classify_by_misorientation_angle() -- a plain
		numeric filter on each grain's already-asserted misorientation
		angle to each ideal texture (< 15 deg), i.e. exactly what the
		ontology's own equivalentClass axioms check -- directly against
		crystallites_ttl (the full ABox; no need for the smaller
		texture_ttl or the ontology's TBox here, since the misorientation
		angle is a plain literal, not something that needs symmetry-family
		joins to derive). Writes to direct_classified_ttl (not
		reasoned_ttl), so both this and the HermiT result can be kept and
		compared -- point EBSD2RDFPipeline(reasoned_ttl=...) at whichever
		one you want Stage C to consume."""
		abox = rdflib.Graph()
		abox.parse(str(self.crystallites_ttl), format="turtle")
		print(f"Loaded {len(abox)} triples from {self.crystallites_ttl}")
		ontology_iri = EX.ontology
		abox.remove((ontology_iri, RDF.type, OWL.Ontology))
		abox.remove((ontology_iri, OWL.imports, None))

		t0 = time.time()
		classified = classify_by_misorientation_angle(abox)
		print(f"Direct classification finished in {time.time() - t0:.1f}s, {len(classified)} type triples asserted")

		out = rdflib.Graph()
		_bind_prefixes(out)
		out.add((ontology_iri, RDF.type, OWL.Ontology))
		out.add((ontology_iri, OWL.imports, URIRef(self.ontology_url)))
		out += abox
		out += classified

		out.serialize(destination=str(self.direct_classified_ttl), format="turtle")
		print(f"Wrote {len(out)} triples to {self.direct_classified_ttl}")

	def build_populations_and_fractions(self) -> None:
		"""Stage C: grain-population grouping + area fractions, again with
		plain rdflib (no owlready2/SQLite) against the reasoned ABox."""
		graph = rdflib.Graph()
		graph.parse(str(self.reasoned_ttl), format="turtle")
		print(f"Loaded {len(graph)} triples from {self.reasoned_ttl}")
		store = GraphStore(graph)
		_bind_prefixes(store.graph)

		classified = classify_grains(store, GRAIN_TYPES)
		for grain_type, _, slug in TEXTURE_COMPONENTS:
			print(f"  {slug}: {len(classified.get(grain_type, []))} grains classified")

		population_builder = GrainPopulationBuilder(store, GRAIN_POPULATION_QUERY_FILE, TEXTURE_COMPONENTS)
		populations = population_builder.build(classified)

		fraction_calculator = AreaFractionCalculator(store)
		fraction_builder = TextureFractionBuilder(store, TEXTURE_FRACTION_QUERY_FILE)

		total_area = fraction_calculator.total_area()
		print(f"Total crystallite area: {total_area}")
		for slug, population in populations.items():
			pop_area = fraction_calculator.population_area(population)
			fraction = (pop_area / total_area * 100.0) if total_area else 0.0
			print(f"  {slug}: area={pop_area} fraction={fraction:.2f}%")
			fraction_builder.build(population, slug, fraction)

		store.graph.serialize(destination=str(self.output_path), format="turtle")
		print(f"Wrote {len(store.graph)} triples to {self.output_path}")

	def run(self) -> None:
		self.build_crystallites()
		self.reason()
		self.build_populations_and_fractions()


def main() -> None:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--ontology-url", default=DEFAULT_ONTOLOGY_URL)
	parser.add_argument(
		"--owl-ontology-url",
		default=DEFAULT_OWL_ONTOLOGY_URL,
		help="RDF/XML mirror of the ontology, loaded natively by owlready2 for reasoning (Stage B only).",
	)
	parser.add_argument("--csv", default=str(DEFAULT_CSV))
	parser.add_argument("--crystallites-ttl", default=str(DEFAULT_CRYSTALLITES_TTL))
	parser.add_argument(
		"--texture-ttl",
		default=str(DEFAULT_TEXTURE_TTL),
		help="Texture-only subgraph (no area triples) that Stage B actually reasons over.",
	)
	parser.add_argument("--reasoned-ttl", default=str(DEFAULT_REASONED_TTL))
	parser.add_argument(
		"--direct-classified-ttl",
		default=str(DEFAULT_DIRECT_CLASSIFIED_TTL),
		help="Output of classify-direct (reasoner-free GRAIN_TYPES classification).",
	)
	parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
	parser.add_argument("--limit", type=int, default=None, help="Only process the first N grains (for testing).")
	parser.add_argument(
		"--relevant-only",
		action="store_true",
		help=(
			"Only stage misorientation-angle triples for grains the CSV marks as is_relevant "
			"(within tolerance of at least one ideal texture). Grains still get a crystallite+area "
			"either way; this only controls whether the (much larger) misorientation subgraph is built "
			"for every grain or just the ones near a named texture."
		),
	)
	parser.add_argument(
		"--stage",
		choices=["crystallites", "reason", "classify-direct", "populations", "all"],
		default="all",
		help=(
			"Run a single checkpointed stage, or the full pipeline (default). "
			"'classify-direct' is a reasoner-free alternative to 'reason' -- run it, then run "
			"'populations' with --reasoned-ttl pointed at --direct-classified-ttl to use its output."
		),
	)
	args = parser.parse_args()

	pipeline = EBSD2RDFPipeline(
		ontology_url=args.ontology_url,
		owl_ontology_url=args.owl_ontology_url,
		csv_path=Path(args.csv),
		crystallites_ttl=Path(args.crystallites_ttl),
		texture_ttl=Path(args.texture_ttl),
		reasoned_ttl=Path(args.reasoned_ttl),
		direct_classified_ttl=Path(args.direct_classified_ttl),
		output_path=Path(args.output),
		limit=args.limit,
		relevant_only=args.relevant_only,
	)

	if args.stage == "crystallites":
		pipeline.build_crystallites()
	elif args.stage == "reason":
		pipeline.reason()
	elif args.stage == "classify-direct":
		pipeline.classify_directly()
	elif args.stage == "populations":
		pipeline.build_populations_and_fractions()
	else:
		pipeline.run()


if __name__ == "__main__":
	main()
