# tests/test_path_traversal.py
import json
import subprocess
import sys


def _call_read(env, rel_path):
    cmd = [sys.executable, "-m", "second_brain_mcp.server"]
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
            "params": {"name": "obsidian_read", "arguments": {"path": rel_path}},
        },
    ]
    payload = "\n".join(json.dumps(m) for m in messages) + "\n"
    proc = subprocess.run(cmd, input=payload, capture_output=True, text=True, env=env, timeout=60)
    lines = [line for line in proc.stdout.splitlines() if line.strip().startswith("{")]
    responses = [json.loads(line) for line in lines]
    return next(r for r in responses if r.get("id") == 2)


def test_rejects_parent_escape(tmp_vault):
    import os

    from second_brain_mcp import indexer

    indexer.rebuild()

    response = _call_read(os.environ.copy(), "../../etc/passwd")
    text = response["result"]["content"][0]["text"]
    assert "error" in text.lower()
    assert "escapes" in text.lower() or "outside" in text.lower()


def test_rejects_absolute_path(tmp_vault):
    import os

    from second_brain_mcp import indexer

    indexer.rebuild()

    response = _call_read(os.environ.copy(), "/etc/passwd")
    text = response["result"]["content"][0]["text"]
    assert "error" in text.lower()


def test_symlink_trap_on_macos(tmp_vault, tmp_path):
    """
    Regression: on macOS `/var` is a symlink to `/private/var`. If obsidian_read
    calls `.resolve()` before the security check, a naive `.relative_to(vault)`
    can mis-judge a symlinked sibling. Guard the correct variant.
    """
    import os

    from second_brain_mcp import indexer

    indexer.rebuild()

    # Build a malicious path that exists but lives outside the vault.
    response = _call_read(os.environ.copy(), "../../../tmp")
    text = response["result"]["content"][0]["text"]
    assert "error" in text.lower()
