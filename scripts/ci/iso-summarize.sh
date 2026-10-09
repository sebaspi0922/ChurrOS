#!/usr/bin/env bash
# SHA256SUMS junto a las ISO y, si hay GITHUB_STEP_SUMMARY, el resumen del job.
# Uso: iso-summarize.sh DIRECTORIO
# BUILD_COMMIT, BUILD_EDITION y BUILD_ARCH rellenan la tabla.
set -euo pipefail

dir=${1:?falta el directorio de la ISO}
cd "$dir"
mapfile -t isos < <(find . -maxdepth 1 -type f -name '*.iso' -printf '%f\n' | sort)
if [ "${#isos[@]}" -eq 0 ]; then
    echo "iso-summarize: no hay ISO en $dir" >&2
    exit 1
fi

sha256sum -- "${isos[@]}" > SHA256SUMS
cat SHA256SUMS

if [ -z "${GITHUB_STEP_SUMMARY:-}" ]; then
    exit 0
fi

commit=${BUILD_COMMIT:-desconocido}
edition=${BUILD_EDITION:-}
arch=${BUILD_ARCH:-}

{
    echo "### ISO ${arch}"
    echo
    echo "| Campo | Valor |"
    echo "|---|---|"
    echo "| Commit | \`${commit}\` |"
    echo "| Edición | ${edition} |"
    for iso in "${isos[@]}"; do
        bytes=$(stat -c %s "$iso")
        hash=$(awk -v f="$iso" '$2 == f { print $1 }' SHA256SUMS)
        echo "| ISO | \`${iso}\` |"
        echo "| Tamaño | ${bytes} bytes |"
        echo "| sha256 | \`${hash}\` |"
    done
} >> "$GITHUB_STEP_SUMMARY"
