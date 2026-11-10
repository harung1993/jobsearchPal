# jobsearchPal in one image: Python, Playwright's Chromium, LibreOffice (docx -> pdf), and the agent CLIs.
# Your files (config, profile, materials, data) stay in the repo folder, which compose mounts at /app.
FROM node:22-bookworm-slim AS node

FROM mcr.microsoft.com/playwright/python:v1.49.1-noble
ARG INSTALL_CLAUDE=1
ARG INSTALL_CODEX=1
ENV DEBIAN_FRONTEND=noninteractive PIP_NO_CACHE_DIR=1 PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv PATH=/opt/venv/bin:$PATH \
    HOME=/home/app DISABLE_AUTOUPDATER=1 AUTOAPPLY_HOST=0.0.0.0 \
    PYTHONPATH=/app

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3-venv libreoffice-writer-nogui fonts-liberation tzdata curl ca-certificates git \
 && rm -rf /var/lib/apt/lists/*
# Node for the agent CLIs (Ubuntu's is too old for them).
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
 && pkgs="" \
 && if [ "$INSTALL_CLAUDE" = 1 ]; then pkgs="$pkgs @anthropic-ai/claude-code"; fi \
 && if [ "$INSTALL_CODEX" = 1 ]; then pkgs="$pkgs @openai/codex"; fi \
 && if [ -n "$pkgs" ]; then npm install -g $pkgs && npm cache clean --force; fi

# Python deps first. The code that runs is the mounted /app (PYTHONPATH), so git pull + restart updates it;
# rebuild only when dependencies change. Playwright is pinned to the image's browsers.
WORKDIR /opt/jobsearchpal
COPY pyproject.toml README.md ./
COPY autoapply ./autoapply
RUN python3 -m venv $VIRTUAL_ENV \
 && pip install playwright==1.49.1 \
 && pip install -e ".[dev]"

# Any user id can run it (compose passes yours, so files in the mounted folder stay yours).
# Agent logins (~/.claude, ~/.claude.json, ~/.codex) live in the home volume.
RUN mkdir -p /home/app && chmod 1777 /home/app
WORKDIR /app
EXPOSE 8787
CMD ["autoapply", "serve"]
