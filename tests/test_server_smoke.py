# tests/test_server_smoke.py
import json
import os
import subprocess
import sys


def _run_rpc(env, *messages):
    """Send a list of JSON-RPC messages to the server over stdio and return responses."""
    cmd = [sys.executable, "-m", "second_brain_mcp.server"]
    payload = "\n".join(json.dumps(m) for m in messages) + "\n"
    proc = subprocess.run(
        cmd,
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    lines = [line for line in proc.stdout.splitlines() if line.strip().startswith("{")]
    return [json.loads(line) for line in lines], proc.stderr


def test_overview_returns_protocol_and_stats(tmp_vault, monkeypatch):
    # Pre-build the index so the server doesn't have to on the first call.
    from second_brain_mcp import indexer

    indexer.rebuild()

    env = os.environ.copy()
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "smoke", "version": "0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "obsidian_overview", "arguments": {}},
        },
    ]
    responses, stderr = _run_rpc(env, *messages)
    overview = next(r for r in responses if r.get("id") == 2)
    text = overview["result"]["content"][0]["text"]
    assert "OBSIDIAN MEMORY PROTOCOL" in text
    assert '"notes":' in text or "'notes':" in text


def test_prompt_to_obsidian_is_listed(tmp_vault):
    import os

    env = os.environ.copy()

    # The MCP stdio server cancels in-flight requests when stdin hits EOF, so
    # we issue prompts/list and prompts/get in two separate subprocess sessions
    # rather than batching four messages into one (which drops the last one).
    base_init = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "smoke", "version": "0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
    ]

    list_responses, _ = _run_rpc(
        env,
        *base_init,
        {"jsonrpc": "2.0", "id": 3, "method": "prompts/list", "params": {}},
    )
    lst = next(r for r in list_responses if r.get("id") == 3)
    assert any(p["name"] == "to_obsidian" for p in lst["result"]["prompts"])

    get_responses, _ = _run_rpc(
        env,
        *base_init,
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "prompts/get",
            "params": {"name": "to_obsidian", "arguments": {}},
        },
    )
    got = next(r for r in get_responses if r.get("id") == 4)
    text = got["result"]["messages"][0]["content"]["text"]
    assert "DO NOT use `obsidian-cli create`" in text
    assert "approval" in text.lower()
