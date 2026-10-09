#!/bin/sh
# Receta "Niri dentro de cage": sin virgl/3D, Niri no pinta en la TTY, así que
# cage (wlroots + pixman) da una salida por software y Niri corre anidado
# (backend winit). greetd la lanza como initial_session del usuario live.
export WLR_DRM_DEVICES=${QA_DRM_DEVICE:-/dev/dri/card0} WLR_RENDERER=pixman WLR_NO_HARDWARE_CURSORS=1
exec cage -s -- sh -c "niri > /tmp/niri-nested.log 2>&1"
