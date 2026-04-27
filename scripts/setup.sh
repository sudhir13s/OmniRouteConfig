#!/usr/bin/env bash
# Idempotent OmniRoute prerequisites installer.
# Safe to re-run.

set -euo pipefail

log() { printf '\033[36m[setup]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[setup]\033[0m %s\n' "$*" >&2; }

# ---------- Node.js ----------

if command -v node >/dev/null 2>&1; then
  NODE_VERSION="$(node --version)"
  log "node found: $NODE_VERSION"
else
  warn "node not found."
  warn "Install Node 20+ from https://nodejs.org/ or via your package manager:"
  warn "  macOS:   brew install node"
  warn "  Ubuntu:  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - && sudo apt install -y nodejs"
  warn "  Then re-run this script."
  exit 1
fi

# ---------- npm cache for omniroute ----------

if command -v npm >/dev/null 2>&1; then
  log "npm found: $(npm --version)"
else
  warn "npm not found. Install Node.js (it ships with npm)."
  exit 1
fi

# ---------- Optional: Docker ----------

if command -v docker >/dev/null 2>&1; then
  log "docker found: $(docker --version)"
else
  log "docker NOT found (optional — only needed for the docker run path)."
fi

# ---------- Pre-fetch OmniRoute via npx so first `omni-route-config init`
# doesn't pay the install cost ----------

log "Pre-fetching omniroute via npx (first-run cache warm)..."
npx -y omniroute@latest --version >/dev/null 2>&1 || warn "npx omniroute@latest failed; will retry at first init."

# ---------- Python deps ----------

if command -v python3 >/dev/null 2>&1; then
  log "python found: $(python3 --version)"
else
  warn "python3 not found. Install Python 3.11+."
  exit 1
fi

log "Setup complete. Next:"
log "  1. cp .env.example .env   # paste your provider API keys"
log "  2. omni-route-config init        # start OmniRoute"
log "  3. omni-route-config configure   # push catalog -> OmniRoute"
log "  4. omni-route-config status      # verify"
