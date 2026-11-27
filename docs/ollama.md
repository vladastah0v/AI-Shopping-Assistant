# Локальная языковая модель

Провайдер использует асинхронный `POST /api/chat` с поддержкой JSON Schema и потокового NDJSON. Для полного запроса повторяются ошибки подключения, HTTP 429, 502, 503 и 504. Таймаут охватывает ожидание свободного слота и генерацию. Поток не повторяется после отправки запроса. `GET /health/ai` проверяет наличие настроенной модели через `GET /api/tags`. Состояние `disabled` или `unavailable` сохраняет доступность каталога и поиска. [API Ollama](https://docs.ollama.com/api/chat) · [Формат потока](https://docs.ollama.com/api/streaming).

## Модель и ресурсы

Стартовый вариант — многоязычная `qwen2.5:1.5b` Q4_K_M с размером весов 986 МБ. Для планирования выделите минимум 3 ГиБ доступной памяти под Ollama с контекстом 4096 и одним запросом, плюс память PostgreSQL, Redis и приложения. Это ориентир. Фактические память и скорость на Intel — `NOT_MEASURED`. Сетевая и прикладная интеграция проверена с тестовым HTTP-транспортом. Запуск локальных весов — `NOT_RUN`. [Карточка модели](https://ollama.com/library/qwen2.5:1.5b).

## Подключение с хоста

На macOS укажите `SHOPPING_OLLAMA_ENABLED=true` и `SHOPPING_OLLAMA_URL=http://host.docker.internal:11434` в окружении Compose. При запуске API напрямую используйте `http://127.0.0.1:11434`. Ollama должна принимать соединения от API. Ограничьте доступ к порту локальной сетью контейнера или хоста.

## Отдельный контейнер

```bash
docker compose -f docker-compose.yml -f docker-compose.ollama.yml --profile llm up -d --build
docker compose -f docker-compose.yml -f docker-compose.ollama.yml --profile llm exec ollama ollama pull qwen2.5:1.5b
curl http://127.0.0.1:8000/health/ai
```

Команда `ollama pull` скачивает веса в отдельный том. Укажите одинаковый тег в `SHOPPING_OLLAMA_MODEL` и в команде загрузки. Docker Compose не публикует порт Ollama. [Запуск Ollama в Docker](https://docs.ollama.com/docker).

| Переменная с префиксом `SHOPPING_` | Значение по умолчанию |
|---|---:|
| `OLLAMA_ENABLED` | `false` |
| `OLLAMA_MODEL` | `qwen2.5:1.5b` |
| `OLLAMA_CONNECTION_TIMEOUT_SECONDS` | 2 |
| `OLLAMA_GENERATION_TIMEOUT_SECONDS` | 45 |
| `OLLAMA_RETRIES` | 1 |
| `OLLAMA_CONCURRENCY` | 1 |
| `OLLAMA_TEMPERATURE` | 0,1 |
| `OLLAMA_MAX_TOKENS` | 512 |
| `OLLAMA_CONTEXT_TOKENS` | 4096 |
