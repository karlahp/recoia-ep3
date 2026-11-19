import csv
import json
import logging
import os
import secrets
import time
from collections import Counter

import boto3
from botocore.config import Config
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

# ---------- Configuración (variables de entorno) ----------
API_KEY = os.getenv("API_KEY", "")
REGION = os.getenv("AWS_REGION", "us-east-1")
ENDPOINT_NAME = os.getenv("SAGEMAKER_ENDPOINT", "recoia-endpoint")
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0")
USAR_BEDROCK = os.getenv("USAR_BEDROCK", "true").lower() == "true"
RATE_LIMIT = os.getenv("RATE_LIMIT", "30/minute")
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("recoia")

# ---------- Datos de apoyo (catálogo y perfiles) ----------
def _leer(nombre):
    ruta = os.path.join(os.path.dirname(__file__), nombre)
    with open(ruta, encoding="utf-8") as f:
        return list(csv.DictReader(f))

CATEGORIA = {int(r["item_id"]): r["categoria"] for r in _leer("catalogo.csv")}
PERFIL = {int(r["user_id"]): r for r in _leer("usuarios.csv")}

# ---------- Clientes AWS ----------
runtime = boto3.client("sagemaker-runtime", config=Config(
    region_name=REGION, read_timeout=10, connect_timeout=3, retries={"max_attempts": 2}))
bedrock = boto3.client("bedrock-runtime", config=Config(
    region_name=REGION, read_timeout=20, connect_timeout=3, retries={"max_attempts": 1}))

STATS = Counter()
_CACHE = {}

# ---------- Seguridad ----------
def clave_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    return xff.split(",")[0].strip() if xff else request.client.host

limiter = Limiter(key_func=clave_ip)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def verificar_key(clave: str = Depends(api_key_header)):
    if not API_KEY or not clave or not secrets.compare_digest(clave, API_KEY):
        raise HTTPException(status_code=401, detail="API key inválida o ausente")

# ---------- Aplicación ----------
app = FastAPI(
    title="RecoIA API",
    version="1.0.0",
    description="Recomendaciones de productos (modelo ALS en SageMaker) con explicación "
                "generada por Amazon Bedrock y acción sugerida para el negocio.",
    root_path="/api",
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.middleware("http")
async def registrar(request: Request, call_next):
    t0 = time.time()
    resp = await call_next(request)
    log.info("%s %s -> %s en %.0f ms", request.method, request.url.path,
             resp.status_code, (time.time() - t0) * 1000)
    return resp


class Consulta(BaseModel):
    user_id: int = Field(..., ge=0, examples=[0])
    k: int = Field(10, ge=1, le=20)


# ---------- Lógica ----------
def invocar_endpoint(user_id: int, k: int) -> dict:
    r = runtime.invoke_endpoint(
        EndpointName=ENDPOINT_NAME,
        ContentType="application/json",
        Body=json.dumps({"user_id": user_id, "k": k}),
    )
    return json.loads(r["Body"].read())


def explicar_reglas(perfil, recs, fallback):
    if fallback:
        return "Usuario sin historial: se muestran los productos más populares del catálogo."
    top, n = Counter(r["categoria"] for r in recs).most_common(1)[0]
    texto = f"{n} de {len(recs)} recomendaciones son de {top}"
    if perfil and perfil["cat_favorita"] == top:
        texto += ", su categoría favorita según su historial"
    return texto + "."


def explicar(user_id: int, items: tuple, fallback: bool):
    perfil = PERFIL.get(user_id)
    recs = [{"categoria": CATEGORIA.get(i, "desconocida")} for i in items]
    reglas = explicar_reglas(perfil, recs, fallback)
    if not USAR_BEDROCK or fallback or perfil is None:
        return reglas, "reglas"

    clave = (user_id, items)
    if clave in _CACHE:
        STATS["cache_aciertos"] += 1
        return _CACHE[clave], "bedrock (caché)"

    prompt = (
        "Eres el asistente de una tienda en línea. Explica en español, en 2 frases claras "
        "y sin tecnicismos, por qué se le recomiendan estos productos a un cliente. "
        f"Región del cliente: {perfil['region']}. "
        f"Categoría favorita según su historial: {perfil['cat_favorita']}. "
        f"Categorías de los productos recomendados, en orden: {', '.join(r['categoria'] for r in recs)}. "
        "No inventes datos que no estén aquí."
    )
    try:
        body = {"anthropic_version": "bedrock-2023-05-31", "max_tokens": 200,
                "messages": [{"role": "user", "content": prompt}]}
        r = bedrock.invoke_model(modelId=BEDROCK_MODEL_ID, body=json.dumps(body),
                                 contentType="application/json", accept="application/json")
        texto = json.loads(r["body"].read())["content"][0]["text"].strip()
        STATS["bedrock_llamadas"] += 1
        _CACHE[clave] = texto
        return texto, "bedrock"
    except Exception as e:
        STATS["bedrock_fallos"] += 1
        log.warning("Bedrock falló, se usa explicación por reglas: %s", e)
        return reglas, "reglas"


def accion_sugerida(recs, fallback):
    if fallback:
        return ("Usuario nuevo: mostrar los productos más vendidos y registrar sus primeras "
                "interacciones para personalizar.")
    top, n = Counter(r["categoria"] for r in recs).most_common(1)[0]
    if n >= len(recs) / 2:
        return f"Destacar la categoría {top} en la portada del usuario y evaluar un cupón de esa categoría."
    return "Intereses variados: mostrar un carrusel mixto y medir qué categoría genera más clics."


def publicar_evento(evento: dict):
    """Publica el evento en RabbitMQ si está configurado (no bloquea la respuesta)."""
    if not RABBITMQ_URL:
        return
    try:
        import pika
        conn = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
        ch = conn.channel()
        ch.queue_declare(queue="recomendaciones", durable=True)
        ch.basic_publish(exchange="", routing_key="recomendaciones", body=json.dumps(evento),
                         properties=pika.BasicProperties(delivery_mode=2))
        conn.close()
        STATS["eventos_publicados"] += 1
    except Exception as e:
        STATS["eventos_fallidos"] += 1
        log.warning("No se pudo publicar el evento: %s", e)


# ---------- Endpoints ----------
@app.get("/health", tags=["Sistema"])
def health():
    return {"estado": "ok", "endpoint": ENDPOINT_NAME}


@app.get("/stats", tags=["Sistema"], dependencies=[Depends(verificar_key)])
def stats():
    return dict(STATS)


@app.post("/recommend", tags=["Recomendaciones"], dependencies=[Depends(verificar_key)])
@limiter.limit(RATE_LIMIT)
def recomendar(request: Request, consulta: Consulta, tareas: BackgroundTasks):
    t0 = time.time()
    STATS["consultas"] += 1
    try:
        out = invocar_endpoint(consulta.user_id, consulta.k)
    except Exception as e:
        STATS["errores_endpoint"] += 1
        log.error("Fallo al invocar SageMaker: %s", e)
        raise HTTPException(status_code=503,
                            detail="El servicio de recomendación no está disponible por ahora")

    fallback = bool(out.get("fallback"))
    recs = [{"item_id": r["item_id"],
             "categoria": CATEGORIA.get(r["item_id"], "desconocida"),
             "score": r.get("score")} for r in out["recomendaciones"]]
    texto, fuente = explicar(consulta.user_id, tuple(r["item_id"] for r in recs), fallback)

    tareas.add_task(publicar_evento, {
        "user_id": consulta.user_id, "fallback": fallback,
        "categorias": [r["categoria"] for r in recs], "ts": time.time()})

    return {
        "user_id": consulta.user_id,
        "fallback": fallback,
        "recomendaciones": recs,
        "explicacion": texto,
        "fuente_explicacion": fuente,
        "accion_sugerida": accion_sugerida(recs, fallback),
        "latencia_ms": round((time.time() - t0) * 1000),
    }
