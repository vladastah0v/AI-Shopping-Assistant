from __future__ import annotations

import asyncio
from collections.abc import Sequence
from threading import Lock
from typing import TYPE_CHECKING

from app.ai.embeddings.service import EMBEDDING_DIMENSIONS, EmbeddingSpace

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

E5_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
E5_SMALL = EmbeddingSpace(
    model="intfloat/multilingual-e5-small",
    version=f"{E5_REVISION}:fp32-l2-512-v1",
    dimensions=EMBEDDING_DIMENSIONS,
    query_prefix="query: ",
    passage_prefix="passage: ",
)


class SentenceTransformersProvider:
    space = E5_SMALL

    def __init__(self, *, download_model: bool = False) -> None:
        self.download_model = download_model
        self._model: SentenceTransformer | None = None
        self._lock = Lock()

    async def prepare(self) -> None:
        await asyncio.to_thread(self._prepare)

    def _prepare(self) -> None:
        with self._lock:
            self._load()

    async def encode_batch(self, prefixed_texts: Sequence[str]) -> list[list[float]]:
        if not prefixed_texts:
            return []
        return await asyncio.to_thread(self._encode, prefixed_texts)

    def _encode(self, texts: Sequence[str]) -> list[list[float]]:
        with self._lock:
            return (
                self._load()
                .encode(
                    list(texts),
                    batch_size=len(texts),
                    show_progress_bar=False,
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                    precision="float32",
                )
                .tolist()
            )

    def _load(self) -> SentenceTransformer:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as error:
                raise RuntimeError(
                    "Для генерации нужен Linux-образ с зависимостями embeddings."
                ) from error

            try:
                model = SentenceTransformer(
                    self.space.model,
                    revision=E5_REVISION,
                    device="cpu",
                    local_files_only=not self.download_model,
                    trust_remote_code=False,
                    model_kwargs={"use_safetensors": True},
                )
            except OSError as error:
                raise RuntimeError(
                    "Не удалось загрузить модель E5. Проверьте локальный кэш "
                    "или укажите --download-model для получения весов."
                ) from error
            get_dimension = getattr(model, "get_embedding_dimension", None)
            dimension = (
                get_dimension()
                if get_dimension is not None
                else model.get_sentence_embedding_dimension()
            )
            if dimension != self.space.dimensions:
                raise ValueError("Размерность загруженной модели отличается от ожидаемых 384.")
            model.max_seq_length = 512
            self._model = model
        return self._model
