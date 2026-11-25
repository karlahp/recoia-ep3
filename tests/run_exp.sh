#!/usr/bin/env bash
# Uso: KEY=<key> bash tests/run_exp.sh <nombre> <on|off> <usuarios...>   (on/off = RabbitMQ)
set -u
cd "$(dirname "$0")/.."
: "${KEY:?Define KEY}"; NOM="${1:?nombre}"; BUS="${2:?on|off}"; shift 2
AMQP="${RABBITMQ_URL:-$(grep "^RABBITMQ_URL=" .env | cut -d= -f2-)}"

setenv() { grep -q "^$1=" .env && sed -i "s#^$1=.*#$1=$2#" .env || echo "$1=$2" >> .env; }
reiniciar() {
  docker compose --profile bus up -d --force-recreate api > /dev/null
  for i in $(seq 1 30); do
    [ "$(docker inspect -f '{{.State.Health.Status}}' recoia-ep3-api-1 2>/dev/null)" = healthy ] && break
    sleep 2
  done
}
restaurar() {
  setenv RATE_LIMIT 30/minute; setenv REC_CACHE_TTL 300; setenv USAR_BEDROCK false; setenv RABBITMQ_URL "$AMQP"
  reiniciar; echo "Configuración final restaurada."
}
trap restaurar EXIT
carga() {
  CSV=""; [ -n "$3" ] && CSV="--csv /mnt/locust/$3"
  docker run --rm --network recoia-net -e API_KEY="$KEY" -v "$PWD/tests:/mnt/locust" \
    locustio/locust -f /mnt/locust/locustfile.py --headless -u "$1" -r 10 -t "$2" \
    --host http://api:8000 $CSV > /dev/null 2>&1
}
setenv RATE_LIMIT 100000/minute; setenv USAR_BEDROCK false; setenv REC_CACHE_TTL 300
if [ "$BUS" = "on" ]; then setenv RABBITMQ_URL "$AMQP"; else setenv RABBITMQ_URL ""; fi
reiniciar
echo "Calentando (45 s)..."; carga 10 45s ""
for U in "$@"; do echo "$NOM: $U usuarios (120 s)"; carga "$U" 120s "e_${NOM}_u$U"; done
echo "Listo."
