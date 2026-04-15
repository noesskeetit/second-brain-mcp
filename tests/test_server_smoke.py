# tests/test_server_smoke.py
import contextlib
import json
import os
import selectors
import subprocess
import sys
import time


def _run_rpc(env, *messages, timeout=120):
    """Send a list of JSON-RPC messages to the server over stdio and return responses.

    Keeps stdin open until every expected response has been read — closing stdin
    too early lets the anyio-based MCP server cancel the in-flight request
    before it finishes processing. macOS is forgiving about the race; Linux
    CI runners are not.
    """
    cmd = [sys.executable, "-m", "second_brain_mcp.server"]
    expected_ids = {m["id"] for m in messages if "id" in m}

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        bufsize=1,
    )

    for m in messages:
        proc.stdin.write(json.dumps(m) + "\n")
    proc.stdin.flush()

    responses: list[dict] = []
    received_ids: set[int] = set()
    deadline = time.monotonic() + timeout
    sel = selectors.DefaultSelector()
    sel.register(proc.stdout, selectors.EVENT_READ)

    try:
        while received_ids != expected_ids:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"RPC timeout; got ids {received_ids}, expected {expected_ids}")
            events = sel.select(timeout=remaining)
            if not events:
                continue
            line = proc.stdout.readline()
            if not line:
                break
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "id" in obj and obj["id"] in expected_ids:
                responses.append(obj)
                received_ids.add(obj["id"])
    finally:
        sel.close()
        with contextlib.suppress(BrokenPipeError, OSError):
            proc.stdin.close()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    stderr = proc.stderr.read() if proc.stderr else ""
    return responses, stderr


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
