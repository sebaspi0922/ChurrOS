#!/usr/bin/env bash
# Humo de churros-verify sobre una ISO ya construida.
# BUILD_SHA, BUILD_REF, EDITION e ISO_NAME vienen del job de build.
# El pipeline devuelve 0 aunque el veredicto sea RECHAZADO: este script
# mira el informe y sale 1 en ese caso.
set -euo pipefail

: "${BUILD_SHA:?}"
: "${BUILD_REF:?}"
: "${EDITION:?}"
: "${ISO_NAME:?}"

iso="iso/${ISO_NAME}"
if [ ! -f "$iso" ]; then
    echo "no está la ISO descargada: $iso" >&2
    ls -la iso >&2 || true
    exit 1
fi

(
    cd iso
    sha256sum -c SHA256SUMS
)

git fetch --no-tags origin main
if ! git rev-parse --verify "${BUILD_SHA}^{commit}" >/dev/null 2>&1; then
    git fetch --no-tags origin "$BUILD_REF"
fi
git rev-parse --verify "${BUILD_SHA}^{commit}"

run_id="gha-${GITHUB_RUN_ID:-local}-${EDITION}"
export QA_NESTED_TIMEOUT="${QA_NESTED_TIMEOUT:-600}"

scripts/qa/churros-verify cache-iso "$BUILD_SHA" "$PWD/$iso" --edition "$EDITION" --arch x86_64

set +e
scripts/qa/churros-verify run "$BUILD_SHA" \
    --edition "$EDITION" \
    --arch x86_64 \
    --fg \
    --until smoke \
    --run-id "$run_id"
run_rc=$?
set -e

scripts/qa/churros-verify report "$run_id" | tee smoke-verdict.txt

report="scripts/qa/runs/${run_id}/report.md"
if [ -n "${GITHUB_STEP_SUMMARY:-}" ] && [ -f "$report" ]; then
    {
        echo "### Humo x86_64"
        echo
        echo '```'
        sed -n '1,80p' "$report"
        echo '```'
    } >> "$GITHUB_STEP_SUMMARY"
fi

if [ "$run_rc" -ne 0 ]; then
    echo "el pipeline salió con rc=$run_rc" >&2
    exit "$run_rc"
fi
if grep -q 'VEREDICTO: RECHAZADO' smoke-verdict.txt; then
    echo "veredicto RECHAZADO" >&2
    exit 1
fi
