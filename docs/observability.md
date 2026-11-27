# Метрики и журналы

API предоставляет `GET /metrics` в формате Prometheus. HTTP-метрики используют шаблон пути, метод и статус. Запросы модели, векторизация, retrieval, операции каталога, Redis и защитные отказы имеют отдельные метрики. При наличии статистики Ollama собираются входные и выходные токены. Метки содержат только фиксированные категории и имена инструментов.

Журнал приложения пишет JSON-строки с UTC-временем, уровнем, именем события и разрешёнными полями. HTTP-события содержат шаблон маршрута, метод, статус и длительность. Заголовки, UUID сессий и пользовательский текст в эти события не включаются. Docker запускает Uvicorn с отключённым необработанным журналом доступа.

```bash
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml --profile monitoring up -d --build
```

Перед запуском задайте отдельный `GRAFANA_ADMIN_PASSWORD` в окружении или `.env`. Prometheus доступен на `127.0.0.1:9090`, Grafana — на `127.0.0.1:3000`. Источник данных и панель «AI Shopping Assistant» загружаются из репозитория автоматически. [Prometheus](https://prometheus.io/docs/prometheus/latest/configuration/configuration/) · [Grafana](https://grafana.com/docs/grafana/latest/administration/provisioning/).
