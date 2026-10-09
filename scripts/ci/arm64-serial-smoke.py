#!/usr/bin/env python3
"""Humo por consola serie de una ISO aarch64.

Arranca QEMU (KVM si /dev/kvm responde, si no TCG), espera el login del live,
entra como churros y comprueba `uname -m` y `systemctl --failed`.

Códigos: 0 el humo pasa, 1 arrancó y no cumple, 2 no es viable (falta QEMU o
el firmware) y la razón queda en el log y en $GITHUB_STEP_SUMMARY.

Uso: arm64-serial-smoke.py ISO [DIRECTORIO]
"""
import os
import re
import shutil
import socket
import subprocess
import sys
import time

ISO = sys.argv[1] if len(sys.argv) > 1 else ""
OUT = sys.argv[2] if len(sys.argv) > 2 else "serial-smoke"
BOOT_KVM = int(os.environ.get("QA_BOOT_TIMEOUT", "1200"))
BOOT_TCG = int(os.environ.get("QA_BOOT_TIMEOUT_TCG", "2700"))


def summary(text):
    print(text, flush=True)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")


def skip(reason):
    summary("### Humo serie arm64\n\nOmitido: " + reason)
    return 2


def fail(reason):
    summary("### Humo serie arm64\n\nFallo: " + reason)
    return 1


def kvm_probe():
    if not os.path.exists("/dev/kvm") or not os.access("/dev/kvm", os.R_OK | os.W_OK):
        return False, "/dev/kvm no está usable"
    sock = f"/tmp/churros-arm-kvmprobe-{os.getpid()}.sock"
    proc = subprocess.Popen(
        ["qemu-system-aarch64", "-machine", "virt,accel=kvm", "-cpu", "host",
         "-m", "128", "-display", "none", "-nodefaults", "-S",
         "-qmp", f"unix:{sock},server=on,wait=off"],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
    ok, msg = False, "QEMU+KVM no respondió a query-status en 15 s"
    deadline = time.time() + 15
    while time.time() < deadline and proc.poll() is None:
        try:
            conn = socket.socket(socket.AF_UNIX)
            conn.settimeout(3)
            conn.connect(sock)
            reader = conn.makefile("rb")
            reader.readline()
            conn.sendall(b'{"execute":"qmp_capabilities"}\n')
            reader.readline()
            conn.sendall(b'{"execute":"query-status"}\n')
            reply = reader.readline()
            if b"return" in reply:
                ok, msg = True, "QEMU+KVM responde"
            conn.close()
            break
        except (OSError, socket.timeout):
            time.sleep(0.5)
    if proc.poll() is not None and not ok:
        err = proc.stderr.read().decode(errors="replace").strip()[-200:]
        msg = "QEMU con KVM salió: " + err
    proc.kill()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.remove(sock)
    except OSError:
        pass
    return ok, msg


def resolve_pflash(dest):
    os.makedirs(dest, exist_ok=True)
    script = "source scripts/lib/ovmf.sh && churros_resolve_pflash aarch64 \"$1\""
    proc = subprocess.run(["bash", "-c", script, "pflash", dest],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        return None, (proc.stderr or proc.stdout).strip()[-400:]
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    if len(lines) < 2:
        return None, "churros_resolve_pflash no devolvió CODE y VARS"
    return (lines[0], lines[1]), ""


def send(sock_path, text):
    try:
        conn = socket.socket(socket.AF_UNIX)
        conn.settimeout(10)
        conn.connect(sock_path)
        conn.sendall(text.encode())
        time.sleep(0.3)
        conn.close()
        return True
    except OSError as exc:
        print("serie:", exc, flush=True)
        return False


def read_log(path):
    if not os.path.exists(path):
        return ""
    return open(path, "rb").read().decode("utf-8", "replace")


def wait_log(path, pattern, timeout, offset=0):
    rx = re.compile(pattern)
    deadline = time.time() + timeout
    text = ""
    while time.time() < deadline:
        text = read_log(path)
        if rx.search(text[offset:]):
            return text
        time.sleep(2)
    return text


def shell_ready(sock_path, log_path):
    # El comando no contiene el resultado (40+1): el eco del teclado no vale
    # como prueba de que la shell ejecutó.
    for _ in range(6):
        off = os.path.getsize(log_path) if os.path.exists(log_path) else 0
        if not send(sock_path, "churros\r"):
            return False
        chunk = wait_log(log_path, r"Password:|QA_SH_41", 25, off)
        if "Password:" in chunk[off:]:
            send(sock_path, "\r")
            time.sleep(2)
        off = os.path.getsize(log_path) if os.path.exists(log_path) else 0
        if not send(sock_path, "echo QA_SH_$((40+1))\r"):
            return False
        chunk = wait_log(log_path, r"QA_SH_41", 20, off)
        if re.search(r"QA_SH_41", chunk[off:]):
            return True
    return False


def main():
    os.makedirs(OUT, exist_ok=True)
    if not ISO or not os.path.isfile(ISO):
        return fail(f"no está la ISO ({ISO or 'sin ruta'})")
    if shutil.which("qemu-system-aarch64") is None or shutil.which("qemu-img") is None:
        return skip("no está qemu-system-aarch64 o qemu-img; no se puede arrancar la ISO")
    pflash, err = resolve_pflash(os.path.join(OUT, "fw"))
    if not pflash:
        return skip("no hay firmware UEFI aarch64 utilizable (" + err + ")")

    kvm, kvm_msg = kvm_probe()
    print("KVM:", kvm_msg, flush=True)
    accel = "kvm" if kvm else "tcg"
    timeout = BOOT_KVM if kvm else BOOT_TCG
    code, vars_src = pflash
    disk = os.path.join(OUT, "disk.qcow2")
    evars = os.path.join(OUT, "OVMF_VARS.fd")
    subprocess.run(["qemu-img", "create", "-q", "-f", "qcow2", disk, "8G"], check=True)
    subprocess.run(["cp", vars_src, evars], check=True)
    for name in ("serial.sock", "serial.log"):
        path = os.path.join(OUT, name)
        if os.path.exists(path):
            os.remove(path)

    machine = "virt,accel=kvm" if kvm else "virt"
    cpu = "host" if kvm else "cortex-a72"
    vm = OUT
    args = [
        "qemu-system-aarch64", "-name", "churros-arm-serial",
        "-machine", machine, "-cpu", cpu, "-smp", "4", "-m", "4096",
        "-display", "none",
        "-device", "virtio-gpu-pci",
        "-nic", "user,model=virtio-net-pci",
        "-drive", f"if=pflash,format=raw,readonly=on,file={code}",
        "-drive", f"if=pflash,format=raw,file={evars}",
        "-device", "virtio-scsi-pci,id=scsi0",
        "-device", "scsi-cd,bus=scsi0.0,drive=cdrom0,bootindex=0",
        "-drive", f"id=cdrom0,if=none,format=raw,readonly=on,file={ISO}",
        "-device", "virtio-blk-pci,drive=disk0,bootindex=1",
        "-drive", f"id=disk0,if=none,format=qcow2,file={disk}",
        "-chardev", f"socket,id=ser0,path={vm}/serial.sock,server=on,wait=off,logfile={vm}/serial.log",
        "-serial", "chardev:ser0",
    ]
    qlog = open(os.path.join(OUT, "qemu.log"), "w", encoding="utf-8")
    qlog.write(" ".join(args) + "\n")
    qlog.flush()
    proc = subprocess.Popen(args, stdout=qlog, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    sock = os.path.join(OUT, "serial.sock")
    log = os.path.join(OUT, "serial.log")
    try:
        text = wait_log(log, r"login:", timeout)
        if "login:" not in text:
            tail = text[-500:].replace("\n", " | ")
            return fail(f"sin prompt de login en {timeout}s ({accel}). Cola: {tail}")
        if not shell_ready(sock, log):
            return fail(f"no hubo shell de churros por la serie ({accel})")
        off = os.path.getsize(log)
        # Los marcadores no están en el texto tecleado (1+1, 3+4): el eco
        # del teclado no puede adelantar la espera.
        send(sock, "uname -m; echo QA_UNAME_$((1+1)); systemctl --failed --no-legend --plain; echo QA_FAILED_$((3+4))\r")
        text = wait_log(log, r"QA_FAILED_7", 120, off)
        chunk = text[off:]
        if "QA_FAILED_7" not in chunk or "QA_UNAME_2" not in chunk:
            return fail("la serie no devolvió uname/systemctl")
        uname_at = chunk.rfind("QA_UNAME_2")
        failed_at = chunk.rfind("QA_FAILED_7")
        uname_win = chunk[max(0, uname_at - 200):uname_at]
        between = chunk[uname_at:failed_at]
        arch_ok = re.search(r"(?m)^aarch64\s*$", uname_win) or re.search(r"\baarch64\b", uname_win)
        units = []
        for line in between.splitlines():
            line = line.strip()
            if not line or line.startswith("QA_") or "systemctl" in line or line.startswith("echo "):
                continue
            if ".service" in line or ".mount" in line or ".scope" in line or "loaded failed" in line:
                units.append(line)
        detail = f"accel={accel}; uname={'aarch64' if arch_ok else 'NO'}; failed={len(units)}"
        if units:
            detail += "; " + " | ".join(units[:6])
        if not arch_ok or units:
            return fail(detail)
        summary("### Humo serie arm64\n\n" + detail)
        return 0
    finally:
        proc.kill()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            pass
        qlog.close()
        for name in ("disk.qcow2", "OVMF_VARS.fd"):
            try:
                os.remove(os.path.join(OUT, name))
            except OSError:
                pass


if __name__ == "__main__":
    sys.exit(main())
