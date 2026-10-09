"""Contexto que reciben las pruebas: comandos en el invitado, teclas, capturas,
esperas y estado de Noctalia/Niri."""
import json, os, re, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
import qalib  # noqa: E402


class Ctx:
    def __init__(self, run_id):
        self.run_id = run_id
        self.dir = qalib.run_dir(run_id)

    @property
    def st(self):
        return qalib.load_state(self.run_id)

    def log(self, msg):
        qalib.log(self.run_id, msg)

    def cmd(self, script, user=False, timeout=120):
        return qalib.guest_cmd(self.run_id, script, user=user, timeout=timeout)

    def ucmd(self, script, timeout=120):
        return self.cmd(script, user=True, timeout=timeout)

    def key(self, combo):
        qalib.send_combo(self.run_id, combo)

    def wait(self, serial=None, cmd=None, user=False, timeout=60, interval=1.5):
        return qalib.wait_until(self.run_id, serial=serial, cmd=cmd, user=user,
                                timeout=timeout, interval=interval)

    def shot(self, name, prefer=None, settle=None):
        """Captura: QMP screendump (pantalla de la VM); si sale en blanco prueba
        el otro dispositivo y por último grim dentro de la sesión."""
        st = self.st
        order = []
        pref = prefer or st.get("shot_source")
        for src in ([pref] if pref else []) + [None, "vgpu", "grim"]:
            if src not in order:
                order.append(src)
        last = None
        for src in order:
            try:
                if src == "grim":
                    rc, _ = self.ucmd(f"grim /tmp/{name}.png && curl -sf -T /tmp/{name}.png $(cat /run/qa/host)/up/{name}.png",
                                      timeout=60)
                    p = os.path.join(self.dir, "evidence", name + ".png")
                    if rc == 0 and os.path.exists(p):
                        qalib.update_state(self.run_id, lambda s: s.__setitem__("shot_source", "grim"))
                        return p
                    continue
                p = last = qalib.qmp_shot(self.run_id, name, device=src,
                                          settle=float(os.environ.get("QA_SHOT_SETTLE", 8)) if settle is None else settle)
                if not qalib.image_is_blank(p):
                    if src != st.get("shot_source"):
                        qalib.update_state(self.run_id, lambda s: s.__setitem__("shot_source", src))
                    return p
            except Exception as e:  # noqa: BLE001
                self.log(f"captura {name} con {src or 'qmp'} falló: {e}")
        return last

    def rel(self, path):
        return os.path.relpath(path, self.dir) if path else None

    # ---- Noctalia / Niri
    def noctalia_status(self):
        # Con TCG Noctalia a veces no contesta a tiempo ("read() failed: Resource
        # temporarily unavailable"): se reintenta dentro del mismo trabajo.
        rc, out = self.ucmd("for i in 1 2 3 4 5; do noctalia msg status && exit 0; sleep 1; done; exit 1", timeout=40)
        m = re.search(r"\{.*\}", out, re.S)
        if rc == 0 and m:
            try:
                return json.loads(m.group(0))
            except ValueError:
                pass
        return {}

    def wait_status(self, pred, timeout=25):
        end = time.time() + timeout
        s = {}
        while time.time() < end:
            s = self.noctalia_status()
            if s and pred(s):
                return True, s
            time.sleep(1)
        return False, s

    def close_panels(self):
        self.ucmd("noctalia msg panel-close >/dev/null 2>&1; true", timeout=20)
        self.wait_status(lambda s: not s.get("panelOpen"), timeout=10)

    def procs(self, names):
        rc, out = self.cmd("for p in " + " ".join(names) + "; do pgrep -a -x $p || true; done", timeout=30)
        return out.strip()

    def fetch(self, guest_path, name, user=False):
        rc, _ = self.cmd(f"curl -sf -T {guest_path} $(cat /run/qa/host)/up/{name}", user=user, timeout=60)
        p = os.path.join(self.dir, "evidence", name)
        return p if rc == 0 and os.path.exists(p) else None


def load_allowlist(qa_dir):
    rules = {"": [], "unit": [], "noctalia": []}
    p = os.path.join(qa_dir, "allowlist.txt")
    if os.path.exists(p):
        for line in open(p):
            line = line.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            pre = ""
            for k in ("unit:", "noctalia:"):
                if line.startswith(k):
                    pre, line = k[:-1], line[len(k):]
            rules[pre].append(re.compile(line))
    return rules


def filter_allowed(lines, rules):
    return [l for l in lines if l.strip() and not any(r.search(l) for r in rules)]
