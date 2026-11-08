from __future__ import annotations

import json
import logging
import math
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def _load_env_file(path: Path) -> None:
    if not path.exists() or not path.is_file():
        return
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                continue
            if len(value) >= 2 and (
                (value.startswith('"') and value.endswith('"'))
                or (value.startswith("'") and value.endswith("'"))
            ):
                value = value[1:-1]
            os.environ[key] = value
    except Exception as exc:
        logger.warning("Failed to load env file %s: %s", path, exc)


def _load_local_env_files() -> None:
    current = Path(__file__).resolve()
    backend_root = current.parents[2]
    project_root = current.parents[3]
    for candidate in (backend_root / ".env", project_root / ".env"):
        _load_env_file(candidate)


_load_local_env_files()

COLLECTION_NAME = os.getenv("MILVUS_COLLECTION", "carbon_ai_knowledge")
NEWS_COLLECTION_NAME = os.getenv("MILVUS_NEWS_COLLECTION", "carbon_ai_news")
EMBEDDING_MODEL = os.getenv("OLLAMA_EMBEDDING_MODEL", "bge-m3")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))

MILVUS_HOST = os.getenv("MILVUS_HOST", "127.0.0.1")
MILVUS_PORT = os.getenv("MILVUS_PORT", "19530")
MILVUS_USER = os.getenv("MILVUS_USER", "").strip()
MILVUS_PASSWORD = os.getenv("MILVUS_PASSWORD", "").strip()
MILVUS_DB = os.getenv("MILVUS_DB_NAME", "default").strip()
MILVUS_METRIC_TYPE = os.getenv("MILVUS_METRIC_TYPE", "COSINE")


_milvus_ready = False


def _connect_milvus():
    from pymilvus import connections

    global _milvus_ready
    if _milvus_ready:
        return
    kwargs: dict[str, str] = {
        "alias": "default",
        "host": MILVUS_HOST,
        "port": MILVUS_PORT,
        "db_name": MILVUS_DB,
    }
    if MILVUS_USER:
        kwargs["user"] = MILVUS_USER
    if MILVUS_PASSWORD:
        kwargs["password"] = MILVUS_PASSWORD
    connections.connect(**kwargs)
    _milvus_ready = True


def _ensure_collection():
    from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, utility

    _connect_milvus()
    if utility.has_collection(COLLECTION_NAME):
        col = Collection(COLLECTION_NAME)
        col.load()
        return col

    fields = [
        FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
        FieldSchema(name="source_file", dtype=DataType.VARCHAR, max_length=512),
        FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=65535),
        FieldSchema(name="metadata_json", dtype=DataType.VARCHAR, max_length=65535),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM),
    ]
    schema = CollectionSchema(fields=fields, description="Carbon knowledge embeddings")
    col = Collection(name=COLLECTION_NAME, schema=schema)
    col.create_index(
        field_name="embedding",
        index_params={
            "index_type": "IVF_FLAT",
            "metric_type": MILVUS_METRIC_TYPE,
            "params": {"nlist": 1024},
        },
    )
    col.load()
    return col


def _ensure_news_collection():
    from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, utility

    _connect_milvus()
    if utility.has_collection(NEWS_COLLECTION_NAME):
        col = Collection(NEWS_COLLECTION_NAME)
        col.load()
        return col

    fields = [
        FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
        FieldSchema(name="source_file", dtype=DataType.VARCHAR, max_length=512),
        FieldSchema(name="title", dtype=DataType.VARCHAR, max_length=512),
        FieldSchema(name="summary", dtype=DataType.VARCHAR, max_length=65535),
        FieldSchema(name="tags", dtype=DataType.VARCHAR, max_length=2048),
        FieldSchema(name="source_url", dtype=DataType.VARCHAR, max_length=1024),
        FieldSchema(name="published_at", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="metadata_json", dtype=DataType.VARCHAR, max_length=65535),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM),
    ]
    schema = CollectionSchema(fields=fields, description="Carbon industry news embeddings")
    col = Collection(name=NEWS_COLLECTION_NAME, schema=schema)
    col.create_index(
        field_name="embedding",
        index_params={
            "index_type": "IVF_FLAT",
            "metric_type": MILVUS_METRIC_TYPE,
            "params": {"nlist": 1024},
        },
    )
    col.load()
    return col


EMBED_LLM_TIMEOUT_SEC = int(os.getenv("EMBED_LLM_TIMEOUT_SEC", "20"))


def _embed_texts(texts: list[str]) -> list[list[float]]:
    try:
        import ollama

        client = ollama.Client(host=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"), timeout=EMBED_LLM_TIMEOUT_SEC)
        responses = client.embed(model=EMBEDDING_MODEL, input=texts)
        vectors = responses.get("embeddings", [])
        if vectors and len(vectors[0]) != EMBEDDING_DIM:
            raise ValueError(
                f"Embedding dim mismatch: expected {EMBEDDING_DIM}, got {len(vectors[0])}"
            )
        return vectors
    except Exception as exc:
        logger.warning("Ollama embedding failed, fallback hash embeddings used: %s", exc)
        return _fallback_embed(texts)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Public embedding helper for service-layer semantic scoring.
    """
    normalized = [str(t or "").strip() for t in (texts or []) if str(t or "").strip()]
    if not normalized:
        return []
    return _embed_texts(normalized)


def max_cosine_similarity(text: str, prototypes: list[str]) -> float:
    """
    Compute max cosine similarity between one text and a set of prototype texts.
    Returns 0.0 on failures.
    """
    t = str(text or "").strip()
    ps = [str(p or "").strip() for p in (prototypes or []) if str(p or "").strip()]
    if not t or not ps:
        return 0.0
    vecs = embed_texts([t] + ps)
    if len(vecs) < 2:
        return 0.0
    base = vecs[0]
    best = -1.0
    for v in vecs[1:]:
        num = sum(a * b for a, b in zip(base, v))
        den1 = math.sqrt(sum(a * a for a in base))
        den2 = math.sqrt(sum(b * b for b in v))
        if den1 <= 0 or den2 <= 0:
            continue
        sim = num / (den1 * den2)
        if sim > best:
            best = sim
    return max(0.0, float(best if best > 0 else 0.0))


def _fallback_embed(texts: list[str]) -> list[list[float]]:
    dim = EMBEDDING_DIM
    result = []
    for text in texts:
        vec = [0.0] * dim
        for i, ch in enumerate(text[:dim]):
            vec[i] = ord(ch) / 65535.0
        norm = sum(v * v for v in vec) ** 0.5
        if norm > 0:
            vec = [v / norm for v in vec]
        result.append(vec)
    return result


def _safe_metadata(meta: dict | None) -> dict:
    if not isinstance(meta, dict):
        return {}
    cleaned = {}
    for k, v in meta.items():
        if isinstance(v, (str, int, float, bool)) or v is None:
            cleaned[str(k)] = v
        else:
            cleaned[str(k)] = str(v)
    return cleaned


def add_documents(chunks: list[str], metadatas: list[dict] | None = None, ids: list[str] | None = None) -> int:
    if not chunks:
        return 0
    try:
        col = _ensure_collection()
        metas = metadatas or [{} for _ in chunks]
        if len(metas) != len(chunks):
            metas = (metas + [{} for _ in chunks])[: len(chunks)]
        embeddings = _embed_texts(chunks)
        if len(embeddings) != len(chunks):
            logger.error("Embedding count mismatch: %d texts vs %d embeddings", len(chunks), len(embeddings))
            return 0

        source_files = []
        metadata_json_list = []
        for meta in metas:
            m = _safe_metadata(meta)
            source_files.append(str(m.get("source_file", ""))[:512])
            metadata_json_list.append(json.dumps(m, ensure_ascii=False)[:65535])

        data = [source_files, [c[:65535] for c in chunks], metadata_json_list, embeddings]
        col.insert(data)
        col.flush()
        return len(chunks)
    except Exception as exc:
        logger.error("Milvus add_documents failed: %s", exc)
        return 0


def similarity_search(query: str, k: int = 3) -> list[dict]:
    try:
        col = _ensure_collection()
        if col.num_entities == 0:
            return []
        query_embedding = _embed_texts([query])
        if not query_embedding:
            return []
        results = col.search(
            data=query_embedding,
            anns_field="embedding",
            param={"metric_type": MILVUS_METRIC_TYPE, "params": {"nprobe": 16}},
            limit=max(1, k),
            output_fields=["source_file", "content", "metadata_json"],
        )
        docs: list[dict] = []
        for hit in (results[0] if results else []):
            entity = hit.entity
            meta_raw = entity.get("metadata_json") if entity else "{}"
            try:
                meta = json.loads(meta_raw or "{}")
            except Exception:
                meta = {}
            source = (entity.get("source_file") if entity else "") or meta.get("source_file", "")
            if source:
                meta["source_file"] = source
            docs.append(
                {
                    "content": (entity.get("content") if entity else "") or "",
                    "metadata": meta,
                    "distance": float(hit.distance),
                }
            )
        return docs
    except Exception as exc:
        logger.error("Similarity search failed: %s", exc)
        return []


def add_news_documents(items: list[dict]) -> int:
    """
    Add industry-news vectors into dedicated collection `carbon_ai_news`.
    Each item should include: source_file,title,summary,tags,source_url,published_at,(optional)metadata.
    """
    if not items:
        return 0
    try:
        col = _ensure_news_collection()
        chunks: list[str] = []
        metas: list[dict] = []
        for it in items:
            title = str(it.get("title", "")).strip()[:512]
            summary = str(it.get("summary", "")).strip()[:65535]
            tags_value = it.get("tags", [])
            if isinstance(tags_value, list):
                tags_text = " ".join(str(x) for x in tags_value if x).strip()
            else:
                tags_text = str(tags_value or "").strip()
            source_file = str(it.get("source_file", "")).strip()[:512]
            source_url = str(it.get("source_url", "")).strip()[:1024]
            published_at = str(it.get("published_at", "")).strip()[:64]
            metadata = _safe_metadata(it.get("metadata") if isinstance(it.get("metadata"), dict) else {})
            metadata.setdefault("type", "industry_news")
            metadata.setdefault("source_file", source_file)
            metadata.setdefault("title", title)
            metadata.setdefault("summary", summary[:1000])
            metadata.setdefault("source_url", source_url)
            metadata.setdefault("published_at", published_at)
            metadata.setdefault("tags", tags_value if isinstance(tags_value, list) else ([tags_text] if tags_text else []))
            chunks.append(f"{title}\n{summary}\n{tags_text}".strip())
            metas.append(metadata)

        embeddings = _embed_texts(chunks)
        if len(embeddings) != len(chunks):
            logger.error("News embedding count mismatch: %d texts vs %d embeddings", len(chunks), len(embeddings))
            return 0

        source_files = []
        titles = []
        summaries = []
        tags_list = []
        source_urls = []
        published_list = []
        metadata_json_list = []
        for i, m in enumerate(metas):
            source_files.append(str(m.get("source_file", ""))[:512])
            titles.append(str(m.get("title", ""))[:512])
            summaries.append(str(items[i].get("summary", ""))[:65535])
            tv = items[i].get("tags", [])
            if isinstance(tv, list):
                tags_list.append(json.dumps(tv, ensure_ascii=False)[:2048])
            else:
                tags_list.append(str(tv or "")[:2048])
            source_urls.append(str(items[i].get("source_url", ""))[:1024])
            published_list.append(str(items[i].get("published_at", ""))[:64])
            metadata_json_list.append(json.dumps(m, ensure_ascii=False)[:65535])

        data = [source_files, titles, summaries, tags_list, source_urls, published_list, metadata_json_list, embeddings]
        col.insert(data)
        col.flush()
        return len(items)
    except Exception as exc:
        logger.error("Milvus add_news_documents failed: %s", exc)
        return 0


def similarity_search_news(query: str, k: int = 3) -> list[dict]:
    try:
        col = _ensure_news_collection()
        if col.num_entities == 0:
            return []
        query_embedding = _embed_texts([query])
        if not query_embedding:
            return []
        results = col.search(
            data=query_embedding,
            anns_field="embedding",
            param={"metric_type": MILVUS_METRIC_TYPE, "params": {"nprobe": 16}},
            limit=max(1, k),
            output_fields=["source_file", "title", "summary", "tags", "source_url", "published_at", "metadata_json"],
        )
        docs: list[dict] = []
        for hit in (results[0] if results else []):
            entity = hit.entity
            meta_raw = entity.get("metadata_json") if entity else "{}"
            try:
                meta = json.loads(meta_raw or "{}")
            except Exception:
                meta = {}
            content = f"{(entity.get('title') if entity else '') or ''}\n{(entity.get('summary') if entity else '') or ''}".strip()
            if entity:
                meta.setdefault("source_file", entity.get("source_file") or "")
                meta.setdefault("title", entity.get("title") or "")
                meta.setdefault("summary", entity.get("summary") or "")
                meta.setdefault("tags", entity.get("tags") or "")
                meta.setdefault("source_url", entity.get("source_url") or "")
                meta.setdefault("published_at", entity.get("published_at") or "")
            meta.setdefault("type", "industry_news")
            docs.append({"content": content, "metadata": meta, "distance": float(hit.distance)})
        return docs
    except Exception as exc:
        logger.error("News similarity search failed: %s", exc)
        return []


def similarity_search_all(query: str, k: int = 3) -> list[dict]:
    """
    Query both knowledge and news collections, merge by distance asc.
    """
    know_hits = similarity_search(query, k=max(1, k))
    news_hits = similarity_search_news(query, k=max(1, k))
    merged = know_hits + news_hits
    merged.sort(key=lambda x: float(x.get("distance", 1e9)))
    return merged[: max(1, k)]


def delete_by_source(source_file: str) -> int:
    if not source_file:
        return 0


def delete_news_by_source(source_file: str) -> int:
    if not source_file:
        return 0
    try:
        col = _ensure_news_collection()
        escaped = source_file.replace("\\", "\\\\").replace('"', '\\"')
        expr = f'source_file == "{escaped}"'
        rows = col.query(expr=expr, output_fields=["id"])
        ids = [r.get("id") for r in rows if r.get("id") is not None]
        if ids:
            col.delete(expr=f"id in {ids}")
            col.flush()
        return len(ids)
    except Exception as exc:
        logger.error("Delete news by source failed: %s", exc)
        return 0
    try:
        col = _ensure_collection()
        escaped = source_file.replace("\\", "\\\\").replace('"', '\\"')
        expr = f'source_file == "{escaped}"'
        rows = col.query(expr=expr, output_fields=["id"])
        ids = [r.get("id") for r in rows if r.get("id") is not None]
        if ids:
            col.delete(expr=f"id in {ids}")
            col.flush()
        return len(ids)
    except Exception as exc:
        logger.error("Delete by source failed: %s", exc)
        return 0


def get_collection_count() -> int:
    try:
        col = _ensure_collection()
        return int(col.num_entities)
    except Exception:
        return 0


def get_news_collection_count() -> int:
    try:
        col = _ensure_news_collection()
        return int(col.num_entities)
    except Exception:
        return 0


def reset_news_collection() -> bool:
    """
    Drop and recreate news collection. Useful for one-time full backfill.
    """
    try:
        from pymilvus import utility

        _connect_milvus()
        if utility.has_collection(NEWS_COLLECTION_NAME):
            utility.drop_collection(NEWS_COLLECTION_NAME)
        _ensure_news_collection()
        return True
    except Exception as exc:
        logger.error("Reset news collection failed: %s", exc)
        return False


def check_milvus_health() -> tuple[bool, str]:
    try:
        _ensure_collection()
        return True, "ok"
    except Exception as exc:
        return False, str(exc)
