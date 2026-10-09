#!/usr/bin/env bash
# Quita toolchains preinstalados de un runner de GitHub para dejar sitio a
# mkarchiso (work/ de la ISO cabe en decenas de GiB). No toca docker.
set -euo pipefail

sudo rm -rf \
    /usr/share/dotnet \
    /usr/local/lib/android \
    /opt/ghc \
    /usr/local/share/boost \
    /usr/local/lib/node_modules \
    /usr/share/swift \
    /usr/local/.ghcup \
    /opt/hostedtoolcache \
    /usr/local/share/chromium \
    /usr/local/share/powershell \
    /usr/share/miniconda \
    /usr/local/julia \
    || true

if command -v docker >/dev/null 2>&1; then
    docker image prune -af || true
fi

df -h
