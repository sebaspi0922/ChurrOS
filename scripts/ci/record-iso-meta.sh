#!/usr/bin/env bash
# Tras el build: commit, nombre de la ISO y clave de artefacto.
# Uso: record-iso-meta.sh DIRECTORIO_OUT
# Requiere BUILD_EDITION, BUILD_ARCH y BUILD_REF_NAME. Escribe en $GITHUB_OUTPUT.
set -euo pipefail

out_dir=${1:?falta el directorio de la ISO}
sha=$(git rev-parse HEAD)
mapfile -t isos < <(find "$out_dir" -maxdepth 1 -type f -name '*.iso' -printf '%f\n' | sort)
iso=${isos[0]:-}
if [ -z "$iso" ]; then
    echo "record-iso-meta: no hay ISO en $out_dir" >&2
    exit 1
fi
short=${sha:0:12}
edition=${BUILD_EDITION:-niri}
arch=${BUILD_ARCH:?falta BUILD_ARCH}
ref_name=${BUILD_REF_NAME:-$sha}

if [ -z "${GITHUB_OUTPUT:-}" ]; then
    printf 'sha=%s\nshort=%s\niso_name=%s\nedition=%s\nref=%s\nartifact=%s\n' \
        "$sha" "$short" "$iso" "$edition" "$ref_name" \
        "churros-${arch}-${edition}-${short}"
    exit 0
fi

{
    echo "sha=$sha"
    echo "short=$short"
    echo "iso_name=$iso"
    echo "edition=$edition"
    echo "ref=$ref_name"
    echo "artifact=churros-${arch}-${edition}-${short}"
} >> "$GITHUB_OUTPUT"
