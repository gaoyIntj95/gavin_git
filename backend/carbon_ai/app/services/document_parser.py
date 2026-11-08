from __future__ import annotations

import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

CHUNK_SIZE = int(os.getenv("DOC_CHUNK_SIZE", "820"))
CHUNK_OVERLAP = int(os.getenv("DOC_CHUNK_OVERLAP", "0"))
CHUNK_OVERLAP_RATIO = float(os.getenv("DOC_CHUNK_OVERLAP_RATIO", "0.18"))
CHUNK_STRATEGY = os.getenv("DOC_CHUNK_STRATEGY", "semantic").strip().lower()
MIN_CHUNK_SIZE = int(os.getenv("DOC_MIN_CHUNK_SIZE", "220"))
PARENT_CHUNK_SIZE = int(os.getenv("DOC_PARENT_CHUNK_SIZE", "1700"))
PARENT_CHUNK_OVERLAP = int(os.getenv("DOC_PARENT_CHUNK_OVERLAP", "160"))
DOC_TYPE_OVERRIDE = os.getenv("DOC_TYPE_OVERRIDE", "").strip().lower()

PAGE_MARKER_PREFIX = "[[[PAGE:"
PAGE_MARKER_SUFFIX = "]]]"


def _extract_text_from_txt(file_path: Path) -> str:
    return file_path.read_text(encoding="utf-8", errors="replace")


def _extract_text_from_pdf(file_path: Path) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(file_path))
        pages: list[str] = []
        for idx, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            marker = f"{PAGE_MARKER_PREFIX}{idx}{PAGE_MARKER_SUFFIX}"
            if text.strip():
                pages.append(f"{marker}\n{text.strip()}")
            else:
                pages.append(marker)
        return "\n\n".join(pages)
    except Exception as exc:
        logger.error("PDF extraction failed: %s", exc)
        return ""


def _extract_text_from_docx(file_path: Path) -> str:
    try:
        from docx import Document

        doc = Document(str(file_path))
        paragraphs = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
        tables_text: list[str] = []
        for table in doc.tables:
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                row_text = " | ".join(cell for cell in cells if cell)
                if row_text:
                    tables_text.append(row_text)
        return "\n\n".join(paragraphs + tables_text)
    except Exception as exc:
        logger.error("DOCX extraction failed: %s", exc)
        return ""


def _extract_text_from_excel(file_path: Path) -> str:
    try:
        import pandas as pd

        suffix = file_path.suffix.lower()
        sheets: list[str] = []
        if suffix == ".csv":
            df = pd.read_csv(file_path)
            sheet_name = file_path.stem or "Sheet1"
            sheets.append(f"=== {sheet_name} ===\n{df.to_string(index=False)}")
        else:
            xls = pd.ExcelFile(file_path)
            for sheet_name in xls.sheet_names:
                df = pd.read_excel(file_path, sheet_name=sheet_name)
                sheets.append(f"=== {sheet_name} ===\n{df.to_string(index=False)}")
        return "\n\n".join(sheets)
    except Exception as exc:
        logger.error("Excel extraction failed: %s", exc)
        return ""


def extract_text(file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    extractors = {
        ".txt": _extract_text_from_txt,
        ".md": _extract_text_from_txt,
        ".pdf": _extract_text_from_pdf,
        ".docx": _extract_text_from_docx,
        ".doc": _extract_text_from_docx,
        ".csv": _extract_text_from_excel,
        ".xls": _extract_text_from_excel,
        ".xlsx": _extract_text_from_excel,
    }
    extractor = extractors.get(suffix)
    if extractor is None:
        raise ValueError(f"Unsupported file type: {suffix}")
    return extractor(file_path)


def _normalize_text(text: str) -> str:
    if not text:
        return ""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t]+\n", "\n", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def _compute_overlap(chunk_size: int, overlap: int) -> int:
    if overlap > 0:
        return max(0, min(overlap, max(chunk_size - 1, 0)))
    ratio = max(0.10, min(CHUNK_OVERLAP_RATIO, 0.25))
    return max(0, min(int(chunk_size * ratio), max(chunk_size - 1, 0)))


def _is_page_marker(line: str) -> bool:
    s = line.strip()
    return s.startswith(PAGE_MARKER_PREFIX) and s.endswith(PAGE_MARKER_SUFFIX)


def _extract_page_number(marker_line: str) -> int | None:
    m = re.search(r"\[\[\[PAGE:(\d+)\]\]\]", marker_line.strip())
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _heading_level(line: str) -> int:
    s = line.strip()
    if not s:
        return 0
    if re.match(r"^#{1,6}\s+", s):
        return min(6, len(s) - len(s.lstrip("#")))
    if re.match(r"^===\s*.+\s*===$", s):
        return 1
    if re.match(r"^第[一二三四五六七八九十百零\d]+章", s):
        return 1
    if re.match(r"^第[一二三四五六七八九十百零\d]+节", s):
        return 2
    if re.match(r"^第[一二三四五六七八九十百零\d]+条", s):
        return 3
    if re.match(r"^\d+(\.\d+){0,4}\s+", s):
        return min(5, s.count(".") + 1)
    if re.match(r"^[（(]?[一二三四五六七八九十\d]+[）)\.、]\s*", s):
        return 4
    return 0


def _is_clause_like(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    patterns = [
        r"^第[一二三四五六七八九十百零\d]+条",
        r"^[（(]?[一二三四五六七八九十\d]+[）)\.、]",
        r"^\d+(\.\d+){1,4}",
        r"^[一二三四五六七八九十]+、",
        r"^[-*•]\s+",
    ]
    return any(re.match(p, s) for p in patterns)


def _infer_doc_type(file_path: Path, text: str) -> str:
    if DOC_TYPE_OVERRIDE:
        return DOC_TYPE_OVERRIDE
    suffix = file_path.suffix.lower()
    if suffix in {".csv", ".xls", ".xlsx"}:
        return "table"

    sample = (file_path.name + "\n" + text[:4000]).lower()
    if any(k in sample for k in ["iso", "gb/t", "标准", "规范", "guideline", "protocol"]):
        return "standard"
    if any(k in sample for k in ["条例", "办法", "通知", "政策", "条款", "实施细则"]):
        return "policy"
    if any(k in sample for k in ["报告", "白皮书", "年度", "分析", "盘查"]):
        return "report"
    return "general"


def _split_sentences(text: str) -> list[str]:
    s = (text or "").strip()
    if not s:
        return []
    parts = re.split(r"(?<=[。！？!?；;])\s+|\n+", s)
    return [p.strip() for p in parts if p and p.strip()]


def _split_table_rows(text: str) -> list[str]:
    rows = [line.strip() for line in text.split("\n") if line.strip()]
    if not rows:
        return []
    if len(rows) <= 2:
        return ["\n".join(rows)]
    header = rows[0]
    groups: list[str] = []
    current: list[str] = [header]
    for row in rows[1:]:
        current.append(row)
        if len(current) >= 8:
            groups.append("\n".join(current).strip())
            current = [header]
    if len(current) > 1:
        groups.append("\n".join(current).strip())
    return groups


def _semantic_units(block: str, doc_type: str) -> list[str]:
    text = (block or "").strip()
    if not text:
        return []
    if doc_type == "table":
        return _split_table_rows(text)

    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if doc_type in {"policy", "standard"}:
        clauses: list[str] = []
        current: list[str] = []
        for line in lines:
            if _is_clause_like(line) and current:
                clauses.append("\n".join(current).strip())
                current = [line]
            else:
                current.append(line)
        if current:
            clauses.append("\n".join(current).strip())
        if clauses:
            return clauses

    return _split_sentences(text)


def _build_sections(text: str, doc_type: str) -> list[dict]:
    lines = text.split("\n")
    sections: list[dict] = []
    current_lines: list[str] = []
    current_start = 0
    current_section = "正文"
    current_level = 0
    current_page: int | None = None

    cursor = 0
    for raw_line in lines:
        line = raw_line.rstrip()
        line_start = cursor
        line_end = cursor + len(raw_line)
        cursor = line_end + 1

        if _is_page_marker(line):
            page_no = _extract_page_number(line)
            if page_no is not None:
                current_page = page_no
            continue

        level = _heading_level(line)
        if level > 0:
            if current_lines:
                text_block = "\n".join(current_lines).strip()
                if text_block:
                    sections.append(
                        {
                            "section": current_section,
                            "toc_level": current_level,
                            "text": text_block,
                            "start": current_start,
                            "end": max(current_start, line_start - 1),
                            "page": current_page,
                        }
                    )
                current_lines = []

            current_section = line.strip()
            current_level = level
            current_start = line_start
            continue

        if not current_lines:
            current_start = line_start
        current_lines.append(line)

        if not line.strip() and doc_type == "table":
            text_block = "\n".join(current_lines).strip()
            if text_block:
                sections.append(
                    {
                        "section": current_section,
                        "toc_level": current_level,
                        "text": text_block,
                        "start": current_start,
                        "end": line_end,
                        "page": current_page,
                    }
                )
            current_lines = []

    if current_lines:
        text_block = "\n".join(current_lines).strip()
        if text_block:
            sections.append(
                {
                    "section": current_section,
                    "toc_level": current_level,
                    "text": text_block,
                    "start": current_start,
                    "end": max(current_start, len(text) - 1),
                    "page": current_page,
                }
            )

    if not sections:
        sections = [
            {
                "section": "正文",
                "toc_level": 0,
                "text": text,
                "start": 0,
                "end": max(0, len(text) - 1),
                "page": None,
            }
        ]
    return sections


def _split_long_text_fixed(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    if not text:
        return []
    safe_overlap = max(0, min(chunk_overlap, max(chunk_size - 1, 0)))
    step = max(1, chunk_size - safe_overlap)
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        start += step
    return chunks


def _pack_units(units: list[str], chunk_size: int, chunk_overlap: int) -> list[str]:
    if not units:
        return []
    chunks: list[str] = []
    current = ""

    def flush_current() -> None:
        nonlocal current
        piece = current.strip()
        if piece:
            chunks.append(piece)
        current = ""

    for unit in units:
        if len(unit) > chunk_size:
            flush_current()
            chunks.extend(_split_long_text_fixed(unit, chunk_size=chunk_size, chunk_overlap=chunk_overlap))
            continue

        if not current:
            current = unit
            continue

        candidate = f"{current}\n{unit}"
        if len(candidate) <= chunk_size:
            current = candidate
        else:
            flush_current()
            current = unit

    flush_current()

    if not chunks or chunk_overlap <= 0:
        return chunks

    overlapped: list[str] = [chunks[0]]
    for idx in range(1, len(chunks)):
        prev_tail = chunks[idx - 1][-chunk_overlap:].strip()
        merged = (prev_tail + "\n" + chunks[idx]).strip() if prev_tail else chunks[idx]
        overlapped.append(merged)
    return overlapped


def _post_merge_short_chunks(chunks: list[str], min_chunk_size: int, max_chunk_size: int) -> list[str]:
    if not chunks:
        return []
    merged: list[str] = []
    for chunk in chunks:
        if merged and len(chunk) < min_chunk_size and (len(merged[-1]) + 1 + len(chunk)) <= max_chunk_size:
            merged[-1] = (merged[-1] + "\n" + chunk).strip()
        else:
            merged.append(chunk)
    return merged


def _build_parent_child_chunks(
    normalized: str,
    sections: list[dict],
    file_path: Path,
    doc_type: str,
    chunk_size: int,
    chunk_overlap: int,
) -> list[dict]:
    parent_units: list[dict] = []
    parent_idx = 0

    for section_idx, sec in enumerate(sections):
        sec_text = (sec.get("text") or "").strip()
        if not sec_text:
            continue

        parent_pieces = _pack_units(
            _semantic_units(sec_text, doc_type=doc_type),
            chunk_size=max(PARENT_CHUNK_SIZE, chunk_size),
            chunk_overlap=max(0, PARENT_CHUNK_OVERLAP),
        )
        if not parent_pieces:
            parent_pieces = [sec_text]

        sec_start = int(sec.get("start") or 0)
        rolling = 0
        for piece_idx, parent_text in enumerate(parent_pieces):
            parent_start = normalized.find(parent_text[:80], sec_start + rolling)
            if parent_start < 0:
                parent_start = sec_start + rolling
            parent_end = parent_start + len(parent_text)
            rolling = max(0, parent_end - sec_start)

            parent_id = f"{file_path.name}:{section_idx}:{piece_idx}:{parent_idx}"
            parent_idx += 1
            parent_units.append(
                {
                    "parent_id": parent_id,
                    "section": sec.get("section") or "正文",
                    "toc_level": int(sec.get("toc_level") or 0),
                    "page": sec.get("page"),
                    "text": parent_text,
                    "start": max(0, parent_start),
                    "end": max(parent_start, parent_end),
                }
            )

    child_chunks: list[dict] = []
    child_idx = 0

    for parent in parent_units:
        parent_text = parent["text"]
        units = _semantic_units(parent_text, doc_type=doc_type)
        packed = _pack_units(units, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        packed = _post_merge_short_chunks(
            packed,
            min_chunk_size=max(80, MIN_CHUNK_SIZE),
            max_chunk_size=int(chunk_size * 1.2),
        )
        if not packed:
            packed = [parent_text]

        rolling = 0
        for local_idx, piece in enumerate(packed):
            if not piece.strip():
                continue
            local_start = parent_text.find(piece[:80], rolling)
            if local_start < 0:
                local_start = rolling
            local_end = local_start + len(piece)
            rolling = max(local_end - chunk_overlap, 0)

            abs_start = int(parent["start"]) + max(0, local_start)
            abs_end = int(parent["start"]) + max(0, local_end)
            child_chunks.append(
                {
                    "text": piece,
                    "metadata": {
                        "section": parent["section"],
                        "page": parent.get("page"),
                        "start_offset": abs_start,
                        "end_offset": abs_end,
                        "doc_type": doc_type,
                        "toc_level": int(parent.get("toc_level") or 0),
                        "parent_chunk_id": parent["parent_id"],
                        "parent_index": child_idx,
                        "child_index": local_idx,
                        "parent_start_offset": int(parent["start"]),
                        "parent_end_offset": int(parent["end"]),
                        "parent_text": parent_text,
                        "chunk_role": "child",
                        "boundary_preserved": True,
                    },
                }
            )
        child_idx += 1

    return child_chunks


def split_text(text: str, chunk_size: int = CHUNK_SIZE, chunk_overlap: int = CHUNK_OVERLAP) -> list[str]:
    normalized = _normalize_text(text)
    if not normalized:
        return []

    chunk_size = max(160, int(chunk_size))
    safe_overlap = _compute_overlap(chunk_size=chunk_size, overlap=int(chunk_overlap))

    if CHUNK_STRATEGY == "fixed":
        return _split_long_text_fixed(normalized, chunk_size=chunk_size, chunk_overlap=safe_overlap)

    # Backward-compatible plain text splitter.
    units = _split_sentences(normalized)
    chunks = _pack_units(units, chunk_size=chunk_size, chunk_overlap=safe_overlap)
    chunks = _post_merge_short_chunks(
        chunks,
        min_chunk_size=max(80, MIN_CHUNK_SIZE),
        max_chunk_size=int(chunk_size * 1.15),
    )
    return [c for c in chunks if c.strip()]


def parse_and_chunk(
    file_path: Path,
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
) -> list[dict]:
    text = extract_text(file_path)
    if not text.strip():
        return []

    normalized = _normalize_text(text)
    if not normalized:
        return []

    chunk_size = max(160, int(chunk_size))
    safe_overlap = _compute_overlap(chunk_size=chunk_size, overlap=int(chunk_overlap))
    doc_type = _infer_doc_type(file_path, normalized)
    sections = _build_sections(normalized, doc_type=doc_type)

    if CHUNK_STRATEGY == "fixed":
        fixed_chunks = _split_long_text_fixed(normalized, chunk_size=chunk_size, chunk_overlap=safe_overlap)
        return [
            {
                "text": c,
                "metadata": {
                    "section": "正文",
                    "page": None,
                    "start_offset": idx * max(1, chunk_size - safe_overlap),
                    "end_offset": idx * max(1, chunk_size - safe_overlap) + len(c),
                    "doc_type": doc_type,
                    "toc_level": 0,
                    "parent_chunk_id": f"{file_path.name}:fixed:{idx}",
                    "parent_index": idx,
                    "child_index": idx,
                    "parent_start_offset": idx * max(1, chunk_size - safe_overlap),
                    "parent_end_offset": idx * max(1, chunk_size - safe_overlap) + len(c),
                    "parent_text": c,
                    "chunk_role": "child",
                    "boundary_preserved": False,
                },
            }
            for idx, c in enumerate(fixed_chunks)
            if c.strip()
        ]

    return _build_parent_child_chunks(
        normalized=normalized,
        sections=sections,
        file_path=file_path,
        doc_type=doc_type,
        chunk_size=chunk_size,
        chunk_overlap=safe_overlap,
    )
