#!/usr/bin/env python3
"""Servidor HTTP por corrida (lo usa el agente del invitado vía 10.0.2.2).
  GET  /job            trabajo pendiente (204 si ya tiene resultado)
  GET  /f/<nombre>     archivos de scripts/qa/guest (agent.sh, env.sh...)
  PUT  /result/<id>?rc=N  salida de un trabajo
  PUT  /up/<nombre>    evidencia (capturas, logs) -> runs/<RUN_ID>/evidence
uso: srv.py RUN_DIR GUEST_DIR PORT"""
import http.server, os, sys, time, urllib.parse

RUN, GUEST, PORT = sys.argv[1], sys.argv[2], int(sys.argv[3])
AG = os.path.join(RUN, "agent"); EV = os.path.join(RUN, "evidence")
os.makedirs(os.path.join(AG, "results"), exist_ok=True); os.makedirs(EV, exist_ok=True)


def safe(name):
    return os.path.basename(urllib.parse.unquote(name)).replace("..", "_") or "upload.bin"


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, data=b"", ctype="text/plain"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if data:
            self.wfile.write(data)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/job":
            open(os.path.join(AG, "heartbeat"), "w").write(str(time.time()))
            p = os.path.join(AG, "job")
            if not os.path.exists(p):
                return self._send(204)
            data = open(p, "rb").read()
            jid = data.split(b"\n", 1)[0][2:].decode().strip()
            if os.path.exists(os.path.join(AG, "results", jid + ".rc")):
                return self._send(204)
            return self._send(200, data)
        if u.path.startswith("/f/"):
            p = os.path.join(GUEST, safe(u.path[3:]))
            if os.path.isfile(p):
                return self._send(200, open(p, "rb").read())
        return self._send(404, b"not found\n")

    def do_PUT(self):
        u = urllib.parse.urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        data = self.rfile.read(n)
        if u.path.startswith("/result/"):
            jid = safe(u.path[8:]); rc = urllib.parse.parse_qs(u.query).get("rc", ["1"])[0]
            base = os.path.join(AG, "results", jid)
            open(base + ".out", "wb").write(data)
            open(base + ".rc", "w").write(rc)  # .rc al final: marca de completado
            return self._send(201, b"ok\n")
        if u.path.startswith("/up/"):
            open(os.path.join(EV, safe(u.path[4:])), "wb").write(data)
            return self._send(201, b"ok\n")
        return self._send(404, b"not found\n")


http.server.ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
