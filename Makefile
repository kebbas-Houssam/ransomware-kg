PY    := .venv/bin/python
QUERY ?= queries/*.rq

.PHONY: build validate test up down load query ingest bench mcp ui clean

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

ingest:                 ## Index chapter 4 of docs/master.pdf -> index/
	$(PY) -m rag.ingest

bench:                  ## Both question sets x 5 modes -> results/benchmark.md
	$(PY) -m bench.run

mcp:                    ## Run the read-only MCP server on stdio
	$(PY) -m mcp_server

ui:                     ## Streamlit UI on http://localhost:8501
	.venv/bin/streamlit run ui/app.py

clean:
	docker compose down -v
