"""Biblioteca común de churros-verify: rutas, state.json, QMP, consola serie,
agente del invitado y resultados. Solo usa la stdlib de Python 3."""
import fcntl, json, os, re, socket, subprocess, time, uuid, contextlib, signal

QA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.abspath(os.path.join(QA_DIR, "..", ".."))
RUNS = os.environ.get("QA_RUNS_DIR", os.path.join(QA_DIR, "runs"))
CACHE = os.environ.get("QA_CACHE", os.path.expanduser("~/.cache/churros-verify"))

STAGES = ["preflight", "diffmap", "build", "boot", "session", "smoke", "deep", "report"]


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def run_dir(run_id):
    return os.path.join(RUNS, run_id)


def resolve_run(run_id=None):
    run_id = run_id or os.environ.get("QA_RUN")
    if not run_id:
        latest = os.path.join(RUNS, "latest")
        if os.path.islink(latest):
            run_id = os.path.basename(os.readlink(latest))
    if not run_id or not os.path.isdir(run_dir(run_id)):
        raise SystemExit(f"churros-verify: RUN_ID desconocido ({run_id}); usa --run o QA_RUN")
    return run_id


# ---------------------------------------------------------------- state.json
@contextlib.contextmanager
def _locked(path):
    with open(path + ".lock", "a+") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        yield


def load_state(run_id):
    p = os.path.join(run_dir(run_id), "state.json")
    with open(p) as f:
        return json.load(f)


def save_state(run_id, st):
    p = os.path.join(run_dir(run_id), "state.json")
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f, indent=2, ensure_ascii=False)
    os.replace(tmp, p)


def update_state(run_id, fn):
    p = os.path.join(run_dir(run_id), "state.json")
    with _locked(p):
        st = load_state(run_id)
        fn(st)
        save_state(run_id, st)
        return st


def set_stage(run_id, stage, status, **info):
    def f(st):
        s = st["stages"].setdefault(stage, {})
        s["status"] = status
        if status == "running":
            s["started"] = now(); s.pop("ended", None)
        elif status in ("done", "failed", "skipped"):
            s["ended"] = now()
        s.update(info)
    return update_state(run_id, f)


def warn(run_id, msg):
    def f(st):
        if msg not in st["warnings"]:
            st["warnings"].append(msg)
    update_state(run_id, f)
    log(run_id, "AVISO: " + msg)


def log(run_id, msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(os.path.join(run_dir(run_id), "progress.log"), "a") as f:
        f.write(line + "\n")


# ------------------------------------------------------------- results.jsonl
def add_result(run_id, phase, cid, title, status, detail="", evidence=None, duration=None):
    row = {"ts": now(), "run_id": run_id, "phase": phase, "id": cid, "title": title,
           "status": status, "detail": detail, "evidence": evidence or []}
    if duration is not None:
        row["duration_s"] = round(duration, 1)
    with open(os.path.join(run_dir(run_id), "results.jsonl"), "a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    log(run_id, f"{phase}/{cid}: {status} {detail[:160]}")
    return row


def load_results(run_id):
    p = os.path.join(run_dir(run_id), "results.jsonl")
    rows = []
    if os.path.exists(p):
        for line in open(p):
            if line.strip():
                rows.append(json.loads(line))
    last = {}
    for r in rows:  # al reanudar, la última fila de cada (phase, id) manda
        last[(r["phase"], r["id"])] = r
    return list(last.values())


def done_ids(run_id, phase):
    """Puntos ya resueltos (para reanudar). Una fila REDO los vuelve a abrir."""
    return {r["id"] for r in load_results(run_id) if r["phase"] == phase and r["status"] != "REDO"}


# --------------------------------------------------------------------- QMP
class QMP:
    def __init__(self, run_id):
        self.path = os.path.join(run_dir(run_id), "vm", "qmp.sock")
        self.s = socket.socket(socket.AF_UNIX)
        self.s.settimeout(30)
        self.s.connect(self.path)
        self.f = self.s.makefile("rb")
        self.f.readline()
        self.cmd({"execute": "qmp_capabilities"})

    def cmd(self, c):
        self.s.sendall((json.dumps(c) + "\n").encode())
        while True:
            r = json.loads(self.f.readline())
            if "event" in r:
                continue
            return r

    def close(self):
        with contextlib.suppress(Exception):
            self.s.close()


def qmp_alive(run_id):
    try:
        q = QMP(run_id); r = q.cmd({"execute": "query-status"}); q.close()
        return r.get("return", {}).get("status")
    except Exception:
        return None


SHIFTED = {'!': '1', '@': '2', '#': '3', '$': '4', '%': '5', '^': '6', '&': '7', '*': '8', '(': '9',
           ')': '0', '_': 'minus', '+': 'equal', '{': 'bracket_left', '}': 'bracket_right',
           '|': 'backslash', ':': 'semicolon', '"': 'apostrophe', '~': 'grave_accent', '<': 'comma',
           '>': 'dot', '?': 'slash'}
PLAIN = {'-': 'minus', '=': 'equal', '[': 'bracket_left', ']': 'bracket_right', '\\': 'backslash',
         ';': 'semicolon', "'": 'apostrophe', '`': 'grave_accent', ',': 'comma', '.': 'dot',
         '/': 'slash', ' ': 'spc', '\n': 'ret', '\t': 'tab'}
ALIASES = {'super': 'meta_l', 'win': 'meta_l', 'meta': 'meta_l', 'ctrl': 'ctrl', 'alt': 'alt',
           'shift': 'shift', 'space': 'spc', 'enter': 'ret', 'return': 'ret', 'escape': 'esc',
           '/': 'slash'}


def combo_keys(combo, mod="meta_l"):
    out = []
    for k in combo.split("+"):
        k = k.strip().lower()
        if k == "mod":
            out.append(mod)
        else:
            out.append(ALIASES.get(k, k))
    return out


def send_combo(run_id, combo, hold=100):
    st = load_state(run_id)
    mod = st.get("mod_key", "meta_l")
    q = QMP(run_id)
    r = q.cmd({"execute": "send-key", "arguments": {
        "keys": [{"type": "qcode", "data": k} for k in combo_keys(combo, mod)], "hold-time": hold}})
    q.close()
    if "error" in r:
        raise RuntimeError(f"send-key {combo}: {r['error']}")


def type_text(run_id, text):
    q = QMP(run_id)
    for ch in text:
        if ch.isalpha():
            keys = ["shift", ch.lower()] if ch.isupper() else [ch]
        elif ch.isdigit():
            keys = [ch]
        elif ch in SHIFTED:
            keys = ["shift", SHIFTED[ch]]
        else:
            keys = [PLAIN[ch]]
        q.cmd({"execute": "send-key", "arguments": {
            "keys": [{"type": "qcode", "data": k} for k in keys], "hold-time": 30}})
        time.sleep(0.05)
    q.close()


def qmp_shot(run_id, name, device=None, settle=0.0):
    """screendump por QMP. Con settle>0 repite cada 0,7 s hasta que dos cuadros
    seguidos son iguales (la UI terminó de pintar) o vence `settle` segundos."""
    import hashlib
    d = os.path.join(run_dir(run_id), "shots"); os.makedirs(d, exist_ok=True)
    ppm = os.path.join(d, name + ".ppm"); png = os.path.join(d, name + ".png")
    args = {"filename": ppm}
    if device:
        args["device"] = device
    end, prev = time.time() + settle, None
    while True:
        q = QMP(run_id); r = q.cmd({"execute": "screendump", "arguments": args}); q.close()
        if "error" in r:
            raise RuntimeError(f"screendump: {r['error']}")
        h = hashlib.md5(open(ppm, "rb").read()).hexdigest()
        if settle <= 0 or h == prev or time.time() >= end:
            break
        prev = h
        time.sleep(0.7)
    subprocess.run(["convert", ppm, png], check=True)
    os.remove(ppm)
    return png


def image_is_blank(png):
    """True si la captura es casi de un solo color (pantalla negra o sin pintar)."""
    try:
        out = subprocess.run(["convert", png, "-colorspace", "Gray", "-format", "%[fx:standard_deviation]", "info:"],
                             capture_output=True, text=True, check=True).stdout
        return float(out) < 0.01
    except Exception:
        return False


# --------------------------------------------------------------- serie
def serial_log(run_id):
    return os.path.join(run_dir(run_id), "vm", "serial.log")


def serial_size(run_id):
    p = serial_log(run_id)
    return os.path.getsize(p) if os.path.exists(p) else 0


def serial_tail(run_id, offset=0):
    p = serial_log(run_id)
    if not os.path.exists(p):
        return ""
    with open(p, "rb") as f:
        f.seek(offset)
        return f.read().decode("utf-8", "replace")


def serial_send(run_id, text):
    p = os.path.join(run_dir(run_id), "vm", "serial.sock")
    s = socket.socket(socket.AF_UNIX); s.settimeout(10); s.connect(p)
    s.sendall(text.encode())
    time.sleep(0.3)
    s.close()


# ------------------------------------------------------------- agente
def agent_dir(run_id):
    return os.path.join(run_dir(run_id), "agent")


def agent_alive(run_id, max_age=8):
    hb = os.path.join(agent_dir(run_id), "heartbeat")
    return os.path.exists(hb) and time.time() - os.path.getmtime(hb) < max_age


def guest_cmd(run_id, script, user=False, timeout=120):
    """Ejecuta `script` en el invitado (root, o el usuario live con user=True y
    el entorno Wayland/Niri resuelto). Devuelve (rc, salida). rc=124 si vence."""
    ad = agent_dir(run_id); os.makedirs(os.path.join(ad, "results"), exist_ok=True)
    jid = time.strftime("%H%M%S") + "-" + uuid.uuid4().hex[:6]
    body = script
    if user:
        body = ("u=$(id -nu 1000); exec runuser -u \"$u\" -- bash -c "
                + shq(". /run/qa/env.sh; " + script))
    job = f"# {jid}\n# timeout {timeout}\n{body}\n"
    with _locked(os.path.join(ad, "job")):
        tmp = os.path.join(ad, "job.tmp")
        open(tmp, "w").write(job)
        os.replace(tmp, os.path.join(ad, "job"))
        with open(os.path.join(ad, "jobs.log"), "a") as f:
            f.write(f"### {jid} user={user}\n{script}\n")
        res = os.path.join(ad, "results", jid)
        deadline = time.time() + timeout + 30
        while time.time() < deadline:
            if os.path.exists(res + ".rc"):
                rc = int(open(res + ".rc").read().strip() or 1)
                out = open(res + ".out", errors="replace").read() if os.path.exists(res + ".out") else ""
                with open(os.path.join(ad, "jobs.log"), "a") as f:
                    f.write(f"--- rc={rc}\n{out}\n")
                return rc, out
            time.sleep(0.3)
    return 124, f"(sin respuesta del agente en {timeout + 30}s)"


def shq(s):
    return "'" + s.replace("'", "'\"'\"'") + "'"


# --------------------------------------------------------------- wait
def wait_until(run_id, serial=None, cmd=None, user=False, timeout=120, interval=2.0, since=None):
    """Espera hasta que aparezca `serial` (regex) en la consola serie desde `since`,
    o hasta que `cmd` devuelva rc=0 en el invitado. Sin condición, espera `timeout`.
    Devuelve (ok, detalle)."""
    start = time.time()
    off = serial_size(run_id) if since is None else since
    rx = re.compile(serial, re.M) if serial else None
    last = ""
    while True:
        if rx:
            txt = serial_tail(run_id, off)
            m = rx.search(txt)
            if m:
                return True, m.group(0)
        if cmd:
            rc, last = guest_cmd(run_id, cmd, user=user, timeout=min(60, max(10, int(timeout))))
            if rc == 0:
                return True, last.strip()
        if time.time() - start >= timeout:
            return (not rx and not cmd), last.strip()[-400:]
        time.sleep(interval)


def pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def kill_pid(pid, sig=signal.SIGTERM):
    with contextlib.suppress(Exception):
        os.kill(int(pid), sig)
