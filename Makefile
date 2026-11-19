PY    := .venv/bin/python
QUERY ?= queries/*.rq

.PHONY: build validate test up down load query clean

.venv: requirements.txt
	python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt && touch .venv

build: .venv            ## CSV -> data/graph.ttl (fails on SHACL violations)
	$(PY) scripts/build_graph.py

validate: .venv         ## Re-validate the committed graph against the shapes
	.venv/bin/pyshacl -s shapes/rkg-shapes.ttl -f human data/graph.ttl

test: .venv
	.venv/bin/pytest -q

up:                     ## Start Fuseki (dataset "rkg" persisted in a Docker volume)
	docker compose up -d --wait

down:
	docker compose down

load:                   ## Upload ontology + graph into Fuseki
	scripts/load.sh

query:                  ## Run queries: make query [QUERY=queries/05-*.rq]
	scripts/query.sh $(QUERY)

clean:
	docker compose down -v
