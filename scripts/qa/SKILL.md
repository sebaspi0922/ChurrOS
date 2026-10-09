---
name: churros-verify
description: >-
  Cuando haya que verificar (QA) una rama, SHA o PR de ChurrOS antes de aprobarla:
  compila o reutiliza la ISO, la arranca en una VM QEMU, corre el smoke fijo de
  12 puntos y las pruebas que tocan según el diff, y deja un informe con
  veredicto APROBADO / NOTAS / RECHAZADO.
---
# churros-verify

La herramienta vive en el repo de ChurrOS, en `scripts/qa/` (léete su `README.md`).
Todo se corre en la máquina que tenga QEMU y el checkout, nunca en el equipo del usuario.

## Pasos
1. **Checkout del SHA.** En el repo: `git fetch <remoto> <rama>`. Si el checkout
   principal lo usa otra corrida, trabaja en un `git worktree` aparte. No hagas push ni PR.
2. **Preflight.** `scripts/qa/churros-verify preflight`. Si falla por KVM y no hay
   otra opción, sigue con `--allow-tcg` y dilo en el informe (TCG es ~10× más lento).
   KVM y 3D salen por separado: sin `/dev/dri`, Niri se anida en cage aunque haya KVM.
   Si hay otra VM de QA corriendo que no es tuya, no la mates: espera a que termine.
3. **ISO ya compilada de ese SHA (opcional).** `scripts/qa/churros-verify cache-iso <SHA> <ruta.iso>`
   evita recompilar. Solo si sabes que esa ISO salió de ese SHA exacto.
4. **Lanzar.** `scripts/qa/churros-verify run <SHA> [--edition niri] [--allow-tcg] [--keep-vm]`.
   Vuelve enseguida con un `RUN_ID`; el pipeline sigue en segundo plano.
5. **Seguir sin bloquear.** `scripts/qa/churros-verify status <RUN_ID>` o
   `runs/<RUN_ID>/progress.log`. Si tu tarea se corta (límite de tiempo, reinicio),
   retoma con `scripts/qa/churros-verify resume <RUN_ID>`: sigue desde la primera
   etapa sin terminar y reutiliza la VM y los resultados que ya hay.
6. **Pruebas a mano si hacen falta** (con `--keep-vm`): `scripts/qa/qa cmd|key|shot|wait`
   con `--until-serial`, `--until-cmd` o `--timeout` en vez de `sleep`.
   Para acabar, `scripts/qa/churros-verify stop <RUN_ID>`.
7. **Informe.** `scripts/qa/churros-verify report <RUN_ID>` regenera
   `runs/<RUN_ID>/report.md` (+ `results.jsonl`). Antes de dar el veredicto, abre
   las capturas de `shots/` y los checks MANUAL: el veredicto automático no juzga lo visual.
8. **Comunicar.** Resume el veredicto, la tabla del smoke, los FAIL/WARN con su evidencia,
   los UNMAPPED y los avisos (TCG, reintentos). RECHAZADO o NOTAS van con notas
   accionables (archivo y línea) para quien hizo la rama.

## Mantenimiento
- Una ruta UNMAPPED significa que `features.yaml` no la cubre: añade el glob a una
  feature o un check nuevo en `checks/deep.py`, y súbelo con la siguiente rama.
- `allowlist.txt` es solo para ruido de la VM (sin 3D, sin BlueZ, sin red externa).
  Un error real del producto no se mete ahí.
