import os
os.environ.update(API_KEY="clave-test", USAR_BEDROCK="false", RATE_LIMIT="1000/minute")

from fastapi.testclient import TestClient
import app as modulo

cliente = TestClient(modulo.app)
H = {"X-API-Key": "clave-test"}


def falso_ok(user_id, k):
    items = (82, 149, 192, 141, 176)
    return {"user_id": user_id, "fallback": False,
            "recomendaciones": [{"item_id": i, "score": 1.0 - i / 1000} for i in items][:k]}


def falso_nuevo(user_id, k):
    return {"user_id": user_id, "fallback": True,
            "recomendaciones": [{"item_id": i, "score": None} for i in (82, 31, 43)][:k]}


def falso_caido(user_id, k):
    raise RuntimeError("endpoint caído")


def test_01_health():
    r = cliente.get("/health")
    assert r.status_code == 200 and r.json()["estado"] == "ok"


def test_02_sin_api_key_da_401():
    assert cliente.post("/recommend", json={"user_id": 0, "k": 5}).status_code == 401


def test_03_api_key_incorrecta_da_401():
    r = cliente.post("/recommend", json={"user_id": 0, "k": 5}, headers={"X-API-Key": "mala"})
    assert r.status_code == 401


def test_04_user_id_negativo_da_422():
    assert cliente.post("/recommend", json={"user_id": -1, "k": 5}, headers=H).status_code == 422


def test_05_k_cero_da_422():
    assert cliente.post("/recommend", json={"user_id": 0, "k": 0}, headers=H).status_code == 422


def test_06_k_sobre_el_maximo_da_422():
    assert cliente.post("/recommend", json={"user_id": 0, "k": 21}, headers=H).status_code == 422


def test_07_recomendacion_valida(monkeypatch):
    monkeypatch.setattr(modulo, "invocar_endpoint", falso_ok)
    r = cliente.post("/recommend", json={"user_id": 0, "k": 5}, headers=H)
    d = r.json()
    assert r.status_code == 200 and len(d["recomendaciones"]) == 5 and d["fallback"] is False
    assert {"explicacion", "accion_sugerida", "latencia_ms"} <= set(d)


def test_08_categoria_viene_del_catalogo(monkeypatch):
    monkeypatch.setattr(modulo, "invocar_endpoint", falso_ok)
    d = cliente.post("/recommend", json={"user_id": 0, "k": 5}, headers=H).json()
    assert d["recomendaciones"][0]["categoria"] == "Electrónica"


def test_09_usuario_nuevo_usa_fallback(monkeypatch):
    monkeypatch.setattr(modulo, "invocar_endpoint", falso_nuevo)
    d = cliente.post("/recommend", json={"user_id": 99999, "k": 3}, headers=H).json()
    assert d["fallback"] is True and "populares" in d["explicacion"]


def test_10_endpoint_caido_da_503(monkeypatch):
    monkeypatch.setattr(modulo, "invocar_endpoint", falso_caido)
    assert cliente.post("/recommend", json={"user_id": 0, "k": 5}, headers=H).status_code == 503


def test_11_explicacion_por_reglas_sin_bedrock(monkeypatch):
    monkeypatch.setattr(modulo, "invocar_endpoint", falso_ok)
    d = cliente.post("/recommend", json={"user_id": 0, "k": 5}, headers=H).json()
    assert d["fuente_explicacion"] == "reglas" and len(d["explicacion"]) > 10


def test_12_stats_requiere_api_key():
    assert cliente.get("/stats").status_code == 401
    assert cliente.get("/stats", headers=H).status_code == 200
