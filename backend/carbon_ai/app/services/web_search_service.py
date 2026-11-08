from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import urllib.parse
import urllib.request

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

WEB_SEARCH_ENABLED = os.getenv("WEB_SEARCH_ENABLED", "false").lower() == "true"
WEB_SEARCH_MAX_RESULTS = int(os.getenv("WEB_SEARCH_MAX_RESULTS", "5"))
WEB_SEARCH_TIMEOUT_SEC = int(os.getenv("WEB_SEARCH_TIMEOUT_SEC", "8"))
WEB_SEARCH_IGNORE_SYSTEM_PROXY = os.getenv("WEB_SEARCH_IGNORE_SYSTEM_PROXY", "true").lower() == "true"


def _normalize_item(title: str, url: str, snippet: str) -> dict:
    return {
        "title": (title or "").strip(),
        "url": (url or "").strip(),
        "snippet": (snippet or "").strip(),
    }


def _search_duckduckgo(query: str, limit: int) -> list[dict]:
    encoded_q = urllib.parse.quote(query)
    api = (
        "https://api.duckduckgo.com/"
        f"?q={encoded_q}&format=json&no_redirect=1&no_html=1&skip_disambig=0"
    )
    req = urllib.request.Request(
        api,
        headers={"User-Agent": "CarbonAI/1.0 (+https://localhost)"},
    )
    opener = (
        urllib.request.build_opener(urllib.request.ProxyHandler({}))
        if WEB_SEARCH_IGNORE_SYSTEM_PROXY
        else urllib.request.build_opener()
    )
    with opener.open(req, timeout=WEB_SEARCH_TIMEOUT_SEC) as resp:
        payload = json.loads(resp.read().decode("utf-8", errors="replace"))

    results: list[dict] = []
    abstract = payload.get("AbstractText", "")
    abstract_url = payload.get("AbstractURL", "")
    heading = payload.get("Heading", "")
    if abstract and abstract_url:
        results.append(_normalize_item(heading or query, abstract_url, abstract))

    def visit_topics(topics: list[dict]) -> None:
        for t in topics:
            if len(results) >= limit:
                return
            if "Topics" in t and isinstance(t["Topics"], list):
                visit_topics(t["Topics"])
                continue
            text = t.get("Text", "")
            first_url = t.get("FirstURL", "")
            if text and first_url:
                title = text.split(" - ")[0][:120]
                results.append(_normalize_item(title, first_url, text))

    related = payload.get("RelatedTopics", [])
    if isinstance(related, list):
        visit_topics(related)

    # deduplicate by URL and trim to limit
    dedup: list[dict] = []
    seen = set()
    for item in results:
        url = item.get("url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        dedup.append(item)
        if len(dedup) >= limit:
            break
    return dedup


def search_web(query: str, max_results: int | None = None) -> list[dict]:
    if not WEB_SEARCH_ENABLED:
        return []
    q = (query or "").strip()
    if not q:
        return []
    limit = max_results or WEB_SEARCH_MAX_RESULTS
    try:
        return _search_duckduckgo(q, limit=limit)
    except Exception as exc:
        logger.warning("Web search failed: %s", exc)
        return []
