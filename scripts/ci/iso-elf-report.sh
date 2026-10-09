#!/usr/bin/env bash
# file(1) sobre los binarios de una ISO aarch64: Rust (churros-*), Calamares,
# Bazaar, yay, wlogout y libdex. Calamares entra en el live como paquete bajo
# /root/packages, no como fichero ya instalado: se abre el .pkg.tar.* .
# Falla si falta alguno o si un ELF no es ARM aarch64.
# Uso: iso-elf-report.sh ISO [INFORME]
set -euo pipefail

iso=${1:?falta la ISO}
report=${2:-elf-report.txt}

if [ ! -f "$iso" ]; then
    echo "no existe $iso" >&2
    exit 1
fi

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

sfs=$tmp/airootfs.sfs
sfs_path=""
for candidate in /churros/aarch64/airootfs.sfs /churros/x86_64/airootfs.sfs; do
    rm -f "$sfs"
    if xorriso -osirrox on -indev "$iso" -extract "$candidate" "$sfs" >/dev/null 2>"$tmp/xorriso.err"; then
        sfs_path=$candidate
        break
    fi
done
if [ -z "$sfs_path" ]; then
    found=$(xorriso -indev "$iso" -find / -name airootfs.sfs 2>/dev/null || true)
    sfs_path=$(printf '%s\n' "$found" | grep -m 1 -o '/[[:alnum:]/_.-]*airootfs\.sfs' || true)
    rm -f "$sfs"
    if [ -z "$sfs_path" ] || ! xorriso -osirrox on -indev "$iso" -extract "$sfs_path" "$sfs" >/dev/null; then
        echo "la ISO no contiene airootfs.sfs" >&2
        cat "$tmp/xorriso.err" >&2 || true
        exit 1
    fi
fi

root=$tmp/root
pkg_root=$tmp/pkgs
mkdir -p "$root" "$pkg_root"
# Un glob que no existe hace que unsquashfs salga distinto de 0.
unsquashfs -d "$root" -wildcards "$sfs" \
    'usr/bin/churros-*' \
    'usr/bin/yay' \
    'usr/bin/wlogout' \
    'usr/bin/bazaar' \
    'usr/lib/libdex*' \
    'usr/lib/*/libdex*' \
    'root/packages/*.pkg.tar.*' \
    || true

if [ -d "$root/root/packages" ]; then
    shopt -s nullglob
    for pkg in "$root/root/packages/"*.pkg.tar.*; do
        base=$(basename "$pkg")
        case "$base" in
            *debug*|*.sig) continue ;;
        esac
        dest=$pkg_root/${base%%.pkg.tar.*}
        mkdir -p "$dest"
        bsdtar -xf "$pkg" -C "$dest"
    done
    shopt -u nullglob
fi

: > "$report"
fail=0

note() {
    printf '%s\n' "$*" | tee -a "$report"
}

require_elf() {
    local label=$1
    shift
    local found=0
    local f info
    for f in "$@"; do
        [ -f "$f" ] || continue
        [ -L "$f" ] && continue
        found=1
        info=$(file -L "$f")
        note "$info"
        case "$info" in
            *ELF*"ARM aarch64"*) ;;
            *ELF*)
                note "ERROR: $label no es ARM aarch64: $f"
                fail=1
                ;;
            *)
                note "ERROR: $label no es un ELF: $f"
                fail=1
                ;;
        esac
    done
    if [ "$found" -eq 0 ]; then
        note "ERROR: no está $label"
        fail=1
    fi
}

collect() {
    local name=$1
    shift
    local dir f
    for dir in "$@"; do
        [ -d "$dir" ] || continue
        while IFS= read -r f; do
            [ -n "$f" ] || continue
            printf '%s\n' "$f"
        done < <(find "$dir" -name "$name" -type f | sort -u)
    done
}

note "ISO: $(basename "$iso")"
note "squashfs: $sfs_path"
note ""
note "== churros-* en usr/bin (scripts y ELF) =="
if [ -d "$root/usr/bin" ]; then
    find "$root/usr/bin" -name 'churros-*' -type f | sort | while IFS= read -r f; do
        file -L "$f" | tee -a "$report"
    done
fi
note ""
note "== ELF exigidos =="

rust=()
for name in churros-welcome churros-settings churros-popup churros-control-center churros-tour; do
    if [ -f "$root/usr/bin/$name" ]; then
        rust+=("$root/usr/bin/$name")
    fi
done
if [ "${#rust[@]}" -eq 0 ]; then
    note "ERROR: no hay binarios Rust churros-* en usr/bin"
    fail=1
else
    require_elf "Rust churros-*" "${rust[@]}"
fi

mapfile -t cal < <(collect calamares "$root" "$pkg_root" | awk '/\/usr\/bin\/calamares$/')
require_elf "Calamares" ${cal[@]+"${cal[@]}"}

mapfile -t baz < <(collect bazaar "$root" "$pkg_root" | awk '/\/usr\/bin\/bazaar$/')
require_elf "Bazaar" ${baz[@]+"${baz[@]}"}

mapfile -t yay_bins < <(collect yay "$root" "$pkg_root" | awk '/\/usr\/bin\/yay$/')
require_elf "yay" ${yay_bins[@]+"${yay_bins[@]}"}

mapfile -t wlog < <(collect wlogout "$root" "$pkg_root" | awk '/\/usr\/bin\/wlogout$/')
require_elf "wlogout" ${wlog[@]+"${wlog[@]}"}

mapfile -t dex < <(collect 'libdex*.so*' "$root" "$pkg_root")
require_elf "libdex" ${dex[@]+"${dex[@]}"}

note ""
if [ "$fail" -ne 0 ]; then
    note "RESULTADO: hay binarios que no son ARM aarch64 o faltan"
    exit 1
fi
note "RESULTADO: todos los ELF exigidos son ARM aarch64"
