#!/usr/bin/env bash
# Run SPARQL query files against Fuseki and print a text table.
# Usage: scripts/query.sh queries/01-*.rq [more.rq ...]   (default: all queries)
set -euo pipefail
cd "$(dirname "$0")/.."
FUSEKI_URL=${FUSEKI_URL:-http://localhost:3030}
files=("$@"); [[ ${#files[@]} -gt 0 ]] || files=(queries/*.rq)
for f in "${files[@]}"; do
  echo "### $f"
  curl -sf --data-urlencode "query@$f" -H 'Accept: text/plain' "$FUSEKI_URL/rkg/sparql"
  echo
done
