## Customize Makefile settings for noes
## 
## If you need to customize your Makefile, make
## changes here rather than in the main Makefile

## Customize Makefile settings for noes
## 
## If you need to customize your Makefile, make
## changes here rather than in the main Makefile

PMDCO_DISJOINTNESS_REMOVAL_TERMS = $(IMPORTDIR)/pmdco_remove_disjoint.txt
PMDCO_INDIVIDUALS_TO_REMOVE = $(IMPORTDIR)/pmdco_individuals_to_remove.txt

$(ONTOLOGYTERMS): $(SRCMERGED)
	$(ROBOT) query -f csv -i $< --query noes_terms.sparql $@

# Import TTO classes preserving subclass hierarchy to PMDco
$(IMPORTDIR)/tto_import.owl: $(MIRRORDIR)/tto.owl $(IMPORTDIR)/tto_terms.txt $(IMPORTSEED) | all_robot_plugins

	$(ROBOT) annotate --input $< --remove-annotations \
			odk:normalize --add-source true \
			extract --term-file $(IMPORTDIR)/tto_terms.txt \
						--force true \
						--copy-ontology-annotations true \
						--individuals exclude \
						--intermediates all \
						--method BOT \
			remove --select individuals \
			\
			remove --term http://purl.obolibrary.org/obo/IAO_0000412 \
					--select annotation \
			odk:normalize --base-iri https://w3id.org/pmd/noes \
							--subset-decls true --synonym-decls true \
			annotate --ontology-iri $(ONTBASE)/$@ $(ANNOTATE_ONTOLOGY_VERSION) \
			convert -f owl --output $@.tmp.owl && mv $@.tmp.owl $@


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
	  remove --term-file $(PMDCO_INDIVIDUALS_TO_REMOVE) \
			 --select "individuals classes"\
	  $(ANNOTATE_CONVERT_FILE); \
	fi

# $(IMPORTDIR)/uo_import.owl: $(MIRRORDIR)/uo.owl $(IMPORTDIR)/uo_terms.txt 
#	$(ROBOT) filter --input mirror/uo.owl --term-file imports/uo_terms.txt --allow-punning true --select "annotations self parents" \
#		 $(ANNOTATE_CONVERT_FILE)
$(IMPORTDIR)/uo_import.owl: $(MIRRORDIR)/uo.owl $(IMPORTDIR)/uo_terms.txt
	$(ROBOT) filter --input $(MIRRORDIR)/uo.owl \
		--term-file $(IMPORTDIR)/uo_terms.txt \
		--allow-punning true \
		--select "annotations self parents" \
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


CITATION="'noes: Nonoriented Electrical Steel Ontology. Version $(VERSION), https://w3id.org/pmd/noes/'"


#ALL_ANNOTATIONS=--annotate-defined-by true \

ALL_ANNOTATIONS=--ontology-iri https://w3id.org/pmd/noes/ -V https://w3id.org/pmd/noes/$(VERSION) \
	--annotation http://purl.org/dc/terms/created "$(TODAY)" \
	--annotation owl:versionInfo "$(VERSION)" \
	--annotation http://purl.org/dc/terms/bibliographicCitation "$(CITATION)"  \
	--link-annotation owl:priorVersion https://w3id.org/pmd/noes/$(PRIOR_VERSION) \

update-ontology-annotations: 
	$(ROBOT) annotate --input ../../noes.owl $(ALL_ANNOTATIONS) --output ../../noes.owl && \
	$(ROBOT) annotate --input ../../noes.ttl $(ALL_ANNOTATIONS) --output ../../noes.ttl && \
	$(ROBOT) annotate --input ../../noes-full.owl $(ALL_ANNOTATIONS) --output ../../noes-full.owl && \
	$(ROBOT) annotate --input ../../noes-full.ttl $(ALL_ANNOTATIONS) --output ../../noes-full.ttl && \
	$(ROBOT) annotate --input ../../noes-base.owl $(ALL_ANNOTATIONS) --output ../../noes-base.owl && \
	$(ROBOT) annotate --input ../../noes-base.ttl $(ALL_ANNOTATIONS) --output ../../noes-base.ttl && \
	
