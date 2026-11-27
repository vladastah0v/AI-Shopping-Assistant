import json
from collections import OrderedDict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from hashlib import sha256
from itertools import batched
from math import isfinite
from typing import Protocol

from app.modules.catalog.models import Product

type Vector = tuple[float, ...]
EMBEDDING_DIMENSIONS = 384


@dataclass(frozen=True, slots=True)
class EmbeddingSpace:
    model: str
    version: str
    dimensions: int
    query_prefix: str
    passage_prefix: str


class EmbeddingProvider(Protocol):
    space: EmbeddingSpace

    async def encode_batch(self, prefixed_texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


def content_hash(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def product_text(product: Product, category: str, brand: str) -> str:
    specifications = json.dumps(product.specifications, ensure_ascii=False, sort_keys=True)
    text = (
        f"Товар: {product.name}. Артикул: {product.sku}. Категория: {category}. Бренд: {brand}. "
        f"{product.description} Характеристики: {specifications}."
    )
    return " ".join(text.split())


def document_text(title: str, content: str) -> str:
    return " ".join(f"{title}. {content}".split())


def validate_vector(values: Sequence[float], dimensions: int) -> Vector:
    vector = tuple(float(value) for value in values)
    if len(vector) != dimensions:
        raise ValueError(f"Размерность вектора должна составлять {dimensions}.")
    if not all(isfinite(value) for value in vector) or not any(vector):
        raise ValueError("Для косинусной метрики нужен ненулевой вектор с конечными числами.")
    return vector


class EmbeddingService:
    def __init__(self, provider: EmbeddingProvider, *, batch_size: int = 8, cache_size: int = 128):
        if not 1 <= batch_size <= 64 or not 0 <= cache_size <= 2048:
            raise ValueError("Недопустимый размер пакета или кэша embeddings.")
        self.provider = provider
        self.space = provider.space
        self.batch_size = batch_size
        self.cache_size = cache_size
        self._cache: OrderedDict[str, Vector] = OrderedDict()

    async def encode_text(self, text: str) -> Vector:
        return (await self.encode_batch((text,)))[0]

    async def encode_query(self, query: str) -> Vector:
        return (await self.encode_batch((query,), query=True))[0]

    async def generate_product_embedding(
        self, product: Product, category: str, brand: str
    ) -> Vector:
        return await self.encode_text(product_text(product, category, brand))

    async def generate_document_embedding(self, title: str, content: str) -> Vector:
        return await self.encode_text(document_text(title, content))

    async def encode_batch(self, texts: Iterable[str], *, query: bool = False) -> list[Vector]:
        prefix = self.space.query_prefix if query else self.space.passage_prefix
        vectors = []
        for group in batched((prefix + " ".join(text.split()) for text in texts), self.batch_size):
            keyed = [(content_hash(text), text) for text in group]
            cached = {}
            missing = {}
            for key, text in keyed:
                if key in self._cache:
                    cached[key] = self._cache[key]
                    self._cache.move_to_end(key)
                else:
                    missing[key] = text

            if missing:
                raw = await self.provider.encode_batch(tuple(missing.values()))
                if len(raw) != len(missing):
                    raise ValueError("Провайдер вернул неверное число векторов.")
                generated = {
                    key: validate_vector(vector, self.space.dimensions)
                    for key, vector in zip(missing, raw, strict=True)
                }
                cached.update(generated)
                for key, vector in generated.items():
                    self._cache[key] = vector
                    self._cache.move_to_end(key)
                    if len(self._cache) > self.cache_size:
                        self._cache.popitem(last=False)
            vectors.extend(cached[key] for key, _ in keyed)
        return vectors
