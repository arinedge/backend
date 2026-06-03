import re
from typing import Any, Callable

import redis
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.config import get_settings
from app.models.graph import CanonicalEntity, EntityAlias, EntityEmbedding, EntityResolutionLog
from app.models.news import NewsExtraction
from app.utils.logger import get_logger

from .json_repair import extract_and_parse, safe_get_entities

logger = get_logger(__name__)

_settings = get_settings()

_TRIGRAM_THRESHOLD = 0.6
_EMBEDDING_THRESHOLD = 0.85
_NEW_ENTITY_CONFIDENCE = 0.6
_TICKER_CONFIDENCE = 0.9
_NORMALIZED_CONFIDENCE = 0.95

_CORPORATE_SUFFIXES = {
    r"\bCorporation\b": "Corp",
    r"\bIncorporated\b": "Inc",
    r"\bLimited\b": "Ltd",
    r"\bTechnologies\b": "Tech",
    r"\bLaboratories\b": "Labs",
    r"\bPharmaceuticals\b": "Pharma",
    r"\bCommunications\b": "Comm",
}

_REDIS_CURSOR_KEY = "graph:resolver:last_extraction_id"


class EntityResolver:
    def __init__(self, db_session_factory: Callable[[], Session]):
        self._session_factory = db_session_factory

    def get_session(self) -> Session:
        return self._session_factory()

    def resolve_extraction_names(self, extraction_id: int) -> list[EntityResolutionLog]:
        session = self.get_session()
        try:
            extraction = session.query(NewsExtraction).filter(NewsExtraction.id == extraction_id).first()
            if extraction is None:
                logger.warning("Extraction %s not found", extraction_id)
                return []

            raw_value = extraction.raw_llm_response
            entity_dicts = safe_get_entities(raw_value)
            if not entity_dicts:
                logger.info("No entities found in extraction %s", extraction_id)
                return []

            resolution_logs: list[EntityResolutionLog] = []
            for entity_dict in entity_dicts:
                name = entity_dict.get("name", "")
                if not name or not isinstance(name, str):
                    name = str(entity_dict.get("entity", ""))
                if not name or not isinstance(name, str):
                    name = str(entity_dict.get("entity_name", ""))
                if not name or not isinstance(name, str):
                    logger.warning("Skipping entity with no name in extraction %s — %s", extraction_id, entity_dict)
                    continue

                try:
                    resolved_id, confidence, method = self.resolve_name(
                        name,
                        entity_type=entity_dict.get("entity_type"),
                        sector=entity_dict.get("sector"),
                    )
                except Exception as exc:
                    logger.error("Failed to resolve name '%s' in extraction %s: %s", name, extraction_id, exc)
                    continue

                log_entry = EntityResolutionLog(
                    extraction_id=extraction_id,
                    raw_name=name,
                    resolved_id=resolved_id,
                    confidence=confidence,
                    method=method,
                )
                session.add(log_entry)
                resolution_logs.append(log_entry)

            session.commit()

            total = len(resolution_logs)
            methods_used = {}
            for rl in resolution_logs:
                methods_used[rl.method] = methods_used.get(rl.method, 0) + 1
            logger.info(
                "Resolved extraction %s: %s entities — methods: %s",
                extraction_id,
                total,
                methods_used,
            )

            return resolution_logs
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def resolve_name(self, name: str, entity_type: str | None = None, sector: str | None = None) -> tuple[int, float, str]:
        stages = [
            (self._stage_exact_match, "exact_match", 0.0),
            (self._stage_normalized_match, "normalized_match", 0.95),
            (self._stage_trigram_match, "trigram_match", _TRIGRAM_THRESHOLD),
            (self._stage_ticker_match, "ticker_match", _TICKER_CONFIDENCE),
            (self._stage_embedding_match, "embedding_match", _EMBEDDING_THRESHOLD),
        ]

        for stage_fn, method_name, min_confidence in stages:
            try:
                entity_id, score = stage_fn(name)
                if entity_id is not None and score >= min_confidence:
                    logger.debug("Resolved '%s' via %s (id=%s, score=%s)", name, method_name, entity_id, score)
                    return entity_id, score, method_name
            except Exception as exc:
                logger.warning("Stage '%s' failed for name '%s': %s", method_name, name, exc)
                continue

        return self._stage_new_entity(name, entity_type=entity_type, sector=sector)

    def _stage_exact_match(self, name: str) -> tuple[int | None, float]:
        session = self.get_session()
        try:
            alias_row = (
                session.query(EntityAlias.canonical_id)
                .filter(EntityAlias.alias == name)
                .first()
            )
            if alias_row is not None:
                return alias_row[0], 1.0

            canonical_row = (
                session.query(CanonicalEntity.id)
                .filter(CanonicalEntity.canonical_name == name)
                .first()
            )
            if canonical_row is not None:
                return canonical_row[0], 1.0

            return None, 0.0
        finally:
            session.close()

    @staticmethod
    def _normalize(s: str) -> str:
        s = s.lower().strip()
        s = re.sub(r"[^\w\s&]", "", s)
        s = re.sub(r"\s+", " ", s)
        return s

    @staticmethod
    def _generate_variations(name: str) -> list[str]:
        variations = [name]

        base = name.strip()
        if base.lower().startswith("the "):
            variations.append(base[4:].strip())

        for pattern, replacement in _CORPORATE_SUFFIXES.items():
            if re.search(pattern, name, re.IGNORECASE):
                variations.append(re.sub(pattern, replacement, name, flags=re.IGNORECASE))

        if " and " in name.lower():
            variations.append(re.sub(r"\band\b", "&", name, flags=re.IGNORECASE))
        if " & " in name:
            variations.append(re.sub(r"\b&\b", "and", name))

        return list(set(variations))

    def _stage_normalized_match(self, name: str) -> tuple[int | None, float]:
        session = self.get_session()
        try:
            norm = self._normalize(name)

            aliases = session.query(EntityAlias).all()

            for alias_row in aliases:
                if self._normalize(alias_row.alias) == norm:
                    return alias_row.canonical_id, _NORMALIZED_CONFIDENCE

            canonicals = session.query(CanonicalEntity).all()
            for canonical_row in canonicals:
                if self._normalize(canonical_row.canonical_name) == norm:
                    return canonical_row.id, _NORMALIZED_CONFIDENCE

            variations = self._generate_variations(name)
            for variant in variations:
                v_norm = self._normalize(variant)
                if v_norm == norm:
                    continue
                for alias_row in aliases:
                    if self._normalize(alias_row.alias) == v_norm:
                        return alias_row.canonical_id, _NORMALIZED_CONFIDENCE
                for canonical_row in canonicals:
                    if self._normalize(canonical_row.canonical_name) == v_norm:
                        return canonical_row.id, _NORMALIZED_CONFIDENCE

            return None, 0.0
        finally:
            session.close()

    def _stage_trigram_match(self, name: str) -> tuple[int | None, float]:
        session = self.get_session()
        try:
            sql = text("""
                SELECT canonical_id, similarity(alias, :name) AS sim
                FROM nse_entity_aliases
                WHERE alias % :name
                ORDER BY sim DESC
                LIMIT 1
            """)
            row = session.execute(sql, {"name": name}).first()
            if row is not None and row.sim >= _TRIGRAM_THRESHOLD:
                return row.canonical_id, float(row.sim)
            return None, 0.0
        finally:
            session.close()

    def _stage_embedding_match(self, name: str) -> tuple[int | None, float]:
        return None, 0.0

    def _stage_ticker_match(self, name: str) -> tuple[int | None, float]:
        if not (1 <= len(name) <= 5 and name.isupper() and name.isalpha()):
            return None, 0.0

        session = self.get_session()
        try:
            row = (
                session.query(CanonicalEntity.id)
                .filter(CanonicalEntity.ticker == name)
                .first()
            )
            if row is not None:
                return row[0], _TICKER_CONFIDENCE
            return None, 0.0
        finally:
            session.close()

    def _stage_new_entity(self, name: str, entity_type: str | None = None, sector: str | None = None) -> tuple[int, float, str]:
        session = self.get_session()
        try:
            entity = CanonicalEntity(
                canonical_name=name,
                entity_type=entity_type or "Unknown",
                sector=sector,
            )
            session.add(entity)
            session.flush()

            alias = EntityAlias(
                canonical_id=entity.id,
                alias=name,
                alias_type="extracted_name",
                confidence=_NEW_ENTITY_CONFIDENCE,
                source="entity_resolver",
            )
            session.add(alias)
            session.commit()

            logger.info("Created new entity '%s' (id=%s)", name, entity.id)
            return entity.id, _NEW_ENTITY_CONFIDENCE, "new_entity"
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _get_or_create_embedding(self, name: str) -> list[float] | None:
        return None

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

    def bulk_resolve_all(self, batch_size: int = 100) -> dict:
        stats = {"processed": 0, "total_entities_resolved": 0, "errors": 0}

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
            while True:
                batch = (
                    session.query(NewsExtraction.id)
                    .filter(NewsExtraction.id > last_id)
                    .filter(NewsExtraction.raw_llm_response.isnot(None))
                    .order_by(NewsExtraction.id)
                    .limit(batch_size)
                    .all()
                )

                if not batch:
                    break

                for (extraction_id,) in batch:
                    try:
                        logs = self.resolve_extraction_names(extraction_id)
                        stats["processed"] += 1
                        stats["total_entities_resolved"] += len(logs)
                    except Exception as e:
                        logger.error("Failed to resolve extraction %s: %s", extraction_id, e)
                        stats["errors"] += 1

                    last_id = extraction_id

                if r is not None:
                    try:
                        r.set(_REDIS_CURSOR_KEY, last_id)
                    except Exception as e:
                        logger.warning("Failed to update Redis cursor: %s", e)

                if len(batch) < batch_size:
                    break

            logger.info(
                "Bulk resolve complete — processed=%s, resolved=%s, errors=%s",
                stats["processed"],
                stats["total_entities_resolved"],
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
