# Поиск товаров

Три маршрута принимают один формат JSON.

- `POST /api/v1/search/keyword` ищет лексемы и артикулы PostgreSQL.
- `POST /api/v1/search/semantic` ранжирует по косинусной близости векторов E5.
- `POST /api/v1/search/hybrid` объединяет места в двух выдачах по Reciprocal Rank Fusion с константой 60. Каждая ветвь возвращает до четырёх значений `top_k` кандидатов, максимум 100. [Публикация RRF](https://research.google/pubs/reciprocal-rank-fusion-outperforms-condorcet-and-individual-rank-learning-methods/).

```json
{
  "query": "ноутбук",
  "top_k": 5,
  "filters": {"category_slug": "laptops", "max_price": 80000, "in_stock": true, "spec": ["ram_gb:gte:16"]}
}
```

Обязательные фильтры применяются в обеих ветвях и при чтении карточек. Ответ содержит запрошенную `strategy`, применённую `applied_strategy` и массив `items` с объектами `product` и `score`. Оценки сопоставимы только в пределах одной стратегии. Отсутствие подходящих товаров возвращает пустой массив.

Для семантического режима подготовьте модель и векторы по [инструкции](embeddings.md), затем запустите API с `docker compose -f docker-compose.yml -f docker-compose.semantic.yml up -d --build api`. Контейнер читает веса из тома embeddings. Максимальное ожидание векторизации задаёт `SHOPPING_EMBEDDING_TIMEOUT_SECONDS`. При выключенной или недоступной модели семантический маршрут отвечает `503`, а гибридный возвращает `applied_strategy: "keyword"`.
