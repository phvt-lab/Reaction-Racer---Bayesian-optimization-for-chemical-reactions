#!/usr/bin/env bash
# Build the ReactionRacer one-dir desktop bundle into dist/ReactionRacer/.
set -euo pipefail
cd "$(dirname "$0")"
./.venv/bin/pyinstaller --noconfirm reaction_racer.spec
