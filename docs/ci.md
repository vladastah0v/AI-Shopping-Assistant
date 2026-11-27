# Автоматические проверки

GitHub Actions запускает проверки для pull request и обновлений `main`. Workflow использует разрешение чтения репозитория, закреплённые ревизии Actions и Gitleaks с маскированием найденных значений.

`scripts/ci_checks.sh` используется в GitHub Actions и при локальной проверке. Команда проверяет lock-файл, Ruff, форматирование и все варианты Compose. Затем она собирает API, поднимает изолированные PostgreSQL с pgvector и Redis, применяет миграции и запускает тесты. Покрытие приложения должно быть не ниже 80%. Для CI сохраняется XML-артефакт. Тестовая конфигурация создаёт отдельные случайные пароли и удаляет временные тома после проверки.

```bash
./scripts/ci_checks.sh
```

Рабочие сервисы используют локальные провайдеры. В CI модель Ollama отключена, сценарии модели используют тестовый транспорт или тестовые ответы. [GitHub Actions для Python](https://docs.github.com/en/actions/use-cases-and-examples/building-and-testing/building-and-testing-python) · [Настройка uv](https://docs.astral.sh/uv/guides/integration/github/).
