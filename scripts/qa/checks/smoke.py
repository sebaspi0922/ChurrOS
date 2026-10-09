"""Smoke fijo de 12 puntos. Corre siempre primero, antes de las pruebas del diff.
Puntos 1-6 y 11 se miden en la sesión real que lanza greetd. KVM y 3D se
deciden por separado: si el host no tiene /dev/dri, 7-10 corren en Niri anidado
en cage y el 6 se repite ahí. Con 3D (virtio-vga-gl) 7-10 se quedan en la
sesión real. El 12 se toma al final."""
import os, re, time
from checks.common import Ctx, load_allowlist, filter_allowed
import qalib

SMOKE = [
    ("01-boot", "Arranque hasta login"),
    ("02-failed-units", "systemctl --failed vacío"),
    ("03-greetd", "greetd activo y autologin en Niri"),
    ("04-niri-socket", "NIRI_SOCKET responde (niri msg)"),
    ("05-noctalia", "Noctalia corriendo y respondiendo"),
    ("06-no-legacy", "swaybg / waybar / mako NO corren"),
    ("07-mod-space", "Mod+Space abre el lanzador de Noctalia"),
    ("08-mod-c", "Mod+C abre el centro de control de Noctalia"),
    ("09-lock", "Bloqueo de pantalla (noctalia msg session lock)"),
    ("10-notification", "Notificación mostrada por Noctalia"),
    ("11-fc-inter", "fc-match Inter resuelve a Inter"),
    ("12-journal", "journal sin errores fuera de la allowlist"),
]
TITLES = dict(SMOKE)
LEGACY = ["swaybg", "waybar", "mako"]


def R(ctx, cid, status, detail="", evidence=None, t0=None):
    ev = [ctx.rel(e) for e in (evidence or []) if e]
    return qalib.add_result(ctx.run_id, "smoke", cid, TITLES[cid], status, detail, ev,
                            None if t0 is None else time.time() - t0)


def ensure_nested(ctx):
    """Cambia la sesión de greetd a Niri-dentro-de-cage. Idempotente.
    Solo se usa cuando el host no tiene 3D."""
    rc, _ = ctx.cmd("pgrep -u 1000 -x cage >/dev/null && pgrep -u 1000 -x niri >/dev/null", timeout=20)
    if rc != 0:
        ctx.log("cambiando greetd a la sesión anidada (cage + niri)")
        script = r'''
set -e
H=$(cat /run/qa/host)
curl -sf "$H/f/nested-niri.sh" -o /usr/local/bin/qa-nested-niri
chmod 755 /usr/local/bin/qa-nested-niri
c=/etc/greetd/config.toml
[ -f $c.qa-orig ] || cp $c $c.qa-orig
awk 'BEGIN{s=0} /^\[/{s=($0=="[initial_session]")} s && /^command *=/{print "command = \"/usr/local/bin/qa-nested-niri\""; next} {print}' $c.qa-orig > $c
grep -A3 initial_session $c
rm -f /run/greetd.run
systemctl restart greetd
'''
        rc, out = ctx.cmd(script, timeout=60)
        ctx.log(out.strip()[-300:])
    ok, out = ctx.wait(cmd="pgrep -x cage >/dev/null && niri msg version >/dev/null && noctalia msg status",
                       user=True, timeout=float(os.environ.get("QA_NESTED_TIMEOUT", 420)), interval=4)
    if ok:
        # Niri anidado (backend winit) usa Alt como Mod.
        qalib.update_state(ctx.run_id, lambda s: s.update({"session": "nested", "mod_key": "alt"}))
        ctx.wait_status(lambda s: s.get("barVisible"), timeout=60)
    return ok, out


def legacy_check(ctx, where):
    out = ctx.procs(LEGACY)
    return (not out.strip()), out


def run(run_id, only=None):
    ctx = Ctx(run_id)
    done = qalib.done_ids(run_id, "smoke")
    rules = load_allowlist(qalib.QA_DIR)
    todo = lambda cid: cid not in done and (not only or cid in only)  # noqa: E731
    st = ctx.st

    # ---------- sesión real (greetd)
    if st.get("session") != "nested":
        if todo("01-boot"):
            t0 = time.time()
            rc, out = ctx.cmd("systemctl is-system-running; systemd-analyze 2>/dev/null | head -1; uname -r", timeout=60)
            state = out.splitlines()[0].strip() if out else "?"
            status = "PASS" if state in ("running", "degraded") else "FAIL"
            R(ctx, "01-boot", status, f"login en serie alcanzado; system={state}; " + " | ".join(out.splitlines()[1:3]), t0=t0)
        if todo("02-failed-units"):
            rc, out = ctx.cmd("systemctl --failed --no-legend --plain", timeout=60)
            lines = [l for l in out.splitlines() if l.strip()]
            bad = filter_allowed(lines, rules["unit"])
            R(ctx, "02-failed-units", "PASS" if not bad else "FAIL",
              "ninguna" if not lines else ("; ".join(bad) or "solo permitidas: " + "; ".join(lines)))
        if todo("03-greetd"):
            ok, out = ctx.wait(cmd="systemctl is-active greetd && loginctl list-sessions --no-legend | grep -E '\\b(churros|1000)\\b' "
                                   "&& pgrep -u 1000 -a -x niri", timeout=240, interval=4)
            rc, cfg = ctx.cmd("sed -n '/initial_session/,/^$/p' /etc/greetd/config.toml", timeout=20)
            R(ctx, "03-greetd", "PASS" if ok else "FAIL", (out.replace("\n", " | ")[:300] + " || " + cfg.replace("\n", " ")[:200]))
        if todo("04-niri-socket"):
            ok, out = ctx.wait(cmd='[ -S "$NIRI_SOCKET" ] && echo "NIRI_SOCKET=$NIRI_SOCKET" && niri msg version', user=True,
                               timeout=120, interval=3)
            R(ctx, "04-niri-socket", "PASS" if ok else "FAIL", out.replace("\n", " | ")[:300])
        if todo("05-noctalia"):
            ok, out = ctx.wait(cmd="pgrep -a -x noctalia && noctalia msg status", user=True, timeout=180, interval=4)
            rc, ver = ctx.cmd("pacman -Q noctalia 2>/dev/null", timeout=20)
            R(ctx, "05-noctalia", "PASS" if ok else "FAIL", (ver.strip() + " | " + out.replace("\n", " | "))[:300])
        if todo("11-fc-inter"):
            rc, out = ctx.ucmd("fc-match Inter; fc-match 'Inter:weight=600'", timeout=30)
            first = out.splitlines()[0] if out else ""
            ok = rc == 0 and re.search(r'"Inter"', first) is not None
            R(ctx, "11-fc-inter", "PASS" if ok else "FAIL", out.strip().replace("\n", " | "))
        if todo("06-no-legacy"):
            ok, out = legacy_check(ctx, "real")
            qalib.update_state(run_id, lambda s: s.__setitem__("legacy_real", out or "ninguno"))
            if not ok:
                R(ctx, "06-no-legacy", "FAIL", "sesión real: " + out.replace("\n", "; "))
        # Evidencia de la sesión real antes de cambiarla (si no hay 3D)
        ctx.fetch("/etc/greetd/config.toml", "greetd-config.toml")

    # ---------- UI: sesión real si hay 3D; si no, Niri anidado en cage
    st = ctx.st
    if st.get("has_3d"):
        qalib.update_state(run_id, lambda s: s.update({"session": "native", "mod_key": "meta_l"}))
        ctx.log("3D disponible: puntos de UI en la sesión real de greetd (sin cage)")
        base = ctx.shot("smoke-00-desktop")
        if todo("06-no-legacy"):
            real = ctx.st.get("legacy_real", "ninguno")
            R(ctx, "06-no-legacy", "PASS" if real == "ninguno" else "FAIL",
              f"sesión real (3D): {real}", [base])
    else:
        t0 = time.time()
        ok, out = ensure_nested(ctx)
        if not ok:
            for cid in ("07-mod-space", "08-mod-c", "09-lock", "10-notification"):
                if todo(cid):
                    R(ctx, cid, "FAIL", "no arrancó la sesión anidada (cage+niri+noctalia): " + out[-200:])
            if todo("06-no-legacy"):
                real = ctx.st.get("legacy_real", "ninguno")
                R(ctx, "06-no-legacy", "FAIL", f"sesión real: {real}; no hubo sesión anidada")
            return
        ctx.log(f"sin 3D: sesión anidada (cage) lista en {time.time() - t0:.0f}s")
        base = ctx.shot("smoke-00-desktop")
        if todo("06-no-legacy"):
            ok6, out6 = legacy_check(ctx, "nested")
            real = ctx.st.get("legacy_real", "ninguno")
            status = "PASS" if ok6 and real == "ninguno" else "FAIL"
            R(ctx, "06-no-legacy", status, f"sesión real: {real}; anidada: {out6 or 'ninguno'}", [base])

    mod_order = ("meta_l", "alt") if ctx.st.get("has_3d") else ("alt", "meta_l")
    for cid, combo, panel in (("07-mod-space", "mod+spc", "launcher"), ("08-mod-c", "mod+c", "control-center")):
        if not todo(cid):
            continue
        t0 = time.time()
        ctx.close_panels()
        used = None
        for mod in mod_order:
            qalib.update_state(run_id, lambda s, mod=mod: s.__setitem__("mod_key", mod))
            ctx.key(combo)
            ok, s = ctx.wait_status(lambda s: s.get("panelOpen") and s.get("activePanelId") == panel, timeout=20)
            if ok:
                used = mod
                break
        fallback = "meta_l" if ctx.st.get("has_3d") else "alt"
        qalib.update_state(run_id, lambda s, fallback=fallback, used=used: s.__setitem__("mod_key", used or fallback))
        shot = ctx.shot(f"smoke-{cid}")
        detail = f"Mod={used}; status={s}" if used else f"el panel {panel} no se abrió; status={s}"
        R(ctx, cid, "PASS" if used else "FAIL", detail, [shot], t0)
        ctx.close_panels()

    if todo("09-lock"):
        t0 = time.time()
        ctx.close_panels()
        ctx.ucmd("noctalia msg session lock", timeout=30)
        ok, s = ctx.wait_status(lambda s: s.get("locked") is True, timeout=90)
        shot = ctx.shot("smoke-09-lock", settle=15)
        # Desbloqueo: allow_empty_password -> Enter; si no, logind
        ctx.key("ret")
        unl, s2 = ctx.wait_status(lambda s: s.get("locked") is False, timeout=40)
        how = "Enter"
        if not unl:
            ctx.cmd("loginctl unlock-sessions", timeout=20)
            unl, s2 = ctx.wait_status(lambda s: s.get("locked") is False, timeout=40)
            how = "loginctl unlock-sessions (Enter no desbloqueó)"
        detail = f"locked={s.get('locked')}; desbloqueo con {how}: {'ok' if unl else 'NO'}; revisar la captura"
        status = "FAIL" if not ok or not unl else ("PASS" if how == "Enter" else "WARN")
        R(ctx, "09-lock", status, detail, [shot], t0)

    if todo("10-notification"):
        t0 = time.time()
        rc, out = ctx.ucmd("notify-send -a churros-verify 'churros-verify' 'Notificación de prueba del smoke' && "
                           "gdbus call --session --dest org.freedesktop.Notifications --object-path /org/freedesktop/Notifications "
                           "--method org.freedesktop.Notifications.GetServerInformation; "
                           "busctl --user status org.freedesktop.Notifications 2>/dev/null | grep -E '^(PID|Comm)='", timeout=40)
        time.sleep(1)
        shot = ctx.shot("smoke-10-notification")
        ok = rc == 0 and "noctalia" in out.lower()
        R(ctx, "10-notification", "PASS" if ok else "FAIL", out.strip().replace("\n", " | ")[:300], [shot], t0)


def journal(run_id):
    """Punto 12: al final, para que incluya todo lo que pasó en la corrida."""
    ctx = Ctx(run_id)
    if "12-journal" in qalib.done_ids(run_id, "smoke"):
        return
    rules = load_allowlist(qalib.QA_DIR)
    rc, out = ctx.cmd("journalctl -b -p err --no-pager -o short-monotonic -q; echo '--- coredumps'; "
                      "coredumpctl list --no-legend 2>/dev/null || true", timeout=90)
    jr, _, cores = out.partition("--- coredumps")
    jlines = [l for l in jr.splitlines() if l.strip()]
    bad = filter_allowed(jlines, rules[""])
    cores = [l for l in cores.splitlines() if l.strip() and "No coredumps" not in l]
    rc2, nlog = ctx.ucmd("grep -hE '\\[(ERR|CRT|FTL)\\]' ~/.cache/noctalia/noctalia.log 2>/dev/null | cut -c25- | sort | uniq -c | sort -rn | head -40",
                         timeout=40)
    nbad = filter_allowed(nlog.splitlines(), rules["noctalia"])
    with open(os.path.join(ctx.dir, "evidence", "journal-errors.txt"), "w") as f:
        f.write(out + "\n--- noctalia ERR\n" + nlog)
    ctx.fetch("/home/$(id -nu 1000)/.cache/noctalia/noctalia.log", "noctalia.log")
    ctx.fetch("/tmp/niri-nested.log", "niri-nested.log")
    ctx.cmd("journalctl -b --no-pager -o short-monotonic > /tmp/journal.txt", timeout=90)
    ctx.fetch("/tmp/journal.txt", "journal.txt")
    status = "PASS" if not bad and not cores and not nbad else "FAIL"
    detail = (f"{len(jlines)} errores, {len(jlines) - len(bad)} en allowlist; coredumps={len(cores)}; "
              f"noctalia ERR fuera de allowlist={len(nbad)}")
    if bad:
        detail += " | " + " | ".join(l.strip()[:160] for l in bad[:6])
    if cores:
        detail += " | core: " + " | ".join(cores[:3])
    if nbad:
        detail += " | noctalia: " + " | ".join(l.strip()[:160] for l in nbad[:4])
    R(ctx, "12-journal", status, detail, [os.path.join(ctx.dir, "evidence", "journal-errors.txt")])
