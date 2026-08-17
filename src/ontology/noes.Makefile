## Customize Makefile settings for noes
## 
## If you need to customize your Makefile, make
## changes here rather than in the main Makefile

## Customize Makefile settings for noes
## 
## If you need to customize your Makefile, make
## changes here rather than in the main Makefile

PMDCO_DISJOINTNESS_REMOVAL_TERMS = $(IMPORTDIR)/pmdco_remove_disjoint.txt
IAO_TO_REMOVE = $(IMPORTDIR)/iao_to_remove.txt
PMDCO_CLASSES_TO_REMOVE = $(IMPORTDIR)/pmdco_classes_to_remove.txt

$(ONTOLOGYTERMS): $(SRCMERGED)
	$(ROBOT) query -vvv -f csv -i $< --query noes_terms.sparql $@

# Import CryO classes preserving subclass hierarchy to PMDco
$(IMPORTDIR)/cryo_import.owl: $(MIRRORDIR)/cryo.owl $(IMPORTDIR)/cryo_terms.txt $(IMPORTSEED) | all_robot_plugins
	@echo "Generating import module from private CryO mirror..."
	$(ROBOT) annotate --input $< --remove-annotations \
			odk:normalize --add-source true \
			extract --term-file $(IMPORTDIR)/cryo_terms.txt \
						--force true \
						--copy-ontology-annotations true \
						--intermediates all \
						--individuals minimal \
						--method BOT \
			odk:normalize --base-iri https://w3id.org/pmd/noes \
							--subset-decls true --synonym-decls true \
			$(ANNOTATE_CONVERT_FILE); \

# Import TTO classes preserving subclass hierarchy to PMDco
$(IMPORTDIR)/tto_import.owl: $(MIRRORDIR)/tto.owl $(IMPORTDIR)/tto_terms.txt $(IMPORTSEED) | all_robot_plugins
	@echo "Generating import module from private TTO mirror..."
	$(ROBOT) annotate --input $< --remove-annotations \
			odk:normalize --add-source true \
			extract --term-file $(IMPORTDIR)/tto_terms.txt \
						--force true \
						--copy-ontology-annotations true \
						--individuals exclude \
						--intermediates all \
						--method BOT \
			remove --term "https://w3id.org/pmd/co/relatesTo" \
				   --select "self" \
				   --trim true \
			odk:normalize --base-iri https://w3id.org/pmd/noes \
							--subset-decls true --synonym-decls true \
			$(ANNOTATE_CONVERT_FILE); \

$(IMPORTDIR)/pmdco_import.owl: $(MIRRORDIR)/pmdco.owl $(IMPORTDIR)/pmdco_terms.txt
	@echo "Generating Application Module from pmdco..."
	if [ $(IMP) = true ]; then $(ROBOT) \
	  query -i $< --update ../sparql/preprocess-module.ru \
	  extract --term-file $(IMPORTDIR)/pmdco_terms.txt \
	          --force true \
	          --copy-ontology-annotations true \
	          --intermediates all \
	          --method BOT \
	  \
	  query --update ../sparql/inject-subset-declaration.ru \
	        --update ../sparql/inject-synonymtype-declaration.ru \
	        --update ../sparql/postprocess-module.ru \
	  \
	  remove --term http://purl.obolibrary.org/obo/IAO_0000412 \
             --select annotation \
	  \
	  remove --term-file $(PMDCO_DISJOINTNESS_REMOVAL_TERMS) \
			 --axioms DisjointClasses \
	  remove --term-file $(PMDCO_CLASSES_TO_REMOVE) \
			 --select "classes"\
	  remove --term-file $(IAO_TO_REMOVE) \
			 --select "individuals classes"\
	  $(ANNOTATE_CONVERT_FILE); \
	fi


$(IMPORTDIR)/uo_import.owl: $(MIRRORDIR)/uo.owl $(IMPORTDIR)/uo_terms.txt
	$(ROBOT) filter --input $(MIRRORDIR)/uo.owl \
		--term-file $(IMPORTDIR)/uo_terms.txt \
		--allow-punning true \
		--select "annotations self parents" \
		$(ANNOTATE_CONVERT_FILE)

$(IMPORTDIR)/qudt_import.owl: $(MIRRORDIR)/qudt.owl $(IMPORTDIR)/qudt_terms.txt
	$(ROBOT) filter --input $(MIRRORDIR)/qudt.owl \
		--term-file $(IMPORTDIR)/qudt_terms.txt \
		--allow-punning true \
		--select "annotations self" \
		$(ANNOTATE_CONVERT_FILE)

$(IMPORTDIR)/ro_import.owl: $(MIRRORDIR)/ro.owl $(IMPORTDIR)/ro_terms.txt \
			   $(IMPORTSEED) | all_robot_plugins
	$(ROBOT) annotate --input $< --remove-annotations \
	     remove --select "RO:*" --select complement --select "classes"  --axioms annotation \
		 odk:normalize --add-source true \
		 extract --term-file $(IMPORTDIR)/ro_terms.txt  \
		         --force true --copy-ontology-annotations true \
		         --individuals exclude \
		         --method SUBSET \
		 remove $(foreach p, $(ANNOTATION_PROPERTIES), --term $(p)) \
		        --term-file $(IMPORTDIR)/ro_terms.txt \
		        --select complement --select annotation-properties \
		 remove --term-file $(IMPORTDIR)/unwanted.txt  \
		 odk:normalize --base-iri https://w3id.org/pmd \
		               --subset-decls true --synonym-decls true \
		 $(ANNOTATE_CONVERT_FILE)

#.PHONY: autoshapes
#autoshapes: 
#	echo "please run manually: sh utils/generate-auto-shapes.sh"


$(ONT)-base.owl: $(EDIT_PREPROCESSED) $(OTHER_SRC) $(IMPORT_FILES)
	$(ROBOT_RELEASE_IMPORT_MODE) \
	reason --reasoner ELK --equivalent-classes-allowed asserted-only --exclude-tautologies structural --annotate-inferred-axioms False \
	relax \
	reduce -r ELK \
	remove --base-iri $(URIBASE)/ --axioms external --preserve-structure false --trim false \
	$(SHARED_ROBOT_COMMANDS) \
	annotate --link-annotation http://purl.org/dc/elements/1.1/type http://purl.obolibrary.org/obo/IAO_8000001 \
		--ontology-iri $(ONTBASE)/$@ $(ANNOTATE_ONTOLOGY_VERSION) \
		--output $@.tmp.owl && mv $@.tmp.owl $@


CITATION="'NOES-Onto: Nonoriented Electrical Steel Ontology. Version $(VERSION), https://w3id.org/pmd/noes/'"
CREATED   = 2025-06-01                                  
DOI       = https://doi.org/10.5281/zenodo.XXXXXXX      # TODO: mint via Zenodo-GitHub integration (use the concept DOI)
PUBLISHER = https://ror.org/04hm8eb66                     # TODO: your institution (a ROR IRI works well)

# Previous published version: read from the last released file BEFORE overwriting it
#PRIOR_VERSION := $(shell sed -n 's:.*<owl:versionInfo>\(.*\)</owl:versionInfo>.*:\1:p' ../../noes.owl 2>/dev/null | head -n 1)
#ifneq ($(strip $(PRIOR_VERSION)),)
#PRIOR_ANNOTATION = --link-annotation owl:priorVersion https://w3id.org/pmd/noes/$(PRIOR_VERSION)
#endif

ALL_ANNOTATIONS = --ontology-iri https://w3id.org/pmd/noes/ \
	--typed-annotation http://purl.org/dc/terms/created "$(CREATED)" xsd:date \
	--typed-annotation http://purl.org/dc/terms/issued "$(TODAY)" xsd:date \
	--typed-annotation http://purl.org/dc/terms/modified "$(TODAY)" xsd:date \
	--annotation http://purl.org/vocab/vann/preferredNamespacePrefix "noes" \
	--annotation http://purl.org/vocab/vann/preferredNamespaceUri "https://w3id.org/pmd/noes/" \
	--link-annotation http://purl.org/dc/terms/publisher $(PUBLISHER) \
	--link-annotation http://purl.org/dc/terms/source https://w3id.org/pmd/co/ \
	--annotation http://purl.org/ontology/bibo/status "stable" \
	--annotation http://purl.org/dc/terms/identifier "$(DOI)"

RELEASE_FILES = noes.owl noes.ttl noes-full.owl noes-full.ttl \
                noes-base.owl noes-base.ttl noes-simple.owl noes-simple.ttl

# Annotate the src/ontology copies IN PLACE (these feed WIDOCO → gh-pages → w3id),
# then mirror them to the repo root.
update-ontology-annotations:
	for f in $(RELEASE_FILES); do \
		$(ROBOT) annotate --input $$f $(ALL_ANNOTATIONS) --output tmp_$$f && \
		mv tmp_$$f $$f && \
		cp $$f ../../$$f || exit 1; \
	done

all_assets: update-ontology-annotations
