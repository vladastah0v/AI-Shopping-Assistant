# Схема каталога

Модели SQLAlchemy и миграция Alembic `0002` описывают четыре таблицы PostgreSQL. Идентификаторы имеют тип `UUID` и генерируются в базе, если при вставке указан только набор бизнес-полей.

```mermaid
erDiagram
    categories o|--o{ categories : "родительская категория"
    categories ||--o{ products : "содержит товары"
    brands ||--o{ products : "выпускает товары"
    products ||--o{ product_documents : "имеет документы"
```

| Таблица | Данные и ограничения |
|---|---|
| `categories` | Название, описание, уникальный `slug` и необязательная ссылка на родителя. База отклоняет ссылку категории на саму себя. |
| `brands` | Уникальное название и описание бренда. |
| `products` | Категория, бренд, название, уникальный артикул, описание, цена, валюта, остаток, характеристики, рейтинг и признак активности. Остаток и цена неотрицательны, рейтинг при наличии находится в диапазоне от 0 до 5. |
| `product_documents` | Товар, тип, заголовок, содержимое, источник и временные метки. Поддерживаются описание товара, технические характеристики, руководство и частые вопросы. |

Цена хранится в `NUMERIC(14,2)` и представлена в Python как `Decimal`. Валюта по умолчанию — `RUB`, а схема проверяет формат трёхбуквенного кода. Временные метки хранятся в `TIMESTAMP WITH TIME ZONE`. Триггеры PostgreSQL обновляют `updated_at` у товаров и документов при записи через ORM или SQL.

Категорию или бренд с привязанными товарами можно удалить после переноса или удаления этих товаров. При удалении товара PostgreSQL удаляет его документы. B-tree-индексы покрывают поиск по родительской категории, бренду, товару для документа, диапазону цен и паре «категория, цена».

## Технические характеристики

Поле `products.specifications` хранит JSON-объект. Перечисленные числовые ключи принимают положительные числа в заданных единицах. Отсутствующая характеристика представляется отсутствием ключа.

| Ключи | Единица измерения |
|---|---|
| `ram_gb`, `ssd_gb`, `storage_gb`, `vram_gb` | ГБ |
| `display_size_in` | дюймы |
| `resolution_width_px`, `resolution_height_px` | пиксели |
| `refresh_rate_hz` | Гц |
| `battery_capacity_mah` | мА·ч |
| `camera_mp` | Мп |
| `weight_g` | граммы |
| `volume_l` | литры |
| `load_capacity_kg` | килограммы |
| `power_w` | Вт |

Числовые фильтры используют приведение значения к `numeric`. При отсутствующем ключе выражение сравнения исключает товар из результата.

```sql
SELECT id, sku, price
FROM products
WHERE is_active
  AND currency = 'RUB'
  AND price <= 80000.00
  AND (specifications ->> 'ram_gb')::numeric >= 16;
```

## Миграции и права доступа

В Compose `shopping_migrator` применяет миграции, а `shopping_app` получает `SELECT` на четыре таблицы каталога. При развёртывании вне Compose роль `shopping_app` должна существовать до применения `0002`. Миграция не заполняет таблицы данными.

```bash
docker compose run --rm migrate alembic current
docker compose run --rm migrate alembic check
```

Откат к `0001` удаляет таблицы каталога и их данные. Расширение pgvector остаётся установленным.

## Интеграционные проверки

Для проверок каталога запустите отдельный проект Compose. Публикация порта PostgreSQL в примере действует только для тестового окружения и привязана к loopback.

```bash
API_PORT=18000 docker compose -p ai-shopping-assistant-catalog-test \
  -f docker-compose.yml -f - up --build --wait <<'YAML'
services:
  postgres:
    ports:
      - "127.0.0.1:55432:5432"
YAML
```

В `SHOPPING_TEST_DATABASE_URL` укажите пароль `POSTGRES_PASSWORD` из тестового окружения. В URL специальные символы пароля требуют процентного кодирования. Тесты каталога откатывают свои транзакции.

```bash
SHOPPING_TEST_BASE_URL=http://127.0.0.1:18000 \
  SHOPPING_TEST_DATABASE_URL='postgresql+asyncpg://shopping_migrator:LOCAL_PASSWORD@127.0.0.1:55432/shopping_assistant' \
  uv run --locked pytest --cov=app --cov-report=term-missing
```
