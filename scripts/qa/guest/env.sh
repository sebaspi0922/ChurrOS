# shellcheck shell=bash
# Entorno de la sesión gráfica del usuario live (lo carga `qa cmd --user`).
# Elige el socket de Niri vivo más reciente (sesión real de greetd o la anidada).
export XDG_RUNTIME_DIR=/run/user/$(id -u)
export DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus
for s in $(ls -t "$XDG_RUNTIME_DIR"/niri.wayland-*.sock 2>/dev/null); do
    b=$(basename "$s" .sock); pid=${b##*.}
    if kill -0 "$pid" 2>/dev/null; then
        export NIRI_SOCKET="$s"
        w=${s#"$XDG_RUNTIME_DIR"/niri.}; export WAYLAND_DISPLAY=${w%%.*}
        break
    fi
done
