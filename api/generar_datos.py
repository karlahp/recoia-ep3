import numpy as np
import pandas as pd

rng = np.random.default_rng(42)
N_USERS, N_ITEMS = 1000, 200
categorias = ["Electrónica", "Hogar", "Moda", "Deportes", "Belleza"]

catalogo = pd.DataFrame({
    "item_id": np.arange(N_ITEMS),
    "categoria": rng.choice(categorias, N_ITEMS),
})
usuarios = pd.DataFrame({
    "user_id": np.arange(N_USERS),
    "region": rng.choice(["Central", "Norte", "Sur"], N_USERS, p=[0.6, 0.2, 0.2]),
    "cat_favorita": rng.choice(categorias, N_USERS),
})
catalogo.to_csv("catalogo.csv", index=False)
usuarios.to_csv("usuarios.csv", index=False)

print("Categorías de los productos 82,149,192,141,176:",
      catalogo.set_index("item_id").loc[[82, 149, 192, 141, 176], "categoria"].tolist())
print("Categoría favorita del usuario 0:", usuarios.loc[0, "cat_favorita"])
