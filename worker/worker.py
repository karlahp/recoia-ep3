import json
import logging
import os
import time
from collections import Counter
import pika

logging.basicConfig(level=logging.INFO, format="%(asctime)s [WORKER] %(levelname)s %(message)s")
log = logging.getLogger("recoia-worker")

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/")
COLA = "recomendaciones"


def procesar_mensaje(ch, method, properties, body):
    evento = json.loads(body.decode("utf-8"))
    cats = evento.get("categorias", [])
    top_cat = Counter(cats).most_common(1)[0][0] if cats else "N/A"
    log.info(
        "Evento recibido | user_id=%s | fallback=%s | items=%d | cat_principal=%s",
        evento.get("user_id"),
        evento.get("fallback"),
        len(cats),
        top_cat,
    )
    ch.basic_ack(delivery_tag=method.delivery_tag)


def main():
    params = pika.URLParameters(RABBITMQ_URL)
    while True:
        try:
            conn = pika.BlockingConnection(params)
            ch = conn.channel()
            ch.queue_declare(queue=COLA, durable=True)
            ch.basic_qos(prefetch_count=1)
            ch.basic_consume(queue=COLA, on_message_callback=procesar_mensaje)
            log.info("Conectado a RabbitMQ. Escuchando cola '%s'...", COLA)
            ch.start_consuming()
        except Exception as e:
            log.warning("Esperando conexión con RabbitMQ (%s). Reintentando en 3s...", e)
            time.sleep(3)


if __name__ == "__main__":
    main()
