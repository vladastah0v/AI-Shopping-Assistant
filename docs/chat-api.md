# Chat API

Базовый путь — `/api/v1/chat`. Запросы принимают JSON. Первый `POST /sessions` возвращает UUID и секретный `access_token`. Передавайте секрет через `Authorization: Bearer …`. С ним можно создавать дополнительные сессии того же владельца и получать их список. По чужому или истёкшему UUID возвращается `404`.

| Метод и путь | Операция |
|---|---|
| `POST /sessions` | Создать сессию. Тело `{}` использует название по умолчанию |
| `GET /sessions` | Перечислить свои сессии с `limit` и `offset` |
| `GET /sessions/{id}` | Прочитать сессию |
| `DELETE /sessions/{id}` | Удалить сессию и связанные записи |
| `POST /sessions/{id}/messages` | Передать `{"content":"Подбери ноутбук до 80000 рублей"}` |
| `GET /sessions/{id}/messages` | Получить историю в исходном порядке, параметры `limit` и `before` по позиции |
| `DELETE /sessions/{id}/messages` | Очистить историю и состояние |
| `POST /sessions/{id}/stream` | Отправить сообщение и получить события SSE |
| `POST /feedback` | Оставить или обновить оценку `rating` от 1 до 5 по `session_id` и `message_id` ответа |

В ответе на сообщение возвращаются `session_id`, `message_id`, `answer`, `intent`, `recommended_products`, `recommendations`, `sources`, `compared_specifications`, `clarification_required` и `metadata`. Факты и источники проверяются до сохранения и отправки.

SSE начинает событие `accepted`. После обработки приходит `result` с полной проверенной структурой или `error`. Событие `result` отправляется после записи хода. Отключение клиента отменяет незавершённую обработку. [Состояние диалога](conversations.md) · [Проверка фактов](rag.md).
