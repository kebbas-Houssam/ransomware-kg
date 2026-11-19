import asyncio

import pytest
from mcp import Client
from mcp.server.mcpserver.exceptions import ToolError

from mcp_server.server import checked_query, mcp
from rag.ask import drop_unsupported_numbers, enforce_rows


def test_sparql_guard():
    assert checked_query("SELECT ?p WHERE { ?p a rkg:Paper }").endswith("LIMIT 100")
    assert checked_query("SELECT ?p WHERE { ?p a rkg:Paper } LIMIT 5").count("LIMIT") == 1
    assert "LIMIT" not in checked_query("ASK { ?p a rkg:Paper }")
    for bad in ("DELETE WHERE { ?s ?p ?o }", "INSERT DATA { <a:a> <a:b> <a:c> }",
                "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }", "DROP ALL"):
        with pytest.raises(ToolError):
            checked_query(bad)


def test_server_exposes_read_only_tools():
    async def tools():
        async with Client(mcp) as c:
            return (await c.list_tools()).tools
    ts = asyncio.run(tools())
    assert {t.name for t in ts} == {"get_schema", "sparql_select", "search_papers",
                                    "get_paper", "get_results", "search_thesis"}
    assert all(t.annotations.read_only_hint for t in ts)


def test_hybrid2_numbers_come_from_rows():
    rows = [{"count": "9"}]
    assert enforce_rows("Nine papers (9) target Windows.", rows, "en").startswith("Nine")
    assert enforce_rows("Two papers target Windows.", rows, "en").startswith("Knowledge graph: count = 9")
    assert drop_unsupported_numbers("It reaches 98.7%. It uses eBPF.", "no numbers here") == "It uses eBPF."
