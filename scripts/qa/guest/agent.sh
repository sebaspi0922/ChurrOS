#!/bin/bash
# Agente del invitado (corre como root). Pide trabajos al host por HTTP, los
# ejecuta y devuelve salida y rc. Uso: agent.sh http://10.0.2.2:PUERTO
H="$1"; last=""; D=${QA_AGENT_DIR:-/run/qa}
mkdir -p $D
echo "$H" > $D/host; chmod 755 $D; chmod 644 $D/host
curl -sf -m 10 "$H/f/env.sh" -o $D/env.sh
chmod 644 $D/env.sh
while :; do
    code=$(curl -s -m 10 -o $D/job -w '%{http_code}' "$H/job" || echo 000)
    if [ "$code" = 200 ]; then
        id=$(head -1 $D/job | cut -c3-)
        if [ -n "$id" ] && [ "$id" != "$last" ]; then
            last="$id"
            t=$(sed -n '2s/^# timeout //p' $D/job); t=${t:-120}
            timeout -k 5 "$t" bash $D/job > $D/out 2>&1 < /dev/null
            rc=$?
            for _ in 1 2 3 4 5; do
                curl -sf -m 30 -X PUT --data-binary @$D/out "$H/result/$id?rc=$rc" >/dev/null && break
                sleep 1
            done
        fi
    fi
    sleep 0.5
done
