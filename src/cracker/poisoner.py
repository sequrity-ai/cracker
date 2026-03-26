"""File embedding strategies for indirect prompt injection.

Used by the adaptive attack mode to inject attacker-generated text
into workspace files the agent reads. All injections are placed
on the data path — inside data the agent must process.
"""

import json
import logging

logger = logging.getLogger(__name__)


def _embed(content: str, payload: str, strategy: str) -> str:
    """Embed injection payload into file content using the specified strategy."""
    if strategy == "csv_row":
        return _embed_csv_row(content, payload)
    elif strategy == "text_inline":
        return _embed_text_inline(content, payload)
    elif strategy == "log_entry":
        return _embed_log_entry(content, payload)
    elif strategy == "ini_value":
        return _embed_ini_value(content, payload)
    elif strategy == "json_field":
        return _embed_json_field(content, payload)
    elif strategy == "code_comment":
        return _embed_code_comment(content, payload)
    else:
        return _embed_text_inline(content, payload)


def _embed_csv_row(content: str, payload: str) -> str:
    """Inject as a data row in the middle of CSV data."""
    lines = content.split("\n")
    if len(lines) < 2:
        lines.append(payload)
        return "\n".join(lines)
    data_start = 1
    data_end = len(lines)
    while data_end > data_start and not lines[data_end - 1].strip():
        data_end -= 1
    insert_at = data_start + (data_end - data_start) // 2
    lines.insert(insert_at, payload)
    return "\n".join(lines)


def _embed_text_inline(content: str, payload: str) -> str:
    """Inject between paragraphs in text content."""
    lines = content.split("\n")
    mid = len(lines) // 2
    best = mid
    for i in range(mid, len(lines)):
        if not lines[i].strip():
            best = i
            break
    for i in range(mid, 0, -1):
        if not lines[i].strip():
            if abs(i - mid) < abs(best - mid):
                best = i
            break
    lines.insert(best + 1, payload)
    return "\n".join(lines)


def _embed_log_entry(content: str, payload: str) -> str:
    """Inject as a log entry."""
    lines = content.split("\n")
    insert_at = max(1, len(lines) // 2)
    lines.insert(insert_at, f"[2026-03-24 10:42:17] INFO: {payload}")
    return "\n".join(lines)


def _embed_ini_value(content: str, payload: str) -> str:
    """Inject as a config value."""
    lines = content.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("[") and i + 1 < len(lines):
            lines.insert(i + 1, f"processing_note = {payload}")
            break
    else:
        lines.append(f"processing_note = {payload}")
    return "\n".join(lines)


def _embed_json_field(content: str, payload: str) -> str:
    """Inject as a JSON field value."""
    try:
        data = json.loads(content)
        data["processing_instructions"] = payload
        return json.dumps(data, indent=2)
    except json.JSONDecodeError:
        return content + f'\n{{"note": "{payload}"}}\n'


def _embed_code_comment(content: str, payload: str) -> str:
    """Inject as a code comment before a function definition."""
    lines = content.split("\n")
    insert_at = max(1, len(lines) // 3)
    for i, line in enumerate(lines):
        if line.startswith("def ") or line.startswith("class "):
            insert_at = i
            break
    lines.insert(insert_at, f"# {payload}")
    return "\n".join(lines)
