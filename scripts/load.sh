#!/usr/bin/env bash
# Upload the ontology and the instance graph into the Fuseki dataset "rkg".
# Each file goes to its own named graph with HTTP PUT, so re-running replaces
# the previous content instead of duplicating it.
set -euo pipefail
cd "$(dirname "$0")/.."

FUSEKI_URL=${FUSEKI_URL:-http://localhost:3030}
GSP="$FUSEKI_URL/rkg/data"

put() {  # put <file> <graph-iri>
  local code
  code=$(curl -s -o /dev/null -w '%{http_code}' -X PUT \
         -H 'Content-Type: text/turtle' --data-binary "@$1" \
         "$GSP?graph=$(python3 -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1],safe=""))' "$2")")
  [[ $code == 2* ]] || { echo "upload of $1 failed (HTTP $code)" >&2; exit 1; }
  echo "loaded $1 -> <$2>"
}

[[ -f data/graph.ttl ]] || { echo "data/graph.ttl missing; run 'make build' first" >&2; exit 1; }
put ontology/rkg.ttl https://w3id.org/rkg/graph/ontology
put data/graph.ttl   https://w3id.org/rkg/graph/data
