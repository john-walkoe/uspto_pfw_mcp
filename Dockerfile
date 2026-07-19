FROM python:3.11-slim

# Install curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Dependency layer — cached unless pyproject.toml or uv.lock changes
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev

# Source and config
COPY src/ ./src/
COPY field_configs.yaml ./
COPY reference/ ./reference/
COPY scripts/ ./scripts/

# Run as non-root (audit L11). Home dir needed: logs/keys/data live under
# ~/.uspto_pfw_mcp
RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER appuser

# HTTP transport — overridden per-service in docker-compose.yml
ENV FASTMCP_TRANSPORT=http
ENV FASTMCP_HOST=0.0.0.0
ENV FASTMCP_PORT=8001

# Download proxy — set PROXY_BIND_HOST=0.0.0.0 in Docker (done in docker-compose.yml)
# so the host browser can reach download links via the mapped port.
ENV PFW_PROXY_PORT=8080
ENV PROXY_BIND_HOST=127.0.0.1

# Expose MCP port and download proxy port
EXPOSE 8001
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=15s \
  CMD curl -sf "http://localhost:${FASTMCP_PORT:-8001}/health" || exit 1

CMD ["uv", "run", "patent-filewrapper-mcp"]
