import json
import os
import numpy as np


def model_fn(model_dir):
    d = np.load(os.path.join(model_dir, "modelo_als.npz"))
    e = np.load(os.path.join(model_dir, "extras.npz"))
    return {"U": d["user_factors"], "V": d["item_factors"],
            "vistos": e["vistos"], "popular": e["popular"]}


def input_fn(body, content_type="application/json"):
    if content_type != "application/json":
        raise ValueError("Solo se acepta application/json")
    data = json.loads(body)
    return {"user_id": int(data["user_id"]), "k": int(data.get("k", 10))}


def predict_fn(data, m):
    u, k = data["user_id"], max(1, min(data["k"], 50))
    if 0 <= u < m["U"].shape[0]:
        scores = m["U"][u] @ m["V"].T
        scores[m["vistos"][u]] = -np.inf   # no recomendar lo ya visto
        top = np.argsort(-scores)[:k]
        return {"user_id": u, "fallback": False,
                "recomendaciones": [{"item_id": int(i), "score": float(scores[i])} for i in top]}
    # Usuario desconocido (cold start): más populares
    top = m["popular"][:k]
    return {"user_id": u, "fallback": True,
            "recomendaciones": [{"item_id": int(i), "score": None} for i in top]}


def output_fn(pred, accept="application/json"):
    return json.dumps(pred)
