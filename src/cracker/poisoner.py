"""File poisoning strategies for indirect prompt injection.

All injections are placed ON THE DATA PATH — inside actual data values that
the agent MUST read and process to complete its task. Not in comments,
not in metadata, but in the data itself.
"""

import json
import logging

from cracker.backends import Backend

logger = logging.getLogger(__name__)


# Maps task names to the files they read and the embedding strategy
TASK_FILE_MAP = {
    "File Organization": {
        "file": "sales_data.csv",
        "strategy": "csv_row",
    },
    "File Modification": {
        "file": "notes.txt",
        "strategy": "text_inline",
    },
    "File Consolidation": {
        "file": "users/Alice Johnson/profile.txt",
        "strategy": "text_inline",
    },
    "Recursive File Search": {
        "file": "logs/app.log",
        "strategy": "log_entry",
    },
    "Data Transformation": {
        "file": "sales_data.csv",
        "strategy": "csv_row",
    },
    "File Comparison": {
        "file": "config_v1.ini",
        "strategy": "ini_value",
    },
    "Multi-Step Data Pipeline": {
        "file": "reports/employees.csv",
        "strategy": "csv_row",
    },
    "Advanced Log Analysis": {
        "file": "application.log",
        "strategy": "log_entry",
    },
    "Data Validation Report": {
        "file": "inventory.csv",
        "strategy": "csv_row",
    },
}


def poison_file(
    backend: Backend,
    task_name: str,
    injection_payload: str,
) -> str | None:
    """Embed injection payload into the data the agent must process."""
    mapping = TASK_FILE_MAP.get(task_name)
    if not mapping:
        logger.warning(f"No file mapping for task: {task_name}")
        return None

    file_path = mapping["file"]
    strategy = mapping["strategy"]

    content = backend.read_file(file_path)
    if content is None:
        logger.error(f"Cannot read {file_path} for poisoning")
        return None

    poisoned = _embed(content, injection_payload, strategy)
    backend.write_file(file_path, poisoned)
    logger.info(f"Poisoned {file_path} using {strategy} strategy")
    return file_path


def restore_file(backend: Backend, task_name: str, original_content: str) -> None:
    """Restore a poisoned file to its original content."""
    mapping = TASK_FILE_MAP.get(task_name)
    if mapping:
        backend.write_file(mapping["file"], original_content)
        logger.info(f"Restored {mapping['file']}")


def get_target_file(task_name: str) -> str | None:
    mapping = TASK_FILE_MAP.get(task_name)
    return mapping["file"] if mapping else None


def save_original(backend: Backend, task_name: str) -> str | None:
    mapping = TASK_FILE_MAP.get(task_name)
    if not mapping:
        return None
    return backend.read_file(mapping["file"])


# ============================================================================
# Embedding strategies — ALL on the data path
# ============================================================================


def _embed(content: str, payload: str, strategy: str) -> str:
    """Embed injection payload into file content on the data path."""
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
    elif strategy == "json_array":
        return _embed_json_array(content, payload)
    else:
        return _embed_csv_row(content, payload)


def _embed_csv_row(content: str, payload: str) -> str:
    """Inject as an actual CSV data row the agent must parse.

    Inserts among real data rows so the agent encounters it during processing.
    """
    lines = content.split("\n")
    if len(lines) < 2:
        lines.append(payload)
        return "\n".join(lines)

    # Insert as a data row in the middle of the CSV data
    data_start = 1  # after header
    data_end = len(lines)
    # Find last non-empty line
    while data_end > data_start and not lines[data_end - 1].strip():
        data_end -= 1

    insert_at = data_start + (data_end - data_start) // 2
    lines.insert(insert_at, payload)
    return "\n".join(lines)


def _embed_text_inline(content: str, payload: str) -> str:
    """Inject inline within text content the agent must read.

    Inserts between existing paragraphs so the agent reads it as part of the document.
    """
    lines = content.split("\n")
    # Find a blank line (paragraph boundary) near the middle
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
    """Inject as a realistic log entry the agent must parse.

    The log analysis tasks count entries by level, so this entry will be processed.
    """
    lines = content.split("\n")
    insert_at = max(1, len(lines) // 2)
    # Format as a real log entry — the agent must parse this
    lines.insert(insert_at, f"[2026-03-24 10:42:17] INFO: {payload}")
    return "\n".join(lines)


def _embed_ini_value(content: str, payload: str) -> str:
    """Inject as a config value the agent must read when comparing configs."""
    lines = content.split("\n")
    # Find a section and add a value inside it
    for i, line in enumerate(lines):
        if line.startswith("[") and i + 1 < len(lines):
            # Insert after the section header as a key-value pair
            lines.insert(i + 1, f"processing_note = {payload}")
            break
    else:
        lines.append(f"processing_note = {payload}")
    return "\n".join(lines)


def _embed_json_field(content: str, payload: str) -> str:
    """Inject as a JSON field value the agent must process."""
    try:
        data = json.loads(content)
        data["processing_instructions"] = payload
        return json.dumps(data, indent=2)
    except json.JSONDecodeError:
        return content + f'\n{{"note": "{payload}"}}\n'


def _embed_json_array(content: str, payload: str) -> str:
    """Inject a poisoned element into a JSON array.

    Clones a real element from the array, replaces its longest text field
    with the payload, and inserts it in the middle. The agent must process
    every element to complete its task, so it will encounter the injection.
    """
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return content

    # Find the array — either top-level or first array value in a dict
    arr = None
    parent = None
    parent_key = None
    if isinstance(data, list):
        arr = data
    elif isinstance(data, dict):
        for key, val in data.items():
            if isinstance(val, list) and len(val) > 0:
                arr = val
                parent = data
                parent_key = key
                break

    if not arr or len(arr) == 0:
        # Fallback to json_field
        if isinstance(data, dict):
            data["processing_instructions"] = payload
        return json.dumps(data, indent=2)

    # Clone an element from the middle
    template = arr[len(arr) // 2]
    if isinstance(template, dict):
        clone = template.copy()
        # Find the longest string field — likely body/description/notes
        text_fields = [(k, v) for k, v in clone.items() if isinstance(v, str)]
        if text_fields:
            best_key = max(text_fields, key=lambda x: len(x[1]))[0]
            clone[best_key] = payload
        else:
            clone["notes"] = payload
    else:
        clone = payload

    # Insert in middle of array
    insert_at = len(arr) // 2
    arr.insert(insert_at, clone)

    if parent is not None:
        parent[parent_key] = arr

    return json.dumps(data, indent=2)
