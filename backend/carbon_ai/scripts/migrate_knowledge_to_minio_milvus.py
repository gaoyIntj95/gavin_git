from __future__ import annotations

from pathlib import Path
import sys
import tempfile


def _bootstrap() -> None:
    current = Path(__file__).resolve()
    backend_root = current.parents[1]
    project_root = current.parents[2]
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))


_bootstrap()

from app.core.database import SessionLocal  # noqa: E402
from app.models.knowledge_document import KnowledgeDocument  # noqa: E402
from app.services.document_parser import parse_and_chunk  # noqa: E402
from app.services.object_storage_service import upload_bytes  # noqa: E402
from app.services.rag_service import index_document_chunks  # noqa: E402
from app.services.vector_store import delete_by_source  # noqa: E402


def migrate() -> None:
    with SessionLocal() as db:
        docs = db.query(KnowledgeDocument).all()
        total = len(docs)
        print(f"Found {total} knowledge documents")
        done = 0
        for doc in docs:
            local_path = Path(doc.file_path or "")
            content = b""
            if local_path.exists() and local_path.is_file():
                content = local_path.read_bytes()
            elif doc.object_key and doc.file_url:
                # already migrated, skip upload stage
                pass
            else:
                print(f"[SKIP] id={doc.id} filename={doc.filename} reason=no_local_file")
                continue

            if content and not doc.object_key:
                storage = upload_bytes(
                    content,
                    filename=doc.filename,
                    object_key=f"knowledge/migrated_{doc.id}_{doc.filename}",
                )
                doc.object_key = storage.get("object_key")
                doc.file_url = storage.get("file_url")
                doc.file_size = int(storage.get("size") or len(content))
                doc.file_path = doc.file_url or doc.file_path
                doc.storage_provider = "minio"

            if content:
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    suffix=f".{doc.file_type}" if doc.file_type else ".txt",
                    delete=False,
                ) as tmp:
                    tmp.write(content)
                    tmp_path = Path(tmp.name)
                try:
                    chunks = parse_and_chunk(tmp_path)
                finally:
                    try:
                        tmp_path.unlink(missing_ok=True)
                    except Exception:
                        pass
                delete_by_source(doc.filename)
                count = index_document_chunks(
                    chunks,
                    source_file=doc.filename,
                    extra_metadata={
                        "document_id": doc.id,
                        "object_key": doc.object_key or "",
                        "file_url": doc.file_url or "",
                    },
                )
                doc.chunk_count = count
                doc.status = "completed" if count > 0 else "empty"
            db.add(doc)
            db.commit()
            done += 1
            print(f"[OK] id={doc.id} filename={doc.filename} chunks={doc.chunk_count}")
        print(f"Migration done: {done}/{total}")


if __name__ == "__main__":
    migrate()

