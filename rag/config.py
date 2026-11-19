"""Settings read from the environment / .env (see .env.example)."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, "").strip() or default


LLM_PROVIDER = env("LLM_PROVIDER", "ollama").lower()
LLM_MODEL = env("LLM_MODEL")
OLLAMA_HOST = env("OLLAMA_HOST", "http://localhost:11434")
FUSEKI_URL = env("FUSEKI_URL", "http://localhost:3030")
SPARQL_ENDPOINT = f"{FUSEKI_URL}/rkg/sparql"
EMBED_MODEL = env("EMBED_MODEL", "intfloat/multilingual-e5-base")
THESIS_PDF = ROOT / env("THESIS_PDF", "docs/master.pdf")
INDEX_DIR = ROOT / "index"
PAPERS_CSV = ROOT / "data/papers.csv"
ONTOLOGY = ROOT / "ontology/rkg.ttl"
