from locust import HttpUser, between, task


class ShoppingUser(HttpUser):
    wait_time = between(0.2, 0.8)

    @task(3)
    def products(self) -> None:
        self.client.get("/api/v1/products?limit=10", name="GET /products")

    @task(2)
    def keyword(self) -> None:
        self.client.post(
            "/api/v1/search/keyword",
            json={"query": "программирование", "filters": {"category_slug": "laptops"}, "top_k": 5},
            name="POST /search/keyword",
        )

    @task
    def hybrid(self) -> None:
        self.client.post(
            "/api/v1/search/hybrid",
            json={"query": "телевизор", "filters": {"category_slug": "televisions"}, "top_k": 5},
            name="POST /search/hybrid",
        )
