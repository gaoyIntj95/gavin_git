from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)


def _try_parse_json_object(text: str) -> dict | None:
    try:
        data = json.loads(text)
    except Exception:
        return None
    if isinstance(data, dict) and "name" in data and "arguments" in data:
        return data
    return None


def parse_tool_calls(text: str) -> list[dict]:
    content = text or ""
    results: list[dict] = []

    # Format A: fenced block
    # ```tool_call
    # {"name":"...", "arguments": {...}}
    # ```
    fenced_pattern = r"```tool_call\s*(\{.*?\})\s*```"
    for match in re.findall(fenced_pattern, content, re.DOTALL):
        data = _try_parse_json_object(match)
        if data:
            results.append(data)

    # Format B: plain JSON object in text
    if not results:
        for match in re.findall(r"(\{(?:[^{}]|(?:\{[^{}]*\}))*\})", content, re.DOTALL):
            data = _try_parse_json_object(match)
            if data:
                results.append(data)

    # Format C: "tool: xxx" + next-line JSON arguments
    # tool: get_emission_breakdown
    # {"project_id":1,...}
    if not results:
        m = re.search(r"tool\s*:\s*([a-zA-Z0-9_]+)", content, re.IGNORECASE)
        if m:
            tool_name = m.group(1).strip()
            arg_match = re.search(r"(\{[\s\S]*\})", content[m.end() :], re.DOTALL)
            arguments = {}
            if arg_match:
                try:
                    maybe_args = json.loads(arg_match.group(1))
                    if isinstance(maybe_args, dict):
                        arguments = maybe_args
                except Exception:
                    arguments = {}
            results.append({"name": tool_name, "arguments": arguments})

    if not results:
        logger.debug("No tool call parsed from model response")
    return results

