import asyncio
import json
import os
import sys
from typing import Any

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from opsagent.mcp_server.server import build_server
from tests.integration.scripted import DATA, ScriptedLLM, build_test_container, truth_for

pytestmark = pytest.mark.integration

READ_ONLY_TOOLS = {
    "list_invoices",
    "get_invoice",
    "get_stats",
    "get_daily_report",
    "search_vendors",
    "list_open_purchase_orders",
    "get_purchase_order",
    "find_payments",
}
WRITE_TOOLS = {
    "ingest_invoice",
    "process_invoice",
    "process_pending",
    "review_invoice",
    "generate_daily_report",
}


def _call(server: MCPServer, name: str, **arguments: Any) -> Any:
    result = asyncio.run(server.call_tool(name, arguments))
    assert isinstance(result, CallToolResult)
    assert not result.is_error, result
    text = result.content[0].text  # type: ignore[union-attr]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


@pytest.fixture
def server_and_llm(session_factory: sessionmaker[Session]) -> tuple[MCPServer, ScriptedLLM]:
    llm = ScriptedLLM()
    return build_server(build_test_container(session_factory, llm)), llm


def test_tools_are_annotated_read_only_or_not(
    server_and_llm: tuple[MCPServer, ScriptedLLM],
) -> None:
    server, _ = server_and_llm
    tools = {t.name: t for t in asyncio.run(server.list_tools())}

    assert set(tools) == READ_ONLY_TOOLS | WRITE_TOOLS
    for name in READ_ONLY_TOOLS:
        assert tools[name].annotations.read_only_hint is True, name  # type: ignore[union-attr]
    for name in WRITE_TOOLS:
        assert tools[name].annotations.read_only_hint is False, name  # type: ignore[union-attr]


def test_claude_can_ingest_process_investigate_and_record_a_human_review(
    server_and_llm: tuple[MCPServer, ScriptedLLM],
) -> None:
    server, llm = server_and_llm
    truth = truth_for("amount_mismatch")
    llm.current = truth

    ingested = _call(server, "ingest_invoice", file_path=str(DATA / "invoices" / truth.file))
    decided = _call(server, "process_invoice", invoice_id=ingested["invoice_id"])
    queue = _call(server, "list_invoices", needs_review=True)
    detail = _call(server, "get_invoice", invoice_id=ingested["invoice_id"])
    po = _call(server, "get_purchase_order", po_number=truth.extraction.po_number)
    reviewed = _call(
        server,
        "review_invoice",
        invoice_id=ingested["invoice_id"],
        outcome="rejected",
        reviewer="carlos",
        note="Cobra unidades no pedidas.",
    )

    assert decided["action"] == "human_review"
    assert queue["items"][0]["id"] == ingested["invoice_id"]
    assert "amount_mismatch" in {f["code"] for f in detail["decisions"][0]["findings"]}
    assert po["result"]["po_number"] == truth.extraction.po_number
    assert reviewed["outcome"] == "rejected"
    after = _call(server, "get_invoice", invoice_id=ingested["invoice_id"])
    assert after["decisions"][-1]["actor"] == "human:carlos (via MCP)"


def test_errors_are_returned_to_the_client_not_raised(
    server_and_llm: tuple[MCPServer, ScriptedLLM],
) -> None:
    server, _ = server_and_llm
    assert "error" in _call(server, "ingest_invoice", file_path="/no/such/file.pdf")
    assert "error" in _call(
        server,
        "review_invoice",
        invoice_id="00000000-0000-0000-0000-000000000000",
        outcome="approved",
        reviewer="x",
    )


def test_stdio_transport_speaks_clean_mcp(db_engine: Engine) -> None:
    """Spawn the real server process: any stray print/log on stdout would break this."""
    env = dict(os.environ)
    env |= {
        "DATABASE_URL": db_engine.url.render_as_string(hide_password=False),
        "LLM_MODE": "replay",
        "LOG_LEVEL": "INFO",
    }
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "opsagent.mcp_server"], env=env
    )

    async def session_roundtrip() -> tuple[set[str], str]:
        async with (
            stdio_client(params) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            tools = await session.list_tools()
            prompt = await session.get_prompt("triage_review_queue")
            return {t.name for t in tools.tools}, str(prompt.messages[0].content)

    names, prompt = asyncio.run(asyncio.wait_for(session_roundtrip(), timeout=60))
    assert names == READ_ONLY_TOOLS | WRITE_TOOLS
    assert "review_invoice" in prompt
