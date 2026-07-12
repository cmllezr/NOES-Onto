"""
Builds an inferred ABox graph of EBSD crystallographic texture from
grain_hkl_uvw.csv against the NOES ontology.

Three checkpointed stages, each reading/writing its own Turtle file so the
(slow, fragile) reasoning step can be re-run in isolation without repeating
grain construction, and so intermediate results are inspectable:

Stage A -- build_crystallites() (plain rdflib, no owlready2/SQLite)
    1.  GrainCsvReader reads grain_id / hkl / uvw / area from the CSV.
    2.  MillerIndexResolver looks up the ontology NamedIndividual denoted by
        each hkl/uvw notation string. Only low-index / ideal orientations
        have a matching individual in the ontology, so most "Other/Random"
        grains legitimately have no match.
    3.  CrystalliteBuilder stages the grains as temp: triples and runs
        crystallite_orientation.rq (SPARQL CONSTRUCT) once to build every
        grain's crystallite + area, and -- only where the orientation was
        resolvable -- its crystallographic direction/plane/lattice.
    4.  The self-contained TBox+ABox graph is dumped to crystallites_ttl,
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
from rdflib.namespace import OWL, RDF, RDFS

CODES_DIR = Path(__file__).resolve().parent
TEXTURE_DIR = CODES_DIR.parent

DEFAULT_ONTOLOGY_URL = "https://cmllezr.github.io/NOES-Onto/1.0.4/doc/ontology.ttl"
# RDF/XML mirror of the same ontology -- owlready2 can load this natively
# (no rdflib round-trip needed), unlike the Turtle URL above, which is only
# used for MillerIndexResolver's label lookups and as the owl:imports
# target written into every output file.
DEFAULT_OWL_ONTOLOGY_URL = "https://raw.githubusercontent.com/cmllezr/NOES-Onto/refs/heads/main/src/ontology/noes-full.owl"
DEFAULT_CSV = TEXTURE_DIR / "grain_hkl_uvw.csv"
# The full ABox -- every grain's crystallite + area -- never fed to
# owlready2 (no reasoning needed for area fractions).
DEFAULT_CRYSTALLITES_TTL = TEXTURE_DIR / "crystallites_with_tbox.ttl"
# Just the texture-relevant subgraph (crystallites with a resolved
# direction/plane, no area triples) -- this, not the full ABox, is what
# actually gets reasoned over in Stage B, since HermiT's cost tracks total
# ABox size and the area/SVS individuals are the bulk of it but are
# irrelevant to GRAIN_TYPES classification.
DEFAULT_TEXTURE_TTL = TEXTURE_DIR / "crystallites_texture.ttl"
DEFAULT_REASONED_TTL = TEXTURE_DIR / "crystallites_reasoned_abox.ttl"
# Output of classify_directly() -- the reasoner-free alternative to Stage B,
# written to its own file rather than reasoned_ttl so both can be compared
# side by side.
DEFAULT_DIRECT_CLASSIFIED_TTL = TEXTURE_DIR / "crystallites_classified_direct.ttl"
DEFAULT_OUTPUT = TEXTURE_DIR / "ebsd_texture_inferred.ttl"

CRYSTALLITE_QUERY_FILE = CODES_DIR / "crystallite_orientation.rq"
TEXTURE_SUBGRAPH_QUERY_FILE = CODES_DIR / "texture_subgraph.rq"
DIRECT_CLASSIFICATION_QUERY_FILE = CODES_DIR / "crystallite_classification_direct.rq"
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
# whole graph (crystallite_orientation.rq itself binds the same
# ex:some_material URI for every grain's rolling direction/plane).
MATERIAL = EX.some_material
MICROSTRUCTURE = EX.microstructure
MATERIAL_CLASS = NOES.NOES_0000180  # non-oriented electrical steel

CRYSTALLITE_CLASS = CO.PMD_0000663
HAS_QUALITY = OBO.RO_0000086
HAS_MEMBER = OBO.RO_0002351
SPECIFIED_BY_VALUE = CO.PMD_0000077
HAS_NUMERIC_VALUE = OBO.OBI_0001937

GRAIN_TYPES = [URIRef("https://w3id.org/pmd/noes/NOES_0000167"),  # crystallite with cube texture orientation
			   URIRef("https://w3id.org/pmd/noes/NOES_0000144"),  # crystallite with Goss texture orientation"
			   URIRef("https://w3id.org/pmd/noes/NOES_0000135"),  # crystallite with rotated cube texture orientation
			   URIRef("https://w3id.org/pmd/noes/NOES_0000151"),  # crystallite with rotated Goss texture orientation
			   URIRef("https://w3id.org/pmd/noes/NOES_0000162"),  # crystallite with alpha texture orientation
			   URIRef("https://w3id.org/pmd/noes/NOES_0000158"),  # crystallite with gamma texture orientation
			   URIRef("https://w3id.org/pmd/noes/NOES_0000157"),  # crystallite with eta texture orientation
			   URIRef("https://w3id.org/pmd/noes/NOES_0000152"),  # crystallite with lambda texture orientation
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
# ex:grain_population_<slug>_texture URIs, in the same order as GRAIN_TYPES
# / ORIENTATION_TYPES above.
TEXTURE_SLUGS = ["cube", "goss", "rotated_cube", "rotated_goss", "alpha", "gamma", "eta", "lambda"]

TEXTURE_COMPONENTS: List[Tuple[URIRef, URIRef, str]] = list(zip(GRAIN_TYPES, ORIENTATION_TYPES, TEXTURE_SLUGS))


def _bind_prefixes(graph: rdflib.Graph) -> None:
	graph.bind("ex", EX)
	graph.bind("noes", NOES)
	graph.bind("obo", OBO)
	graph.bind("pmd", CO)
	graph.bind("cryo", CRYO)
	graph.bind("tto", TTO)
	graph.bind("qudt-unit", QUDT_UNIT)


class GrainRecord:
	__slots__ = ("grain_id", "hkl", "uvw", "area")

	def __init__(self, grain_id: str, hkl: str, uvw: str, area: float):
		self.grain_id = grain_id
		self.hkl = hkl
		self.uvw = uvw
		self.area = area


class GrainCsvReader:
	"""Reads the grain_id / hkl / uvw / area columns out of grain_hkl_uvw.csv."""

	def __init__(self, path: Path):
		self.path = path

	def __iter__(self) -> Iterator[GrainRecord]:
		with open(self.path, newline="", encoding="utf-8") as fh:
			for row in csv.DictReader(fh):
				yield GrainRecord(
					grain_id=row["grain_id"].strip(),
					hkl=row["hkl"].strip(),
					uvw=row["uvw"].strip(),
					area=float(row["area"]),
				)


class MillerIndexResolver:
	"""Looks up the ontology NamedIndividual whose rdfs:label is a given
	Miller-index notation string, e.g. "(110)" or "[1-50]". Only low-index /
	ideal orientations have a matching individual in the ontology, so a miss
	is expected for most grains and is handled by the caller, not an error
	here."""

	def __init__(self, ontology: rdflib.Graph):
		self.ontology = ontology
		self._cache: Dict[str, Optional[URIRef]] = {}

	def get_uri_by_label(self, label: str, lang: str = "en") -> Optional[URIRef]:
		objects = [
			Literal(label, lang=lang),
			Literal(label),
		]
		try:
			for obj in objects:
				out = list(self.ontology.subjects(predicate=RDFS.label, object=obj))
				if out:
					return out[0]
		except ValueError:
			print(f"Could not find the uri from label {label}")
		return None

	def resolve(self, label: str) -> Optional[URIRef]:
		if label not in self._cache:
			self._cache[label] = self.get_uri_by_label(label)
		return self._cache[label]


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

	def remove_temp_triples(self) -> None:
		self.graph.update(
			"DELETE { ?s ?p ?o } WHERE { ?s ?p ?o . "
			"FILTER(STRSTARTS(STR(?s), 'temp:') || STRSTARTS(STR(?p), 'temp:')) }"
		)

	def select(self, select_query: str):
		return self.graph.query(select_query)


class CrystalliteBuilder:
	"""Stages every grain as temp: triples and runs
	crystallite_orientation.rq once to construct all crystallites at once."""

	def __init__(self, store: GraphStore, resolver: MillerIndexResolver, query_path: Path):
		self.store = store
		self.resolver = resolver
		self.query = query_path.read_text(encoding="utf-8")
		self.unresolved_grains: List[str] = []

	@staticmethod
	def _slugify(s: str) -> str:
		return "".join(c if c.isalnum() else "_" for c in s).strip("_")

	@classmethod
	def _orientation_slug(cls, hkl: str, uvw: str) -> str:
		"""URI-safe key for a resolved (hkl, uvw) pair, e.g. "(001)"/"[100]"
		-> "001_100"."""
		return f"{cls._slugify(hkl)}_{cls._slugify(uvw)}"

	@staticmethod
	def _hkl_as_direction_notation(hkl: str) -> str:
		"""For cubic crystals the plane normal (hkl) and the direction
		[hkl] are the same vector, just notated differently -- "(001)" ->
		"[001]" -- so it can be looked up against the ontology's
		direction-notation individuals instead of its plane-notation
		ones."""
		return hkl.replace("(", "[").replace(")", "]")

	def _stage(self, records: Iterable[GrainRecord]) -> rdflib.Graph:
		staging = rdflib.Graph()
		for record in records:
			config = TEMP[f"config_{record.grain_id}"]
			staging.add((config, TEMP.grainID, Literal(record.grain_id)))
			staging.add((config, TEMP.areaValue, Literal(record.area)))

			# uvw (-> ?direction, ~RD) and hkl (-> ?plane, ~RP) are resolved
			# and staged *independently* of each other -- not gated on both
			# succeeding together. That matters for fibers: alpha/eta only
			# need ?direction (uvw), gamma/lambda only need ?ndDirection
			# (hkl, staged separately below); requiring both hkl and uvw to
			# resolve before either is usable would silently drop e.g. a
			# grain whose uvw was fiber-snapped to an exact <110> index but
			# whose hkl is still an unresolvable multi-digit rational fit.
			# ?lattice/?lattice_system (needed for the point-component
			# CRYO_0000041/hasSelf pattern HermiT relies on -- not needed by
			# crystallite_classification_direct.rq at all) are only staged
			# when *both* resolve, since they tie plane and direction
			# together for a single crystal lattice.
			hkl_uri = self.resolver.resolve(record.hkl)
			uvw_uri = self.resolver.resolve(record.uvw)

			if uvw_uri is not None:
				# Grains with the identical resolved uvw notation (e.g.
				# every exact-Cube grain is denoted by the same "[100]"
				# individual) share one direction individual rather than
				# minting a new one each -- physically correct (identical
				# notation *is* the same crystallographic direction) and
				# keeps the individual count small for HermiT.
				uvw_slug = self._slugify(record.uvw)
				staging.add((config, TEMP.uvw, uvw_uri))
				staging.add((config, TEMP.direction, EX[f"direction_{uvw_slug}"]))

			if hkl_uri is not None:
				hkl_slug = self._slugify(record.hkl)
				staging.add((config, TEMP.hkl, hkl_uri))
				staging.add((config, TEMP.plane, EX[f"plane_{hkl_slug}"]))

			if hkl_uri is not None and uvw_uri is not None:
				slug = self._orientation_slug(record.hkl, record.uvw)
				staging.add((config, TEMP.lattice, EX[f"lattice_{slug}"]))
				staging.add((config, TEMP.latticeSystem, EX[f"lattice_system_{slug}"]))

			if hkl_uri is None and uvw_uri is None:
				self.unresolved_grains.append(record.grain_id)

			# Independent of the plane/direction resolution above (fiber
			# support): hkl reinterpreted as a direction-notation string
			# and looked up against the ontology's direction individuals,
			# for the gamma/lambda (<hkl>//ND) fibers. Only alpha/eta
			# fibers are covered by the uvw-derived ?direction above,
			# since they need <uvw>//RD, which that already gives.
			hkl_as_direction = self._hkl_as_direction_notation(record.hkl)
			nd_direction_uri = self.resolver.resolve(hkl_as_direction)
			if nd_direction_uri is not None:
				hkl_slug = self._slugify(hkl_as_direction)
				staging.add((config, TEMP.hklAsDirection, nd_direction_uri))
				staging.add((config, TEMP.ndDirection, EX[f"nd_direction_{hkl_slug}"]))
		return staging

	def build(self, records: Sequence[GrainRecord]) -> int:
		staging = self._stage(records)
		self.store.insert_triples(staging)
		count = self.store.construct_and_insert(self.query)
		self.store.remove_temp_triples()
		return count


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
	subject falls under `abox_namespace`, which by construction is every
	triple we built (crystallite_orientation.rq only ever mints ex:
	subjects) -- this excludes the ~16k base-ontology TBox triples that
	came along for HermiT to reason over."""

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

		self.store.insert_triples(staging)
		self.store.construct_and_insert(self.query)
		self.store.remove_temp_triples()


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

	def _load_ontology_graph(self) -> rdflib.Graph:
		graph = rdflib.Graph()
		graph.parse(self.ontology_url, format="turtle")
		return graph

	def build_crystallites(self) -> None:
		"""Stage A: fetch the ontology (its own graph instance, used only
		for MillerIndexResolver's label lookups -- never merged into the
		construction graph), build every grain's crystallite (+ area, +
		direction/plane/lattice where resolvable) on a separate, initially
		empty rdflib Graph, and dump two checkpoints from it:

		- crystallites_ttl: the full ABox (every grain + its area). Never
		  fed to owlready2 -- no reasoning is needed to compute area
		  fractions.
		- texture_ttl: just the texture-relevant subgraph (crystallites
		  with a resolved direction/plane, no area triples), extracted via
		  texture_subgraph.rq. This, not the full ABox, is what
		  HermitReasoner actually reasons over in Stage B, since it's a
		  small fraction of the individual count.

		Both get the ontology owl:imports statement, added on their own
		graph instance right before serializing."""
		ontology_graph = self._load_ontology_graph()
		print(f"Loaded {len(ontology_graph)} ontology triples from {self.ontology_url}")

		abox_graph = rdflib.Graph()
		store = GraphStore(abox_graph)
		resolver = MillerIndexResolver(ontology_graph)
		builder = CrystalliteBuilder(store, resolver, CRYSTALLITE_QUERY_FILE)

		records = list(GrainCsvReader(self.csv_path))
		if self.limit:
			records = records[: self.limit]
		print(f"Loaded {len(records)} grains from {self.csv_path}")

		n_triples = builder.build(records)
		print(
			f"Constructed {n_triples} crystallite triples "
			f"({len(builder.unresolved_grains)} grains had no matching hkl/uvw individual "
			"in the ontology and were kept as crystallite+area only)"
		)

		material_triple = rdflib.Graph()
		material_triple.add((MATERIAL, RDF.type, MATERIAL_CLASS))
		store.insert_triples(material_triple)

		texture_subgraph_query = TEXTURE_SUBGRAPH_QUERY_FILE.read_text(encoding="utf-8")
		texture_result = abox_graph.query(texture_subgraph_query)
		texture_graph = rdflib.Graph()
		texture_graph += texture_result
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
		against HermiT: loads the ontology plus crystallites_ttl (the full
		ABox, no need for the smaller texture_ttl here -- this is a single
		fast SPARQL query, not an expensive reasoning run) into one plain
		rdflib Graph and runs crystallite_classification_direct.rq, which
		replicates each GRAIN_TYPES class's family-membership check as a
		SPARQL join against the ontology's *asserted* has-member edges,
		instead of relying on HermiT to derive it. Writes to
		direct_classified_ttl (not reasoned_ttl), so both this and the
		HermiT result can be kept and compared -- point
		EBSD2RDFPipeline(reasoned_ttl=...) at whichever one you want Stage
		C to consume."""
		graph = self._load_ontology_graph()
		print(f"Loaded {len(graph)} ontology triples from {self.ontology_url}")

		abox = rdflib.Graph()
		abox.parse(str(self.crystallites_ttl), format="turtle")
		print(f"Loaded {len(abox)} triples from {self.crystallites_ttl}")
		ontology_iri = EX.ontology
		abox.remove((ontology_iri, RDF.type, OWL.Ontology))
		abox.remove((ontology_iri, OWL.imports, None))
		graph += abox

		query = DIRECT_CLASSIFICATION_QUERY_FILE.read_text(encoding="utf-8")
		t0 = time.time()
		result = graph.query(query)
		classified = rdflib.Graph()
		classified += result
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
