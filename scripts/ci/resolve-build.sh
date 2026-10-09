#!/usr/bin/env bash
# Resuelve la ref y la edición de un workflow_dispatch o del schedule.
# Lee INPUT_REF, INPUT_EDITION, GITHUB_EVENT_NAME, GITHUB_REF_NAME y
# CHURROS_ISO_ARCH (aarch64 rechaza cualquier edición que no sea niri).
# Escribe ref y edition en $GITHUB_OUTPUT, o por stdout si no existe.
set -euo pipefail

if [ "${GITHUB_EVENT_NAME:-}" = "schedule" ]; then
    ref=main
    edition=niri
else
    ref=${INPUT_REF:-${GITHUB_REF_NAME:-main}}
    edition=${INPUT_EDITION:-niri}
fi

case "$edition" in
    niri|xfce|kde|server) ;;
    *)
        echo "Edición no válida: $edition (niri, xfce, kde, server)" >&2
        exit 1
        ;;
esac

if [ "${CHURROS_ISO_ARCH:-}" = "aarch64" ] && [ "$edition" != "niri" ]; then
    echo "La ISO aarch64 solo tiene la edición niri." >&2
    exit 1
fi

# Rama, tag o SHA. Sin espacios ni metacaracteres de shell.
case "$ref" in
    ""|*[!A-Za-z0-9._/+-]*)
        echo "Ref no válida: $ref" >&2
        exit 1
        ;;
esac

if [ -z "${GITHUB_OUTPUT:-}" ]; then
    printf 'ref=%s\nedition=%s\n' "$ref" "$edition"
    exit 0
fi

{
    echo "ref=$ref"
    echo "edition=$edition"
} >> "$GITHUB_OUTPUT"
