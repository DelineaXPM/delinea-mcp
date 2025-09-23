FROM ghcr.io/astral-sh/uv:0.8.22-python3.13-trixie-slim@sha256:dcbd347aea4390385eabf95e56c7dabe8be38696e1a74ec7084bf7dc0a9641e1


# Ensure stdout/stderr are not buffered and bytecode files are not written
# Use system Python by default with uv's pip interface
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_CACHE_DIR=/root/.cache/uv \
    UV_PYTHON_CACHE_DIR=/root/.cache/uv/python \
    UV_TOOL_BIN_DIR=/usr/local/bin

WORKDIR /app

# Install Node.js for the MCP CLI (if used) and supporting tools
ARG NODE_VERSION=20
RUN --mount=type=cache,target=/var/cache/apt/archives \
    apt-get update \
    && apt-get install -y --no-install-recommends curl gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_${NODE_VERSION}.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies using uv (system environment)
COPY requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install -r requirements.txt

# Copy application source
COPY . .

# Create data directory and add non-root user for runtime
RUN groupadd -r app && useradd -r -g app -d /app -s /sbin/nologin app \
    && mkdir -p /app/data \
    && chown -R app:app /app

USER app

EXPOSE 8000

# Persist OAuth database and key files
VOLUME ["/app/data"]

# Start the server directly
ENTRYPOINT ["python", "server.py"]
