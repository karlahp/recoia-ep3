import os
import random
from locust import HttpUser, task, between

KEY = os.environ.get("API_KEY", "")


class Cliente(HttpUser):
    wait_time = between(0.05, 0.3)

    @task(9)
    def usuario_existente(self):
        self.client.post("/recommend", json={"user_id": random.randint(0, 999), "k": 10},
                         headers={"X-API-Key": KEY}, name="/recommend")

    @task(1)
    def usuario_nuevo(self):
        self.client.post("/recommend", json={"user_id": random.randint(5000, 9000), "k": 10},
                         headers={"X-API-Key": KEY}, name="/recommend (usuario nuevo)")
