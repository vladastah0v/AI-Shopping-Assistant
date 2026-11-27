# Нагрузочные проверки

`scripts.benchmark` измеряет exact, HNSW и IVFFlat в отдельной временной таблице PostgreSQL. Контрольные векторы детерминированы, их 100, размерность 384. Exact задаёт базу для Recall@K. Для ANN отдельно фиксируется построение индекса и проверяется план. Отдельный блок измеряет текстовый поиск на каталоге small с кэшем и без кэша.

```bash
uv run --locked python -m scripts.benchmark --output-dir benchmark-results
uv run --locked --group benchmark python -m scripts.plot_benchmark benchmark-results/results.json benchmark-results/latency.png
```

Команда выводит JSON и CSV с p50, p95, p99, наблюдаемой пропускной способностью, расходом CPU и максимальной памятью клиентского процесса. Если указать `--api-url`, дополнительно измеряется HTTP для трёх стратегий с `--concurrency`. Ответы с резервной стратегией учитываются отдельно, а недоступная семантика видна в доле ошибок. Для сравнения кэша между HTTP-прогонами задайте `SHOPPING_CACHE_ENABLED=true` или `false` на тестовом API.

```bash
uv run --locked --group benchmark locust -f benchmarks/locustfile.py --headless \
  --host http://127.0.0.1:8000 --users 2 --spawn-rate 1 --run-time 10s --csv benchmark-results/locust
```

[JSON малого прогона](benchmarks/results.json) · [CSV](benchmarks/results.csv) · [График p95](benchmarks/latency.png). [Дымовой прогон HTTP](benchmarks/locust-smoke.csv) проверяет прохождение нагрузки с двумя клиентами.

Результат индексов отражает синтетический набор и настройки эксперимента. Прогон реальных весов, задержки LLM, время первого токена и скорость генерации отмечены `NOT_MEASURED`. Для холодного Redis-прогона используйте свежую тестовую базу Redis.
