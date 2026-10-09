# churros-verify

QA de punta a punta de un SHA de ChurrOS: build de la ISO (con caché por SHA),
VM QEMU propia por corrida, smoke fijo de 12 puntos y pruebas profundas
elegidas por el diff (`qa-diffmap`). Deja `report.md` y `results.jsonl` con
veredicto **APROBADO / NOTAS / RECHAZADO** y la evidencia.

Solo necesita Python 3 (stdlib), QEMU + OVMF, ImageMagick (`convert`), curl y,
para compilar, lo mismo que `./churros build --container` (podman o docker).

## Uso rápido

```bash
scripts/qa/churros-verify preflight                 # KVM, QEMU, OVMF, disco
scripts/qa/churros-verify run <SHA|rama>            # vuelve enseguida; el pipeline sigue en segundo plano
scripts/qa/churros-verify status                    # etapas y último progreso (runs/latest)
scripts/qa/churros-verify resume [RUN_ID]           # tras un corte: sigue desde la primera etapa sin terminar
scripts/qa/churros-verify report [RUN_ID]           # regenera report.md e imprime el veredicto
scripts/qa/churros-verify stop [RUN_ID]             # para pipeline, VM y servidor
```

Opciones de `run`: `--edition niri|kde|xfce|server`, `--base origin/main`,
`--allow-tcg` (sin KVM; queda como aviso y el veredicto baja a NOTAS),
`--keep-vm` (no apaga la VM al final, para seguir a mano), `--rebuild`,
`--fg` (en primer plano), `--until smoke` (para tras el smoke; incluye el
journal y no corre las pruebas del diff), `--run-id`, `--wait-other-vms`
(no arranca la VM mientras haya otra QEMU en la máquina).

El SHA tiene que existir en este repo (`git fetch <remoto> <rama>` antes).

## Etapas y reanudación

`preflight → diffmap → build → boot → session → smoke → deep → report`

Cada corrida vive en `scripts/qa/runs/<RUN_ID>/` (ignorado por git):
`state.json` (etapas, pids, puerto, ISO), `progress.log`, `results.jsonl`,
`report.md`, `diffmap.json`, `vm/` (disco, EFI, `qmp.sock`, `serial.sock`,
`serial.log`), `logs/`, `shots/`, `evidence/`, `agent/jobs.log`.

`resume` vuelve a correr la etapa que quedó a medias. Dentro de smoke y deep
se saltan los puntos que ya tienen resultado, y `vm-up` reutiliza la VM si
sigue viva. `resume --from smoke` repite desde esa etapa.

## Build

- ISO en caché por SHA: `~/.cache/churros-verify/iso/ChurrOS-<sha12>-<edición>-<arch>.iso`
  (`QA_CACHE` para cambiarlo). Si existe, no se compila.
  `churros-verify cache-iso SHA ruta.iso` importa una ISO ya compilada de ese SHA.
- Si el diff es solo docs, no compila: usa la ISO de la base si está en caché, si no salta la VM.
- Compila en un worktree aparte del SHA (`$QA_CACHE/src/<sha12>`) con
  `./churros build --container --edition E --arch A` y
  `CHURROS_CONTAINER_ARGS=--network=host` (por defecto). Antes corre `./churros check`.
- Reintenta (`QA_BUILD_RETRIES`, 3) solo errores transitorios (DNS, descargas,
  sync de DB). Si la DB de paquetes está vieja (`target not found`, 404): `pacman -Sy`
  en el host si es Arch y regenera la imagen del contenedor. Otros errores fallan al momento.

## VM y helpers

`vm-up RUN_ID` arranca (o reutiliza) la VM y un servidor HTTP por corrida;
`vm-up RUN_ID --down` la para. Sockets QMP y serie propios de la corrida, disco nuevo.
`QA_DISPLAY=gtk` para ver la ventana; por defecto `none`.

Control del invitado: login de root en la consola serie (ttyS0, el live no
tiene contraseña de root) que arranca `guest/agent.sh`. El agente pide
trabajos por HTTP a `10.0.2.2:<puerto>` y devuelve salida y rc.

```bash
scripts/qa/qa cmd 'systemctl --failed'                       # root
scripts/qa/qa cmd --user 'noctalia msg status'               # usuario live, con NIRI_SOCKET/WAYLAND_DISPLAY
scripts/qa/qa key mod+spc --until-cmd 'noctalia msg status | grep -q launcher' --until-user --timeout 20
scripts/qa/qa wait --until-serial 'login:' --timeout 900
scripts/qa/qa shot launcher                                  # runs/<id>/shots/launcher.png
```

`--until-serial REGEX`, `--until-cmd 'SHELL'` (rc=0) o `--timeout N`, en vez de `sleep`.

### Niri en la VM

KVM y 3D se detectan por separado. Con `/dev/kvm` usable la VM arranca con
KVM (`-cpu host`); si no, y se pasó `--allow-tcg`, usa TCG. El 3D depende de
`/dev/dri` en el host, igual que `./churros run`: si está, QEMU usa
`virtio-vga-gl` y los puntos de UI (7-10) corren en la sesión real de greetd
(Mod = Super). Si no hay 3D, Niri no pinta en la TTY: tras medir la sesión
real (puntos 1-6 y 11) el smoke cambia el `initial_session` de greetd a
`guest/nested-niri.sh` (cage con pixman y Niri anidado) y reinicia greetd.
En la sesión anidada Mod = Alt (backend winit). Un runner con KVM y sin GPU
toma el segundo camino; no se fuerza TCG solo por falta de 3D.

## Smoke (12 puntos, siempre primero)

1 arranque · 2 `systemctl --failed` · 3 greetd + autologin · 4 `NIRI_SOCKET` ·
5 Noctalia corriendo · 6 swaybg/waybar/mako NO corren · 7 Mod+Space → lanzador ·
8 Mod+C → centro de control · 9 bloqueo · 10 notificación · 11 `fc-match Inter` ·
12 journal (`-p err`, coredumps, `[ERR]` de noctalia.log) contra `allowlist.txt`.

## qa-diffmap y features.yaml

`git diff BASE...SHA` → globs de `features.yaml` → checks de `checks/deep.py`
(`churros-verify checks` los lista). Lo que no casa con nada y no es docs sale
como **UNMAPPED** en el informe (y deja el veredicto en NOTAS): añade la
ruta a una feature o crea un check nuevo.

## Veredicto

- **RECHAZADO**: algún FAIL (smoke, deep, check o build) o una etapa rota.
- **NOTAS**: sin FAIL, pero con WARN/SKIP, UNMAPPED o avisos (TCG, reintentos por DB vieja).
- **APROBADO**: todo PASS. Los checks MANUAL (solo capturas) no cambian el veredicto,
  pero hay que revisar las capturas antes de dar el visto bueno visual.
