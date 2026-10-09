#!/usr/bin/env bash
# Deja /dev/kvm legible para el usuario del runner. En GitHub el nodo existe,
# pero el grupo kvm y el modo 0660 no incluyen a ese usuario.
set -euo pipefail

if [ ! -e /dev/kvm ]; then
    echo "no hay /dev/kvm"
    exit 0
fi

echo 'KERNEL=="kvm", GROUP="kvm", MODE="0666", OPTIONS+="static_node=kvm"' \
    | sudo tee /etc/udev/rules.d/99-kvm4all.rules >/dev/null
sudo udevadm control --reload-rules
sudo udevadm trigger --name-match=kvm || sudo udevadm trigger || true
sudo chmod 666 /dev/kvm || true
ls -l /dev/kvm
