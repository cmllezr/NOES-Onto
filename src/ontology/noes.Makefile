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

# Import CryO from private repo. NOTE MUST BE REMOVED ONCE CRYO IS PUBLIC
CONFIG_FILE := $(firstword $(wildcard ../../noes-odk.yaml ../noes-odk.yaml noes-odk.yaml ../../ontology-config.yaml ../ontology-config.yaml ontology-config.yaml))
RAW_URL = $(shell grep -A 5 "id: cryo" $(CONFIG_FILE) | grep "mirror_from:" | head -n 1 | sed 's/.*mirror_from:[[:space:]]*//' | sed 's/[[:space:]]//g')
CRYO_MIRROR = $(MIRRORDIR)/cryo.owl

# 2. Updated download rule using CRYO_TOKEN
$(CRYO_MIRROR):
	@echo "Detected Config File: $(CONFIG_FILE)"
	@echo "Fetching from URL: $(RAW_URL)"
	@if [ -z "$(RAW_URL)" ]; then \
		echo "ERROR: Could not extract mirror_from URL for 'id: cryo' from $(CONFIG_FILE)"; \
		exit 1; \
	fi
	# Determine if we need to inject the CRYO_TOKEN or if the URL is self-contained
	@if echo "$(RAW_URL)" | grep -q "token="; then \
		echo "Using self-contained token from URL..."; \
		curl -f -sS -L "$(RAW_URL)" -o $@; \
	else \
		echo "Using CRYO_TOKEN from environment..."; \
		$(MAKE) download-with-token; \
	fi
	@if [ ! -s $@ ]; then \
		echo "ERROR: Downloaded cryo.owl is empty. Check URL/Token."; \
		rm -f $@; \
		exit 1; \
	fi

download-with-token:
	$(eval OWNER=$(shell echo $(RAW_URL) | cut -d'/' -f4))
	$(eval REPO=$(shell echo $(RAW_URL) | cut -d'/' -f5))
	# Identify if 'refs/heads/' is in the URL to determine path and ref
	$(eval REF=$(shell echo $(RAW_URL) | grep -oP '(?<=refs/heads/)[^/]+' || echo $(RAW_URL) | cut -d'/' -f6))
	$(eval FILE_PATH=$(shell echo $(RAW_URL) | sed -E 's|.*(refs/heads/[^/]+/\|[^/]+/[^/]+/[^/]+/)(.*)|\2|'))
	@echo "Targeting Repo: $(OWNER)/$(REPO) Path: $(FILE_PATH) Ref: $(REF)"
	curl -f -sS -L -H "Authorization: Bearer $(CRYO_TOKEN)" \
		-H "Accept: application/vnd.github.v3.raw" \
		"https://api.github.com/repos/$(OWNER)/$(REPO)/contents/$(FILE_PATH)?ref=$(REF)" -o $(CRYO_MIRROR)

# 3. Override mirror-cryo to ensure the download happens first
mirror-cryo: $(CRYO_MIRROR)
	@echo "Mirroring local private cryo file..."
	$(ROBOT) convert -i $(CRYO_MIRROR) -o $(TMPDIR)/mirror-cryo.owl

$(ONTOLOGYTERMS): $(SRCMERGED)
	$(ROBOT) query -f csv -i $< --query noes_terms.sparql $@

# Import CryO classes preserving subclass hierarchy to PMDco
$(IMPORTDIR)/tto_import.owl: $(MIRRORDIR)/tto.owl $(IMPORTDIR)/tto_terms.txt
	$(ROBOT) extract --input $< \
	                --method BOT \
	                --term-file $(IMPORTDIR)/tto_terms.txt \
	                --copy-ontology-annotations true \
	                --force true \
	         filter --select "self direct_parents annotations" \
	                --axioms "annotation internal" \
	                --trim true \
	         annotate --ontology-iri $(ONTBASE)/$@ $(ANNOTATE_ONTOLOGY_VERSION) \
	         convert -f owl --output $@.tmp.owl && mv $@.tmp.owl $@

# Import TTO classes preserving subclass hierarchy to PMDco
$(IMPORTDIR)/tto_import.owl: $(MIRRORDIR)/tto.owl $(IMPORTDIR)/tto_terms.txt
	$(ROBOT) filter --input $< \
	                --term-file $(IMPORTDIR)/tto_terms.txt \
	                --select "self parents" \
	                --trim true \
	                --signature true \
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


CITATION=noes: Nonoriented Electrical Steel Ontology. Version $(VERSION), https://w3id.org/pmd/noes/

ALL_ANNOTATIONS=--ontology-iri https://w3id.org/pmd/noes/ -V https://w3id.org/pmd/noes/$(VERSION) \
	--annotation http://purl.org/dc/terms/created "$(TODAY)" \
	--annotation owl:versionInfo "$(VERSION)" \
	--annotation http://purl.org/dc/terms/bibliographicCitation "$(CITATION)" \
	--link-annotation owl:priorVersion https://w3id.org/pmd/noes/$(PRIOR_VERSION)

update-ontology-annotations: 
	$(ROBOT) annotate --input noes.owl $(ALL_ANNOTATIONS) --output ../../noes.owl
	$(ROBOT) annotate --input noes.ttl $(ALL_ANNOTATIONS) --output ../../noes.ttl
	$(ROBOT) annotate --input noes-full.owl $(ALL_ANNOTATIONS) --output ../../noes-full.owl
	$(ROBOT) annotate --input noes-full.ttl $(ALL_ANNOTATIONS) --output ../../noes-full.ttl
	$(ROBOT) annotate --input noes-base.owl $(ALL_ANNOTATIONS) --output ../../noes-base.owl
	$(ROBOT) annotate --input noes-base.ttl $(ALL_ANNOTATIONS) --output ../../noes-base.ttl

all_assets: update-ontology-annotations
