# syntax=docker/dockerfile:1.7
#
# second-brain-mcp — self-contained image.
# Everything the server needs is baked in via uv+uv.lock: Python 3.12,
# chromadb, mcp, starlette, uvicorn, openai. No torch, no on-device
# embedder — embedding is delegated to an OpenAI-compatible HTTP endpoint
# configured at runtime. Image stays well under 1 GB, zero model
# downloads at build or first run.

# ---------- builder ----------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Dep-only layer so edits to source don't invalidate the (slow) install.
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

COPY src/ ./src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# ---------- runtime ----------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    OBSIDIAN_MCP_TRANSPORT=http \
    OBSIDIAN_MCP_HOST=0.0.0.0 \
    OBSIDIAN_MCP_PORT=8765 \
    OBSIDIAN_MCP_PATH=/mcp \
    OBSIDIAN_VAULT=/vault \
    OBSIDIAN_INDEX_DIR=/index

# Non-root user. Vault, index volumes are chowned to this UID/GID below.
# If you mount a vault owned by another user, override `user:` in compose
# or pre-chown on the host.
RUN groupadd --system --gid 1000 mcp \
 && useradd  --system --uid 1000 --gid mcp --home-dir /home/mcp --create-home mcp

WORKDIR /app

COPY --from=builder --chown=mcp:mcp /app /app

RUN mkdir -p /vault /index \
 && chown -R mcp:mcp /vault /index

USER mcp

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys,os; \
url=f'http://127.0.0.1:{os.environ.get(\"OBSIDIAN_MCP_PORT\",\"8765\")}/.well-known/oauth-protected-resource'; \
sys.exit(0 if urllib.request.urlopen(url, timeout=3).status == 200 else 1)" \
  || exit 1

ENTRYPOINT ["second-brain-mcp"]
CMD ["serve"]
