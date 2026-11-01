from __future__ import annotations

from typing import Any

from pyseekdb import EmbeddingFunction, register_embedding_function

from .config import EMBEDDING_MODEL

Documents = str | list[str]
Embeddings = list[list[float]]


@register_embedding_function
class BgeEmbeddingFunction(EmbeddingFunction[Documents]):
    """本地中文 embedding。

    StepFun 只提供对话模型，没有 embedding 接口；这里用 fastembed（ONNX 运行时）
    跑 bge-small-zh，避开 torch。模型文件由 huggingface_hub 下载，走 HF_ENDPOINT 镜像。
    """

    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or EMBEDDING_MODEL
        self._model: Any = None

    def _ensure_model(self) -> Any:
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=self.model_name)
        return self._model

    @staticmethod
    def _to_floats(vector: Any) -> list[float]:
        return vector.tolist() if hasattr(vector, "tolist") else list(vector)

    @property
    def dimension(self) -> int:
        model = self._ensure_model()
        value = getattr(model, "dimension", None)
        if value:
            return int(value)
        return len(self._to_floats(next(iter(model.embed(["维度探测"])))))

    def __call__(self, documents: Documents) -> Embeddings:
        if isinstance(documents, str):
            documents = [documents]
        if not documents:
            return []
        model = self._ensure_model()
        return [self._to_floats(vector) for vector in model.embed(documents)]

    @staticmethod
    def name() -> str:
        return "bge_fastembed"

    def get_config(self) -> dict[str, Any]:
        return {"model_name": self.model_name}

    @staticmethod
    def build_from_config(config: dict[str, Any]) -> "BgeEmbeddingFunction":
        return BgeEmbeddingFunction(model_name=config.get("model_name"))
