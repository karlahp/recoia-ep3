#!/usr/bin/env bash
set -u
cd "$(dirname "$0")/.."
: "${KEY:?Define KEY con tu API key}"

setenv() { grep -q "^$1=" .env && sed -i "s#^$1=.*#$1=$2#" .env || echo "$1=$2" >> .env; }
reiniciar() {
  docker compose --profile bus up -d --force-recreate api > /dev/null
  for i in $(seq 1 30); do
    [ "$(docker inspect -f '{{.State.Health.Status}}' recoia-ep3-api-1 2>/dev/null)" = healthy ] && break
    sleep 2
  done
}
restaurar() {
  setenv RATE_LIMIT 30/minute; setenv REC_CACHE_TTL 300; setenv USAR_BEDROCK false
  reiniciar; echo "Configuración final restaurada."
}
trap restaurar EXIT

carga() {
  CSV=""; [ -n "$3" ] && CSV="--csv /mnt/locust/$3"
  docker run --rm --network recoia-net -e API_KEY="$KEY" -v "$PWD/tests:/mnt/locust" \
    locustio/locust -f /mnt/locust/locustfile.py --headless -u "$1" -r 10 -t "$2" \
    --host http://api:8000 $CSV > /dev/null 2>&1
}

setenv RATE_LIMIT 100000/minute; setenv USAR_BEDROCK false

echo "== A: SIN caché =="
setenv REC_CACHE_TTL 0; reiniciar
echo "Calentando..."; carga 10 45s ""
for U in 25 50; do echo "A: $U usuarios"; carga $U 120s "c_sincache_u$U"; done

echo "== B: CON caché =="
setenv REC_CACHE_TTL 300; reiniciar
echo "Calentando..."; carga 10 45s ""
for U in 50 100 200; do echo "B: $U usuarios"; carga $U 120s "c_cache_u$U"; done
echo "Listo."
