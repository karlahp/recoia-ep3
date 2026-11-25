import hashlib, json, logging, os, time
from datetime import datetime, timezone
import boto3, pika

logging.basicConfig(level=logging.INFO, format="%(asctime)s [WORKER] %(levelname)s %(message)s")
log = logging.getLogger("recoia-worker")

RABBITMQ_URL = os.environ["RABBITMQ_URL"]
S3_BUCKET = os.environ["S3_BUCKET"]
COLA, FLUSH_SECONDS, BATCH_SIZE = "recomendaciones", 10, 50
s3 = boto3.client("s3")
vistos, lote, ultimo_flush = set(), [], time.time()
def clave_evento(e):
    if e.get("event_id"):
        return str(e["event_id"])
    return hashlib.sha1(f"{e.get('user_id','')}|{e.get('ts','')}".encode()).hexdigest()

def flush_lote():
    global lote, ultimo_flush
    if not lote:
        ultimo_flush = time.time()
        return
    now = datetime.now(timezone.utc)
    key = f"clickstream/dt={now:%Y-%m-%d}/batch_{now:%Y%m%dT%H%M%SZ}_{int(time.time()*1000)}.jsonl"
    body = "\n".join(json.dumps(e, ensure_ascii=False) for e in lote) + "\n"
    s3.put_object(Bucket=S3_BUCKET, Key=key, Body=body.encode())
    log.info("Lote archivado en s3://%s/%s (%d eventos)", S3_BUCKET, key, len(lote))
    lote, ultimo_flush = [], time.time()
def main():
    params = pika.URLParameters(RABBITMQ_URL)
    while True:
        try:
            conn = pika.BlockingConnection(params)
            ch = conn.channel()
            ch.queue_declare(queue=COLA, durable=True)
            ch.basic_qos(prefetch_count=1)
            log.info("Conectado a RabbitMQ. Escuchando cola '%s'...", COLA)
            for method, _, body in ch.consume(COLA, inactivity_timeout=2):
                if method is not None:
                    e = json.loads(body.decode())
                    eid = clave_evento(e)
                    if eid in vistos:
                        log.info("Duplicado descartado | event_id=%s", eid)
                    else:
                        vistos.add(eid)
                        lote.append(e)
                        log.info("Evento aceptado | event_id=%s | lote=%d", eid, len(lote))
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                if lote and (len(lote) >= BATCH_SIZE or time.time() - ultimo_flush >= FLUSH_SECONDS):
                    flush_lote()
        except Exception as ex:
            log.warning("Reintentando en 3s: %s", ex)
            time.sleep(3)

if __name__ == "__main__":
    main()
