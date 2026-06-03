import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def extract_and_parse(raw_value: Any) -> dict | None:
    if raw_value is None:
        return None
    if isinstance(raw_value, dict):
        return raw_value
    if not isinstance(raw_value, str):
        return None

    stripped = raw_value.strip()
    if not stripped:
        return None

    first_pass = _try_json_parse(stripped)
    if isinstance(first_pass, dict):
        return first_pass

    if isinstance(first_pass, str):
        second = _try_json_parse(first_pass)
        if isinstance(second, dict):
            return second
        repaired = json_repair_attempt(first_pass)
        if repaired is not None:
            return repaired

    repaired = json_repair_attempt(stripped)
    if repaired is not None:
        return repaired

    return None


def _try_json_parse(value: str):
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def json_repair_attempt(broken: str) -> dict | None:
    if not isinstance(broken, str) or not broken.strip():
        return None

    text_val = broken.strip()

    try:
        result = json.loads(text_val)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    repairs = [
        _repair_capitalization,
        _repair_single_quotes_and_keys,
        _repair_trailing_commas,
        _repair_escaped_quotes,
        _repair_truncated_json,
    ]

    for repair_fn in repairs:
        try:
            repaired = repair_fn(text_val)
            if isinstance(repaired, dict):
                return repaired
        except Exception:
            continue

    return None


def _repair_capitalization(text_val: str) -> dict | None:
    fixed = text_val.replace("None", "null").replace("True", "true").replace("False", "false")
    return json.loads(fixed) if fixed != text_val else None


def _repair_single_quotes_and_keys(text_val: str) -> dict | None:
    import re

    result = re.sub(r"(?<!\\)'", '"', text_val)

    result = re.sub(r'(?<!")(\b\w+\b)(?=\s*:)', r'"\1"', result)

    return json.loads(result)


def _repair_trailing_commas(text_val: str) -> dict | None:
    import re

    result = re.sub(r",\s*}", "}", text_val)
    result = re.sub(r",\s*\]", "]", result)
    return json.loads(result)


def _repair_escaped_quotes(text_val: str) -> dict | None:
    import re

    result = re.sub(r'\\(?!["\\/bfnrt]|u[0-9a-fA-F]{4})', r"\\\\", text_val)
    return json.loads(result)


def _repair_truncated_json(text_val: str) -> dict | None:
    result = text_val

    opens = []
    for ch in result:
        if ch in ("{", "["):
            opens.append(ch)
        elif ch == "}" and opens and opens[-1] == "{":
            opens.pop()
        elif ch == "]" and opens and opens[-1] == "[":
            opens.pop()

    for ch in reversed(opens):
        result += "}" if ch == "{" else "]"

    unmatched = result.count('"') % 2
    if unmatched:
        result += '"'

    try:
        return json.loads(result)
    except json.JSONDecodeError:
        pass

    return _repair_trailing_commas(result)


def bulk_repair_extractions(db_session=None, batch_size: int = 100) -> dict:
    from sqlalchemy import text

    from app.database import SessionLocal
    from app.models.news import NewsExtraction

    close_session = False
    if db_session is None:
        db_session = SessionLocal()
        close_session = True

    stats = {"total_attempted": 0, "repaired": 0, "failed": 0}

    try:
        rows = (
            db_session.query(NewsExtraction)
            .filter(
                NewsExtraction.raw_llm_response.isnot(None),
                text("pg_typeof(raw_llm_response) = 'text'"),
            )
            .all()
        )

        stats["total_attempted"] = len(rows)

        for row in rows:
            if isinstance(row.raw_llm_response, dict):
                continue

            parsed = extract_and_parse(row.raw_llm_response)
            if parsed is not None:
                row.raw_llm_response = parsed
                stats["repaired"] += 1
            else:
                stats["failed"] += 1

        db_session.commit()
    except Exception as e:
        logger.error("Bulk repair failed: %s", e)
        db_session.rollback()
    finally:
        if close_session:
            db_session.close()

    return stats


def safe_get_events(raw_value: Any) -> list[dict]:
    parsed = raw_value if isinstance(raw_value, dict) else extract_and_parse(raw_value)
    if parsed is None:
        return []
    events = parsed.get("events")
    if isinstance(events, list):
        return events
    entities = parsed.get("entities")
    if isinstance(entities, list):
        all_events: list[dict] = []
        for entity in entities:
            entity_events = entity.get("events")
            if isinstance(entity_events, list):
                all_events.extend(entity_events)
        return all_events
    return []


def safe_get_entities(raw_value: Any) -> list[dict]:
    parsed = raw_value if isinstance(raw_value, dict) else extract_and_parse(raw_value)
    if parsed is None:
        return []
    entities = parsed.get("entities")
    if isinstance(entities, list):
        return entities
    return []
