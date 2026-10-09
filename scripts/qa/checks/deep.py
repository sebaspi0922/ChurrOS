"""Pruebas profundas que elige qa-diffmap. Cada check recibe (ctx, feature, diff)
y devuelve (status, detalle, [evidencias]). Estados: PASS, FAIL, WARN, SKIP,
MANUAL (solo evidencia visual, no cambia el veredicto)."""
import json, os, re, subprocess, time
import qalib

CHECKS = {}


def check(cid, title):
    def deco(fn):
        CHECKS[cid] = (title, fn)
        return fn
    return deco


USER_CFG = "~/.config"


def procrx(prog):
    """Regex para pgrep/pkill -f: el comm del kernel se corta a 15 caracteres
    (churros-settings -> churros-setting), así que -x no sirve."""
    return f"'(^|/){re.escape(prog)}( |$)'"
DEFAULTS = "/usr/share/churros/defaults"


# ------------------------------------------------------------------ Niri
@check("niri-config-valid", "niri validate de la config del usuario y la de defaults")
def niri_config_valid(ctx, feat, diff):
    rc, out = ctx.ucmd(f"niri validate -c {USER_CFG}/niri/config.kdl 2>&1; a=$?; "
                       f"niri validate -c {DEFAULTS}/niri/config.kdl 2>&1; b=$?; echo rc=$a,$b; [ $a = 0 ] && [ $b = 0 ]",
                       timeout=60)
    return ("PASS" if rc == 0 else "FAIL"), out.strip().replace("\n", " | ")[-300:], []


@check("niri-autostart-clean", "spawn-at-startup sin swaybg/waybar/mako")
def niri_autostart(ctx, feat, diff):
    rc, out = ctx.ucmd(f"grep -hE '^\\s*spawn(-sh)?-at-startup' {USER_CFG}/niri/config.kdl", timeout=30)
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    bad = [l for l in lines if re.search(r"\b(swaybg|waybar|mako)\b", l)]
    return ("FAIL" if bad else "PASS"), ("legado: " + "; ".join(bad) if bad else f"{len(lines)} entradas: " + "; ".join(lines))[:400], []


def _binds(ctx):
    rc, out = ctx.ucmd(f"cat {USER_CFG}/niri/config.kdl", timeout=30)
    binds = {}
    for m in re.finditer(r"^\s*((?:Mod|Super|Alt|Ctrl|Shift|\+)+[\w+]*)\s[^{]*\{\s*([^}]*)\}", out, re.M):
        binds[m.group(1)] = m.group(2).strip()
    return binds


@check("niri-spawn-binds", "Atajos spawn del diff: cada uno lanza su programa")
def niri_spawn_binds(ctx, feat, diff):
    """Para los atajos `spawn "prog"` que añade el diff, pulsa el atajo y espera
    a que el proceso aparezca. Los `noctalia msg panel-toggle X` se miran por
    `noctalia msg status`."""
    added = [l[1:] for l in diff.get("patch", "").splitlines() if l.startswith("+") and not l.startswith("+++")]
    combos = []
    for l in added:
        m = re.match(r"\s*((?:Mod|Super|Alt|Ctrl|Shift)(?:\+\w+)+)\s.*\{\s*(spawn(?:-sh)?)\s+\"([^\"]+)\"", l)
        if m and m.group(1) not in [c[0] for c in combos]:
            combos.append((m.group(1), m.group(2), m.group(3)))
    if not combos:
        return "SKIP", "el diff no añade atajos spawn", []
    res, shots, bad = [], [], 0
    for combo, kind, target in combos:
        key = combo.replace("Mod", "mod").replace("Shift", "shift").replace("Ctrl", "ctrl").replace("Alt", "alt").lower()
        key = key.replace("space", "spc").replace("slash", "slash")
        ctx.close_panels()
        pm = re.match(r"noctalia msg panel-toggle ([\w-]+)", target)
        if pm:
            ctx.key(key)
            ok, s = ctx.wait_status(lambda s: s.get("activePanelId") == pm.group(1), timeout=20)
            shots.append(ctx.shot(f"deep-bind-{key.replace('+', '_')}"))
            ctx.close_panels()
        else:
            prog = target.split()[0].split("/")[-1]
            ctx.ucmd(f"pkill -f {procrx(prog)}; true", timeout=10)
            ctx.key(key)
            ok, _ = ctx.wait(cmd=f"pgrep -f {procrx(prog)}", user=True, timeout=45)
            shots.append(ctx.shot(f"deep-bind-{key.replace('+', '_')}"))
            ctx.key("esc")
            ctx.ucmd(f"pkill -f {procrx(prog)}; true", timeout=10)
        res.append(f"{combo}→{target}: {'ok' if ok else 'NO'}")
        bad += 0 if ok else 1
    return ("PASS" if not bad else "FAIL"), "; ".join(res), shots


@check("niri-hotkey-overlay", "Overlay de atajos (Mod+Shift+/) se abre; títulos para revisión")
def niri_overlay(ctx, feat, diff):
    ctx.close_panels()
    ctx.key("mod+shift+slash")
    time.sleep(2)
    shot = ctx.shot("deep-hotkey-overlay")
    ctx.key("esc")
    rc, out = ctx.ucmd(f"grep -o 'hotkey-overlay-title=\"[^\"]*\"' {USER_CFG}/niri/config.kdl | cut -d'\"' -f2", timeout=30)
    titles = [t for t in out.splitlines() if t.strip()]
    eng = [t for t in titles if re.search(r"\b(Open|Close|Toggle|Show|Focus|Move|Switch|Take|Screenshot|Quit|Launch|Window|Column)\b", t)]
    if eng:
        return "WARN", f"títulos que parecen en inglés: {eng}", [shot]
    return "MANUAL", f"{len(titles)} títulos, ninguno en inglés por patrón; revisar la captura", [shot]


# --------------------------------------------------------------- Noctalia
@check("noctalia-config-valid", "config.toml y paletas parsean (TOML/JSON)")
def noctalia_config_valid(ctx, feat, diff):
    script = r'''python3 - <<'PY'
import glob, json, os, sys
import tomllib
bad = []
for base in (os.path.expanduser("~/.config/noctalia"), "/usr/share/churros/defaults/noctalia"):
    for p in glob.glob(base + "/*.toml"):
        try:
            tomllib.load(open(p, "rb"))
        except Exception as e:
            bad.append(f"{p}: {e}")
    for p in glob.glob(base + "/palettes/*.json"):
        try:
            d = json.load(open(p))
            keys = sorted(d) if isinstance(d, dict) else []
            print(p, "claves:", ",".join(keys)[:120])
        except Exception as e:
            bad.append(f"{p}: {e}")
print("ERRORES:", bad)
sys.exit(1 if bad else 0)
PY'''
    rc, out = ctx.ucmd(script, timeout=60)
    return ("PASS" if rc == 0 else "FAIL"), out.strip().replace("\n", " | ")[-400:], []


@check("noctalia-theme-light-dark", "Claro/oscuro: launcher y CC repintan; color-scheme sigue el modo")
def noctalia_theme(ctx, feat, diff):
    shots, notes, bad = [], [], 0
    rc, orig = ctx.ucmd("gsettings get org.gnome.desktop.interface color-scheme", timeout=20)
    orig_mode = "light" if "light" in orig else "dark"
    for mode in ("light", "dark"):
        ctx.close_panels()
        rc, _ = ctx.ucmd(f"noctalia msg theme-mode-set {mode}", timeout=30)
        ok, out = ctx.wait(cmd=f"gsettings get org.gnome.desktop.interface color-scheme | grep -q {mode}",
                           user=True, timeout=20, interval=1)
        if not ok:
            bad += 1
        notes.append(f"{mode}: rc={rc} color-scheme {'ok' if ok else 'NO sigue'}")
        time.sleep(2)
        shots.append(ctx.shot(f"deep-theme-{mode}-desktop"))
        for panel in ("launcher", "control-center"):
            ctx.ucmd(f"noctalia msg panel-open {panel}", timeout=20)
            okp, s = ctx.wait_status(lambda s: s.get("activePanelId") == panel, timeout=20)
            time.sleep(1.5)
            shots.append(ctx.shot(f"deep-theme-{mode}-{panel}"))
            if not okp:
                bad += 1; notes.append(f"{mode}/{panel} no abrió")
            ctx.close_panels()
    ctx.ucmd(f"noctalia msg theme-mode-set {orig_mode}", timeout=30)
    return ("PASS" if not bad else "FAIL"), "; ".join(notes) + " (revisar capturas)", shots


@check("noctalia-log-errors", "noctalia.log sin [ERR] fuera de la allowlist")
def noctalia_log(ctx, feat, diff):
    from checks.common import load_allowlist, filter_allowed
    rules = load_allowlist(qalib.QA_DIR)["noctalia"]
    rc, out = ctx.ucmd("grep -hE '\\[(ERR|CRT|FTL)\\]' ~/.cache/noctalia/noctalia.log | cut -c25- | sort | uniq -c | sort -rn | head -30",
                       timeout=30)
    bad = filter_allowed(out.splitlines(), rules)
    return ("PASS" if not bad else "FAIL"), (" | ".join(l.strip() for l in bad[:6]) or "sin errores"), []


# -------------------------------------------------------------- Fondo
@check("wallpaper-apply-noctalia", "churros-apply-wallpaper cambia el fondo vía Noctalia sin lanzar swaybg")
def wallpaper(ctx, feat, diff):
    rc, cur = ctx.ucmd("noctalia msg wallpaper-get", timeout=20)
    cur = cur.strip().splitlines()[-1] if cur.strip() else ""
    rc, lst = ctx.cmd("ls /usr/share/churros/wallpapers/*.png", timeout=20)
    cands = [p for p in lst.split() if p != cur and "default" not in p]
    if not cands:
        return "SKIP", "no hay otro fondo para probar", []
    target = next((p for p in cands if "Dark" in p), cands[0])
    rc, out = ctx.ucmd(f"churros-apply-wallpaper {target}", timeout=60)
    ok, got = ctx.wait(cmd=f"noctalia msg wallpaper-get | grep -qF {target}", user=True, timeout=30, interval=1)
    time.sleep(2)
    shot = ctx.shot("deep-wallpaper-applied")
    legacy = ctx.procs(["swaybg"])
    if cur:
        ctx.ucmd(f"churros-apply-wallpaper {cur}", timeout=60)
    status = "PASS" if ok and not legacy else "FAIL"
    return status, f"rc={rc}; wallpaper-get={'ok' if ok else 'NO'} ({target}); swaybg={'NO' if not legacy else legacy}; " \
                   f"salida: {out.strip()[-160:]}", [shot]


@check("edition-wallpaper", "Fondo en KDE/XFCE")
def edition_wallpaper(ctx, feat, diff):
    return "SKIP", "requiere la ISO de esa edición: churros-verify run SHA --edition kde|xfce", []


@check("edition-session", "Sesión de otra edición")
def edition_session(ctx, feat, diff):
    return "SKIP", "requiere la ISO de esa edición: churros-verify run SHA --edition kde|xfce", []


# ------------------------------------------------------------- Ajustes
@check("preferences-launch", "churros-settings abre en Niri, sin páginas de Waybar/Mako y sin barra extra")
def preferences(ctx, feat, diff):
    ctx.close_panels()
    ctx.ucmd(f"pkill -f {procrx('churros-settings')}; true", timeout=10)
    ctx.ucmd("setsid -f churros-settings > /tmp/churros-settings.log 2>&1 < /dev/null", timeout=20)
    ok, out = ctx.wait(cmd="niri msg windows | grep -iE 'app id: \"?[a-z.]*(churros|preferences|settings)'", user=True,
                       timeout=60, interval=2)
    time.sleep(3)
    shot = ctx.shot("deep-preferences")
    rc, alive = ctx.ucmd(f"pgrep -a -f {procrx('churros-settings')}; tail -5 /tmp/churros-settings.log", timeout=20)
    legacy = ctx.procs(["waybar", "mako", "swaybg"])
    ctx.ucmd(f"pkill -f {procrx('churros-settings')}; true", timeout=10)
    status = "PASS" if ok and "churros-settings" in alive and not legacy else "FAIL"
    return status, (f"ventana={'sí' if ok else 'no'}; procesos legado={legacy or 'ninguno'}; "
                    f"{alive.strip().replace(chr(10), ' | ')[-200:]}"), [shot]


@check("host-check", "./churros check en el árbol del SHA (host)")
def host_check(ctx, feat, diff):
    r = [x for x in qalib.load_results(ctx.run_id) if x["phase"] == "build" and x["id"] == "check"]
    if not r:
        return "SKIP", "no se corrió ./churros check", []
    return r[0]["status"], "ver build/check: " + r[0]["detail"], r[0]["evidence"]


# ------------------------------------------------------------ Paquetes
@check("packages-installed", "Paquetes añadidos/quitados en el diff están (o no) en la ISO")
def packages(ctx, feat, diff):
    arch = ctx.st.get("arch", "x86_64")
    plist = f"archiso/packages.{arch}" if ctx.st.get("edition", "niri") == "niri" else f"archiso/packages.{ctx.st['edition']}.{arch}"
    p = subprocess.run(["git", "-C", qalib.REPO, "diff", f"{diff['base']}...{diff['sha']}", "--", plist],
                       capture_output=True, text=True).stdout
    add = [l[1:].strip() for l in p.splitlines() if l.startswith("+") and not l.startswith("+++") and l[1:].strip() and not l[1:].startswith("#")]
    rem = [l[1:].strip() for l in p.splitlines() if l.startswith("-") and not l.startswith("---") and l[1:].strip() and not l[1:].startswith("#")]
    if not add and not rem:
        return "SKIP", f"{plist} sin cambios", []
    notes, bad = [], 0
    if add:
        rc, out = ctx.cmd("pacman -Q " + " ".join(add) + " 2>&1 | grep -v ^warning:; exit ${PIPESTATUS[0]}", timeout=30)
        bad += 0 if rc == 0 else 1
        notes.append("añadidos: " + out.strip().replace("\n", ", "))
    for pkg in rem:
        rc, _ = ctx.cmd(f"pacman -Q {pkg} 2>/dev/null", timeout=20)
        if rc == 0:
            bad += 1; notes.append(f"{pkg} sigue instalado")
    return ("PASS" if not bad else "FAIL"), "; ".join(notes)[:400], []


@check("greetd-config", "greetd: config válida y autologin")
def greetd_cfg(ctx, feat, diff):
    r = [x for x in qalib.load_results(ctx.run_id) if x["id"] == "03-greetd"]
    return (r[0]["status"] if r else "SKIP"), "ver smoke 03-greetd", []


def run(run_id, diffmap):
    from checks.common import Ctx
    ctx = Ctx(run_id)
    done = qalib.done_ids(run_id, "deep")
    edition = ctx.st.get("edition", "niri")
    patch = subprocess.run(["git", "-C", qalib.REPO, "diff", f"{diffmap['base']}...{diffmap['sha']}"],
                           capture_output=True, text=True).stdout
    diff = dict(diffmap, patch=patch)
    seen = set()
    for feat in diffmap["features"]:
        for cid in feat["checks"]:
            rid = cid
            if rid in seen or rid in done:
                seen.add(rid); continue
            seen.add(rid)
            title, fn = CHECKS.get(cid, (cid, None))
            t0 = time.time()
            if fn is None:
                qalib.add_result(run_id, "deep", rid, title, "FAIL", f"check desconocido en features.yaml ({feat['id']})")
                continue
            if not feat["applies"]:
                qalib.add_result(run_id, "deep", rid, title, "SKIP",
                                 f"[{feat['id']}] solo aplica a {','.join(feat['editions'])}; corre esa edición aparte")
                continue
            try:
                status, detail, ev = fn(ctx, feat, diff)
            except Exception as e:  # noqa: BLE001
                status, detail, ev = "FAIL", f"excepción: {e!r}", []
            qalib.add_result(run_id, "deep", rid, title, status, f"[{feat['id']}] {detail}",
                             [ctx.rel(e) if e and os.path.isabs(e) else e for e in ev if e], time.time() - t0)
