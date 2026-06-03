from typing import Any, Callable

import redis
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.graph import EventType, GraphEvent
from app.models.news import NewsExtraction
from app.utils.logger import get_logger

from .json_repair import extract_and_parse, safe_get_events

logger = get_logger(__name__)

_settings = get_settings()

_REDIS_CURSOR_KEY = "graph:normalizer:last_extraction_id"


class EventNormalizer:
    def __init__(self, db_session_factory: Callable[[], Session]):
        self._session_factory = db_session_factory

    def get_session(self) -> Session:
        return self._session_factory()

    def normalize_extraction_events(self, extraction_id: int) -> list[GraphEvent]:
        session = self.get_session()
        try:
            extraction = session.query(NewsExtraction).filter(NewsExtraction.id == extraction_id).first()
            if extraction is None:
                logger.warning("Extraction %s not found", extraction_id)
                return []

            raw_value = extraction.raw_llm_response
            parsed = extract_and_parse(raw_value)
            event_dicts = safe_get_events(parsed)
            if not event_dicts:
                logger.debug("No events found in extraction %s", extraction_id)
                return []

            created: list[GraphEvent] = []
            for event_dict in event_dicts:
                try:
                    event = self._normalize_single_event(extraction_id, event_dict, session)
                    if event is not None:
                        created.append(event)
                except Exception as exc:
                    logger.error("Failed to normalize event in extraction %s: %s", extraction_id, exc)
                    continue

            session.commit()
            logger.info("Normalized extraction %s: %s events", extraction_id, len(created))
            return created
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _normalize_single_event(self, extraction_id: int, event_dict: dict, db_session: Session | None = None) -> GraphEvent | None:
        event_type_raw = str(event_dict.get("type") or event_dict.get("news_category") or "")
        sentiment = str(event_dict.get("sentiment") or "")
        confidence = event_dict.get("confidence") or event_dict.get("confidence_score")
        importance = event_dict.get("importance") or event_dict.get("importance_score")
        evidence_span = str(event_dict.get("evidence") or event_dict.get("evidence_span") or "")
        event_date = event_dict.get("date") or event_dict.get("event_date")

        if not event_type_raw:
            logger.warning("Skipping event with no type in extraction %s", extraction_id)
            return None

        close_session = False
        if db_session is None:
            db_session = self.get_session()
            close_session = True

        try:
            news_id = self._get_news_id_for_extraction(db_session, extraction_id)
            if news_id is None:
                logger.warning("No news_id found for extraction %s, skipping event", extraction_id)
                return None

            if self._deduplicate_event(db_session, extraction_id, news_id, event_type_raw, evidence_span):
                logger.debug("Skipping duplicate event in extraction %s: %s", extraction_id, event_type_raw)
                return None

            event_type_id = self._match_event_type(event_type_raw, db_session)

            event = GraphEvent(
                extraction_id=extraction_id,
                news_id=news_id,
                event_type_id=event_type_id,
                event_type_raw=event_type_raw,
                sentiment=sentiment,
                confidence=confidence,
                importance=importance,
                evidence_span=evidence_span,
                event_date=event_date,
            )
            db_session.add(event)
            return event
        finally:
            if close_session:
                db_session.close()

    def _match_event_type(self, raw_type: str, db_session: Session | None = None) -> int | None:
        normalized = raw_type.lower().strip().replace(" ", "_")

        close_session = False
        if db_session is None:
            db_session = self.get_session()
            close_session = True

        try:
            row = (
                db_session.query(EventType.id)
                .filter(EventType.event_type == normalized)
                .first()
            )
            if row is not None:
                return row[0]

            parts = normalized.split("_")
            for end in range(len(parts) - 1, 0, -1):
                prefix = "_".join(parts[:end])
                row = (
                    db_session.query(EventType.id)
                    .filter(EventType.event_type == prefix)
                    .first()
                )
                if row is not None:
                    return row[0]

            return None
        finally:
            if close_session:
                db_session.close()

    def _deduplicate_event(self, db_session: Session, extraction_id: int, news_id: int, event_type_raw: str, evidence_span: str) -> bool:
        existing = (
            db_session.query(GraphEvent.id)
            .filter(
                GraphEvent.news_id == news_id,
                GraphEvent.event_type_raw == event_type_raw,
                GraphEvent.evidence_span == evidence_span,
            )
            .first()
        )
        return existing is not None

    def _get_news_id_for_extraction(self, db_session: Session, extraction_id: int) -> int | None:
        row = (
            db_session.query(NewsExtraction.news_id)
            .filter(NewsExtraction.id == extraction_id)
            .first()
        )
        if row is not None:
            return row[0]
        return None

    def normalize_batch(self, limit: int = 100) -> dict:
        stats = {"processed": 0, "events_created": 0, "errors": 0}

        r = self._get_redis()
        last_id = 0
        if r is not None:
            try:
                val = r.get(_REDIS_CURSOR_KEY)
                if val is not None:
                    last_id = int(val)
            except Exception as e:
                logger.warning("Failed to read Redis cursor: %s", e)

        session = self.get_session()
        try:
            already_normalized = (
                session.query(GraphEvent.extraction_id)
                .distinct()
                .subquery()
            )
            while True:
                batch = (
                    session.query(NewsExtraction.id)
                    .filter(NewsExtraction.id > last_id)
                    .filter(NewsExtraction.raw_llm_response.isnot(None))
                    .filter(~NewsExtraction.id.in_(already_normalized))
                    .order_by(NewsExtraction.id)
                    .limit(limit)
                    .all()
                )

                if not batch:
                    break

                for (extraction_id,) in batch:
                    try:
                        events = self.normalize_extraction_events(extraction_id)
                        stats["processed"] += 1
                        stats["events_created"] += len(events)
                    except Exception as e:
                        logger.error("Failed to normalize extraction %s: %s", extraction_id, e)
                        stats["errors"] += 1

                    last_id = extraction_id

                if r is not None:
                    try:
                        r.set(_REDIS_CURSOR_KEY, last_id)
                    except Exception as e:
                        logger.warning("Failed to update Redis cursor: %s", e)

                if len(batch) < limit:
                    break

            logger.info(
                "Batch normalize complete — processed=%s, events_created=%s, errors=%s",
                stats["processed"],
                stats["events_created"],
                stats["errors"],
            )
            return stats
        finally:
            session.close()
            if r is not None:
                try:
                    r.close()
                except Exception:
                    pass

    def _get_redis(self) -> redis.Redis | None:
        try:
            return redis.Redis(
                host=_settings.REDIS_HOST,
                port=_settings.REDIS_PORT,
                password=_settings.REDIS_PASSWORD or None,
                db=_settings.REDIS_DB,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
            )
        except Exception as e:
            logger.warning("Failed to connect to Redis: %s", e)
            return None
