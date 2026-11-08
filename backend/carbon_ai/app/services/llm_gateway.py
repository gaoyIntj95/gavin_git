from __future__ import annotations

import json
import logging
import os
import time
import threading
from pathlib import Path
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
            # Use project .env as source of truth for this app process.
            os.environ[key] = value
    except Exception as exc:
        logger.warning("Failed to load env file %s: %s", path, exc)


def _load_local_env_files() -> None:
    # app/services/llm_gateway.py -> parents[2] is backend root: D:/.../carbon_ai
    current = Path(__file__).resolve()
    backend_root = current.parents[2]
    project_root = current.parents[3]
    for candidate in (backend_root / ".env", project_root / ".env"):
        _load_env_file(candidate)


_load_local_env_files()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "qwen2.5:7b")
OLLAMA_TIMEOUT_SEC = int(os.getenv("OLLAMA_TIMEOUT_SEC", "40"))
OLLAMA_AGENT_TIMEOUT_SEC = int(
    os.getenv("OLLAMA_AGENT_TIMEOUT_SEC", str(min(OLLAMA_TIMEOUT_SEC, 45)))
)

REMOTE_LLM_PROVIDER = os.getenv("REMOTE_LLM_PROVIDER", "openai_compatible").strip().lower()
REMOTE_LLM_ENABLED = os.getenv("REMOTE_LLM_ENABLED", "false").lower() == "true"
REMOTE_LLM_BASE_URL = os.getenv("REMOTE_LLM_BASE_URL", "").strip()
REMOTE_LLM_API_KEY = os.getenv("REMOTE_LLM_API_KEY", "").strip()
REMOTE_LLM_MODEL = os.getenv("REMOTE_LLM_MODEL", "").strip()
REMOTE_LLM_TIMEOUT_SEC = int(os.getenv("REMOTE_LLM_TIMEOUT_SEC", "25"))
REMOTE_LLM_RETRY_COUNT = int(os.getenv("REMOTE_LLM_RETRY_COUNT", "1"))
REMOTE_LLM_FAILURE_THRESHOLD = int(os.getenv("REMOTE_LLM_FAILURE_THRESHOLD", "2"))
REMOTE_LLM_COOLDOWN_SEC = int(os.getenv("REMOTE_LLM_COOLDOWN_SEC", "300"))
REMOTE_LLM_MAX_TOKENS = int(os.getenv("REMOTE_LLM_MAX_TOKENS", "512"))
REMOTE_LLM_TEMPERATURE = float(os.getenv("REMOTE_LLM_TEMPERATURE", "0.2"))

REMOTE_FOR_GENERAL = os.getenv("REMOTE_LLM_FOR_GENERAL", "true").lower() == "true"
REMOTE_FOR_RAG = os.getenv("REMOTE_LLM_FOR_RAG", "true").lower() == "true"
REMOTE_FOR_WEB = os.getenv("REMOTE_LLM_FOR_WEB", "true").lower() == "true"
REMOTE_FOR_AGENT = os.getenv("REMOTE_LLM_FOR_AGENT", "false").lower() == "true"
REMOTE_FOR_SENSITIVE = os.getenv("REMOTE_LLM_FOR_SENSITIVE", "false").lower() == "true"

REMOTE_FALLBACK_TO_LOCAL = os.getenv("REMOTE_LLM_FALLBACK_TO_LOCAL", "true").lower() == "true"
REMOTE_IGNORE_SYSTEM_PROXY = os.getenv("REMOTE_LLM_IGNORE_SYSTEM_PROXY", "true").lower() == "true"

_remote_state_lock = threading.Lock()
_remote_failures = 0
_remote_cooldown_until = 0.0


def _remote_ready() -> bool:
    return (
        REMOTE_LLM_ENABLED
        and bool(_remote_base_url())
        and bool(REMOTE_LLM_API_KEY)
        and bool(_remote_model())
    )


def _remote_base_url() -> str:
    if REMOTE_LLM_BASE_URL:
        return REMOTE_LLM_BASE_URL
    if REMOTE_LLM_PROVIDER == "deepseek":
        return "https://api.deepseek.com/v1"
    if REMOTE_LLM_PROVIDER == "zhipu":
        return "https://open.bigmodel.cn/api/paas/v4"
    return ""


def _remote_model() -> str:
    if REMOTE_LLM_MODEL:
        return REMOTE_LLM_MODEL
    if REMOTE_LLM_PROVIDER == "deepseek":
        return "deepseek-chat"
    if REMOTE_LLM_PROVIDER == "zhipu":
        return "glm-4-flash"
    return ""


def _mask_secret(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if len(text) <= 8:
        return "*" * len(text)
    return f"{text[:4]}...{text[-4:]}"


def get_runtime_config() -> dict:
    return {
        "ollama": {
            "base_url": OLLAMA_BASE_URL,
            "model": OLLAMA_MODEL,
            "timeout_sec": OLLAMA_TIMEOUT_SEC,
            "agent_timeout_sec": OLLAMA_AGENT_TIMEOUT_SEC,
        },
        "remote_llm": {
            "provider": REMOTE_LLM_PROVIDER,
            "enabled": REMOTE_LLM_ENABLED,
            "base_url": _remote_base_url(),
            "model": _remote_model(),
            "api_key_masked": _mask_secret(REMOTE_LLM_API_KEY),
            "timeout_sec": REMOTE_LLM_TIMEOUT_SEC,
            "retry_count": REMOTE_LLM_RETRY_COUNT,
            "failure_threshold": REMOTE_LLM_FAILURE_THRESHOLD,
            "cooldown_sec": REMOTE_LLM_COOLDOWN_SEC,
            "max_tokens": REMOTE_LLM_MAX_TOKENS,
            "temperature": REMOTE_LLM_TEMPERATURE,
            "ignore_system_proxy": REMOTE_IGNORE_SYSTEM_PROXY,
            "ready": _remote_ready(),
            "route_general": REMOTE_FOR_GENERAL,
            "route_rag": REMOTE_FOR_RAG,
            "route_web": REMOTE_FOR_WEB,
            "route_agent": REMOTE_FOR_AGENT,
            "route_sensitive": REMOTE_FOR_SENSITIVE,
            "fallback_to_local": REMOTE_FALLBACK_TO_LOCAL,
        },
    }


def _should_use_remote(task: str, contains_sensitive: bool) -> bool:
    if not _remote_ready():
        return False
    if contains_sensitive and not REMOTE_FOR_SENSITIVE:
        return False
    if task == "agent":
        return REMOTE_FOR_AGENT
    if task == "rag":
        return REMOTE_FOR_RAG
    if task == "web":
        return REMOTE_FOR_WEB
    return REMOTE_FOR_GENERAL


def _remote_in_cooldown() -> bool:
    with _remote_state_lock:
        return time.time() < _remote_cooldown_until


def _mark_remote_success() -> None:
    global _remote_failures, _remote_cooldown_until
    with _remote_state_lock:
        _remote_failures = 0
        _remote_cooldown_until = 0.0


def _mark_remote_failure() -> None:
    global _remote_failures, _remote_cooldown_until
    with _remote_state_lock:
        _remote_failures += 1
        if _remote_failures >= max(1, REMOTE_LLM_FAILURE_THRESHOLD):
            _remote_cooldown_until = time.time() + max(1, REMOTE_LLM_COOLDOWN_SEC)
            logger.warning(
                "Remote LLM enters cooldown for %ss after %s failures",
                REMOTE_LLM_COOLDOWN_SEC,
                _remote_failures,
            )


def _call_ollama(
    messages: list[dict[str, str]],
    timeout_sec: int | None = None,
) -> str:
    import ollama

    client = ollama.Client(
        host=OLLAMA_BASE_URL,
        timeout=timeout_sec if timeout_sec is not None else OLLAMA_TIMEOUT_SEC,
    )
    response = client.chat(model=OLLAMA_MODEL, messages=messages)
    return response.get("message", {}).get("content", "")


def _call_remote(messages: list[dict[str, str]]) -> str:
    base = _remote_base_url().rstrip("/")
    model = _remote_model()
    # OpenAI-compatible endpoint (also works for Zhipu v4 compatibility route)
    url = f"{base}/chat/completions"
    payload = json.dumps(
        {
            "model": model,
            "messages": messages,
            "temperature": REMOTE_LLM_TEMPERATURE,
            "max_tokens": REMOTE_LLM_MAX_TOKENS,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {REMOTE_LLM_API_KEY}",
        },
    )
    opener = (
        urllib.request.build_opener(urllib.request.ProxyHandler({}))
        if REMOTE_IGNORE_SYSTEM_PROXY
        else urllib.request.build_opener()
    )
    total_attempts = max(1, REMOTE_LLM_RETRY_COUNT + 1)
    last_exc: Exception | None = None
    for attempt in range(1, total_attempts + 1):
        try:
            with opener.open(req, timeout=REMOTE_LLM_TIMEOUT_SEC) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            choices = data.get("choices") or []
            if not choices:
                return ""
            message = ((choices[0] or {}).get("message") or {})
            content = (message.get("content") or "").strip()
            if content:
                return content
            # Some models (e.g. vision/reasoning variants) may place output in reasoning fields.
            reasoning = (message.get("reasoning_content") or message.get("reasoning") or "").strip()
            if reasoning:
                return reasoning
            return ""
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "Remote LLM attempt %s/%s failed: %s",
                attempt,
                total_attempts,
                exc,
            )
            if attempt < total_attempts:
                time.sleep(0.35)
    assert last_exc is not None
    raise last_exc


def chat_messages(
    messages: list[dict[str, str]],
    task: str = "general",
    contains_sensitive: bool = False,
) -> str:
    use_remote = _should_use_remote(task=task, contains_sensitive=contains_sensitive)
    if use_remote and _remote_in_cooldown():
        logger.warning("Remote LLM is in cooldown, skip remote and fallback to local. task=%s", task)
        use_remote = False
    if use_remote:
        try:
            out = _call_remote(messages)
            _mark_remote_success()
            return out
        except Exception as exc:
            _mark_remote_failure()
            logger.warning("Remote LLM failed, task=%s: %s", task, exc)
            if not REMOTE_FALLBACK_TO_LOCAL:
                raise
    local_timeout = OLLAMA_TIMEOUT_SEC
    if task == "agent":
        local_timeout = max(5, OLLAMA_AGENT_TIMEOUT_SEC)
    return _call_ollama(messages, timeout_sec=local_timeout)


def check_remote_llm_health() -> tuple[bool, str]:
    if not _remote_ready():
        return False, "REMOTE_LLM 未配置完整或未启用"
    try:
        _call_remote([{"role": "user", "content": "ping"}])
        return True, "ok"
    except Exception as exc:
        return False, str(exc)


def check_ollama_health() -> tuple[bool, str]:
    try:
        # Minimal probe
        _ = _call_ollama([{"role": "user", "content": "ping"}])
        return True, "ok"
    except Exception as exc:
        return False, str(exc)
