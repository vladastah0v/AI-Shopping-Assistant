import argparse
import asyncio
import csv
import json
import platform
import resource
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from random import Random
from time import perf_counter, process_time
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import RedisCache
from app.core.config import Settings
from app.core.database import create_database_engine
from app.core.redis import create_redis_client
from app.modules.catalog.models import Product
from app.modules.catalog.schemas import ProductFilters
from app.modules.search.schemas import SearchRequest
from app.modules.search.service import ProductSearch


def percentile(samples: list[float], fraction: float) -> float:
    ordered = sorted(samples)
    index = (len(ordered) - 1) * fraction
    lower = int(index)
    return ordered[lower] + (ordered[min(len(ordered) - 1, lower + 1)] - ordered[lower]) * (
        index - lower
    )


def summarize(samples: list[float]) -> dict:
    return {
        "samples": len(samples),
        **{
            f"p{percent}_ms": round(percentile(samples, percent / 100), 4)
            for percent in (50, 95, 99)
        },
        "serial_rps": round(1000 * len(samples) / sum(samples), 3),
        "error_rate": 0,
    }


async def compare_indexes(db: AsyncSession, iterations: int, top_k: int) -> list[dict]:
    await db.execute(
        text(
            "CREATE TEMP TABLE benchmark_vectors (id integer PRIMARY KEY, embedding vector(384)) ON COMMIT DROP"
        )
    )
    rng = Random(42)
    data = [
        {"id": index, "vector": json.dumps([rng.uniform(-1, 1) for _ in range(384)])}
        for index in range(100)
    ]
    await db.execute(
        text("INSERT INTO benchmark_vectors(id, embedding) VALUES (:id, CAST(:vector AS vector))"),
        data,
    )
    queries = [data[index % len(data)]["vector"] for index in range(iterations)]
    await db.execute(text("ANALYZE benchmark_vectors"))
    await db.execute(text("SET LOCAL hnsw.ef_search = 20"))
    await db.execute(text("SET LOCAL ivfflat.probes = 2"))
    distance = "embedding <=> CAST(:vector AS vector)"
    rankings: list[set[int]] = []
    results = []
    for mode in ("exact", "hnsw", "ivfflat"):
        build_ms = None
        if mode != "exact":
            options = " WITH (lists = 10)" if mode == "ivfflat" else ""
            started = perf_counter()
            await db.execute(
                text(
                    f"CREATE INDEX benchmark_ann ON benchmark_vectors USING {mode} (embedding vector_cosine_ops){options}"
                )
            )
            build_ms = round((perf_counter() - started) * 1000, 4)
            await db.execute(text("SET LOCAL enable_seqscan = off"))
        order = f"({distance}) + 0, id" if mode == "exact" else distance
        statement = f"SELECT id FROM benchmark_vectors ORDER BY {order} LIMIT :limit"
        parameters = {"vector": queries[0], "limit": top_k}
        plan = "\n".join((await db.execute(text("EXPLAIN " + statement), parameters)).scalars())
        if mode != "exact" and "benchmark_ann" not in plan:
            raise RuntimeError(f"Оптимизатор не использовал индекс {mode}.")
        latencies = []
        recall = []
        for index, vector in enumerate(queries):
            started = perf_counter()
            rows = await db.scalars(text(statement), {"vector": vector, "limit": top_k})
            found = set(rows.all())
            latencies.append((perf_counter() - started) * 1000)
            if mode == "exact":
                rankings.append(found)
                recall.append(1.0)
            else:
                reference = rankings[index]
                recall.append(len(reference & found) / len(reference))
        results.append(
            {
                "experiment": f"pgvector_{mode}",
                "top_k": top_k,
                "recall_at_k": round(sum(recall) / len(recall), 6),
                "index_build_ms": build_ms,
                **summarize(latencies),
            }
        )
        if mode != "exact":
            await db.execute(text("DROP INDEX benchmark_ann"))
    return results


async def compare_keyword_cache(
    db: AsyncSession, iterations: int, top_k: int, cache: RedisCache
) -> list[dict]:
    corpus_count = len((await db.scalars(select(Product.id).limit(100))).all())
    if corpus_count < 100:
        raise RuntimeError("Подготовьте синтетический каталог small перед запуском.")
    output = []
    for name, service in (
        ("keyword_cache_off", ProductSearch(None)),
        ("keyword_cache_on", ProductSearch(None, cache=cache)),
    ):
        request = SearchRequest(
            query="программирование",
            top_k=top_k,
            filters=ProductFilters(category_slug="laptops"),
        )
        first = perf_counter()
        response = await service.search(db, request, "keyword")
        cold_ms = (perf_counter() - first) * 1000
        samples = []
        for _ in range(iterations):
            started = perf_counter()
            cached = await service.search(db, request, "keyword")
            samples.append((perf_counter() - started) * 1000)
            if cached != response:
                raise RuntimeError("Результаты холодного и повторного поиска различаются.")
        output.append(
            {
                "experiment": name,
                "top_k": top_k,
                "first_request_ms": round(cold_ms, 4),
                **summarize(samples),
            }
        )
    return output


async def compare_http(base_url: str, iterations: int, top_k: int, concurrency: int) -> list[dict]:
    results = []
    async with httpx.AsyncClient(base_url=base_url, timeout=20, trust_env=False) as client:
        gate = asyncio.Semaphore(concurrency)
        for mode in ("keyword", "semantic", "hybrid"):

            async def sample(strategy: str = mode) -> tuple[float, bool, bool]:
                async with gate:
                    started = perf_counter()
                    try:
                        response = await client.post(
                            f"/api/v1/search/{strategy}",
                            json={"query": "программирование", "top_k": top_k},
                        )
                        success = response.is_success
                        payload = response.json() if success else None
                        applied = (
                            isinstance(payload, dict)
                            and payload.get("applied_strategy") == strategy
                        )
                    except (httpx.HTTPError, ValueError):
                        success = applied = False
                    return (perf_counter() - started) * 1000, success, applied

            started = perf_counter()
            calls = await asyncio.gather(*(sample() for _ in range(iterations)))
            elapsed = perf_counter() - started
            results.append(
                {
                    "experiment": f"http_{mode}",
                    "top_k": top_k,
                    "concurrency": concurrency,
                    **summarize([duration for duration, _, _ in calls]),
                    "overall_rps": round(iterations / elapsed, 3),
                    "error_rate": round(
                        sum(not success for _, success, _ in calls) / iterations, 6
                    ),
                    "applied_strategy_rate": round(
                        sum(applied for _, _, applied in calls) / iterations, 6
                    ),
                }
            )
    return results


async def run(args: argparse.Namespace) -> dict:
    settings = Settings()
    started = perf_counter()
    cpu = process_time()
    async with AsyncExitStack() as resources:
        engine = create_database_engine(settings)
        resources.push_async_callback(engine.dispose)
        redis = create_redis_client(settings)
        resources.push_async_callback(redis.aclose)
        rows = []
        for top_k in args.top_k:
            async with AsyncSession(engine) as db:
                rows.extend(await compare_indexes(db, args.iterations, top_k))
                await db.rollback()
                rows.extend(
                    await compare_keyword_cache(db, args.iterations, top_k, RedisCache(redis))
                )
    if args.api_url:
        for top_k in args.top_k:
            rows.extend(await compare_http(args.api_url, args.iterations, top_k, args.concurrency))
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {
        "profile": "small",
        "catalog_size": 100,
        "vector_fixture": "synthetic-random-seed-42-384d",
        "machine": {"platform": platform.system(), "architecture": platform.machine()},
        "client_cpu_seconds": round(process_time() - cpu, 4),
        "client_max_rss_bytes": rss if sys.platform == "darwin" else rss * 1024,
        "elapsed_seconds": round(perf_counter() - started, 4),
        "llm_latency": "NOT_MEASURED",
        "embedding_latency": "NOT_MEASURED",
        "time_to_first_token": "NOT_MEASURED",
        "tokens_per_second": "NOT_MEASURED",
        "experiments": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Сравнить режимы pgvector и кэш на малом профиле.")
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--top-k", type=int, nargs="+", default=[5, 10])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--api-url", help="Базовый URL собственного тестового API.")
    parser.add_argument("--concurrency", type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.concurrency <= 32:
        parser.error("Допустима конкуренция от 1 до 32.")
    if args.api_url and urlsplit(args.api_url).scheme not in ("http", "https"):
        parser.error("Укажите HTTP или HTTPS для тестового API.")
    if not 1 <= args.iterations <= 100 or any(not 1 <= k <= 50 for k in args.top_k):
        parser.error("Допустимо 1–100 повторов и top_k от 1 до 50.")
    report = asyncio.run(run(args))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    rows = report["experiments"]
    with (args.output_dir / "results.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=list(dict.fromkeys(key for row in rows for key in row)),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
