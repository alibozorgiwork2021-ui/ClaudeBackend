# ClaudeBackend CLI + MCP server image.
#
# Build context is the repo root: `docker build -f docker/Dockerfile .`
# Used by docker-compose.yml for the fully local, air-gapped Ollama stack.
FROM python:3.11-slim

WORKDIR /app

# Install the package and its dependencies from source.
COPY pyproject.toml README.md ./
COPY claudebackend ./claudebackend
RUN pip install --no-cache-dir .

# The target project is mounted here at runtime (see docker-compose.yml).
WORKDIR /work

# `claudebackend develop /work "<objective>" ...` or `claudebackend mcp`.
ENTRYPOINT ["claudebackend"]
CMD ["--help"]
