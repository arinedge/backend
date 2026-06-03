import random
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.graph import (
    CanonicalEntity,
    EntityResolutionLog,
    GraphEvent,
    GraphMetric,
    Relationship,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

_SENTIMENT_MAP: dict[str, float] = {
    "positive": 1.0,
    "negative": -1.0,
    "neutral": 0.0,
}


class GraphAnalytics:
    def __init__(self, db_session_factory: Callable[[], Session]):
        self._session_factory = db_session_factory

    def get_session(self) -> Session:
        return self._session_factory()

    def compute_all_metrics(self, entity_ids: list[int] | None = None) -> dict:
        session = self.get_session()
        try:
            if entity_ids is None:
                rows = session.query(CanonicalEntity.id).all()
                entity_ids = [row[0] for row in rows]

            stats: dict[str, int] = {
                "entities_computed": 0,
                "with_relationships": 0,
                "errors": 0,
            }

            pagerank_scores = self._compute_pagerank(session)
            degree_scores = self._compute_degree_centrality(session)
            betweenness_scores = self._compute_betweenness_centrality(session)

            rel_entity_ids: set[int] = set()
            for rel in session.query(Relationship.source_entity, Relationship.target_entity).all():
                rel_entity_ids.add(rel.source_entity)
                rel_entity_ids.add(rel.target_entity)

            for entity_id in entity_ids:
                try:
                    velocity = self._compute_velocity(entity_id, session)
                    sentiment = self._compute_sentiment(entity_id, session)

                    existing = (
                        session.query(GraphMetric)
                        .filter(GraphMetric.entity_id == entity_id)
                        .first()
                    )

                    if existing is not None:
                        existing.pagerank = pagerank_scores.get(entity_id, 0.0)
                        existing.degree_centrality = degree_scores.get(entity_id, 0.0)
                        existing.betweenness = betweenness_scores.get(entity_id, 0.0)
                        existing.mention_velocity = velocity["velocity"]
                        existing.sentiment_score = sentiment["avg_sentiment"]
                        existing.sentiment_velocity = sentiment["sentiment_velocity"]
                        existing.computed_at = func.now()
                    else:
                        gm = GraphMetric(
                            entity_id=entity_id,
                            pagerank=pagerank_scores.get(entity_id, 0.0),
                            degree_centrality=degree_scores.get(entity_id, 0.0),
                            betweenness=betweenness_scores.get(entity_id, 0.0),
                            mention_velocity=velocity["velocity"],
                            sentiment_score=sentiment["avg_sentiment"],
                            sentiment_velocity=sentiment["sentiment_velocity"],
                        )
                        session.add(gm)

                    stats["entities_computed"] += 1
                    if entity_id in rel_entity_ids:
                        stats["with_relationships"] += 1

                except Exception as e:
                    logger.error(
                        "Failed to compute metrics for entity %s: %s", entity_id, e
                    )
                    stats["errors"] += 1

            session.commit()
            logger.info(
                "compute_all_metrics complete — entities=%s, with_rels=%s, errors=%s",
                stats["entities_computed"],
                stats["with_relationships"],
                stats["errors"],
            )
            return stats
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _compute_pagerank(
        self,
        db_session: Session,
        damping: float = 0.85,
        max_iter: int = 100,
        tol: float = 1e-6,
    ) -> dict[int, float]:
        relationships = db_session.query(Relationship).all()

        out_edges: dict[int, list[int]] = defaultdict(list)
        in_edges: dict[int, list[int]] = defaultdict(list)
        all_nodes: set[int] = set()

        for rel in relationships:
            out_edges[rel.source_entity].append(rel.target_entity)
            in_edges[rel.target_entity].append(rel.source_entity)
            all_nodes.add(rel.source_entity)
            all_nodes.add(rel.target_entity)

        if not all_nodes:
            return {}

        n = len(all_nodes)
        node_list = list(all_nodes)
        node_index = {node: i for i, node in enumerate(node_list)}

        rank = [1.0 / n] * n
        dangling_rank = 1.0 / n

        for _ in range(max_iter):
            new_rank = [0.0] * n
            dangling_sum = 0.0

            for i, node in enumerate(node_list):
                if not out_edges[node]:
                    dangling_sum += rank[i]

            for i, node in enumerate(node_list):
                rank_sum = 0.0
                for incoming in in_edges[node]:
                    j = node_index[incoming]
                    deg = len(out_edges[incoming])
                    if deg > 0:
                        rank_sum += rank[j] / deg

                new_rank[i] = (1 - damping) / n + damping * (
                    rank_sum + dangling_sum * dangling_rank
                )

            diff = sum(abs(new_rank[i] - rank[i]) for i in range(n))
            rank = new_rank
            if diff < tol:
                break

        return {node_list[i]: rank[i] for i in range(n)}

    def _compute_degree_centrality(self, db_session: Session) -> dict[int, float]:
        total_entities = db_session.query(CanonicalEntity).count()
        if total_entities <= 1:
            return {}

        denom = total_entities - 1

        unique_neighbors: dict[int, set[int]] = defaultdict(set)
        for rel in db_session.query(Relationship).all():
            unique_neighbors[rel.source_entity].add(rel.target_entity)
            unique_neighbors[rel.target_entity].add(rel.source_entity)

        return {
            entity_id: len(neighbors) / denom
            for entity_id, neighbors in unique_neighbors.items()
        }

    def _compute_betweenness_centrality(
        self, db_session: Session, sample_size: int = 100
    ) -> dict[int, float]:
        relationships = db_session.query(Relationship).all()

        adj: dict[int, set[int]] = defaultdict(set)
        all_nodes: set[int] = set()

        for rel in relationships:
            adj[rel.source_entity].add(rel.target_entity)
            adj[rel.target_entity].add(rel.source_entity)
            all_nodes.add(rel.source_entity)
            all_nodes.add(rel.target_entity)

        if not all_nodes:
            return {}

        nodes = list(all_nodes)
        n = len(nodes)

        if n > 500 and sample_size < n:
            sample = random.sample(nodes, sample_size)
        else:
            sample = nodes

        betweenness: dict[int, float] = defaultdict(float)

        for s in sample:
            stack: list[int] = []
            pred: dict[int, list[int]] = defaultdict(list)
            sigma: dict[int, int] = defaultdict(int)
            sigma[s] = 1
            dist: dict[int, float] = {}
            dist[s] = 0.0
            queue: deque[tuple[int, float]] = deque()
            queue.append((s, 0.0))

            while queue:
                v, d = queue.popleft()
                stack.append(v)
                for w in adj.get(v, set()):
                    if w not in dist:
                        dist[w] = d + 1.0
                        queue.append((w, d + 1.0))
                    if dist[w] == d + 1.0:
                        sigma[w] += sigma[v]
                        pred[w].append(v)

            delta: dict[int, float] = defaultdict(float)
            while stack:
                w = stack.pop()
                for v in pred[w]:
                    if sigma[w] > 0:
                        delta[v] += (sigma[v] / sigma[w]) * (1.0 + delta[w])
                if w != s:
                    betweenness[w] += delta[w]

        if sample is not nodes:
            scale = n / len(sample)
            for k in betweenness:
                betweenness[k] *= scale

        denom = max((n - 1) * (n - 2), 1)
        return {node_id: score / denom for node_id, score in betweenness.items()}

    def _compute_velocity(
        self, entity_id: int, db_session: Session
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        recent_start = now - timedelta(days=7)
        previous_start = now - timedelta(days=14)

        recent_count = (
            db_session.query(func.count(GraphEvent.id))
            .join(
                EntityResolutionLog,
                GraphEvent.extraction_id == EntityResolutionLog.extraction_id,
            )
            .filter(
                EntityResolutionLog.resolved_id == entity_id,
                GraphEvent.article_date >= recent_start,
            )
            .scalar()
        ) or 0

        previous_count = (
            db_session.query(func.count(GraphEvent.id))
            .join(
                EntityResolutionLog,
                GraphEvent.extraction_id == EntityResolutionLog.extraction_id,
            )
            .filter(
                EntityResolutionLog.resolved_id == entity_id,
                GraphEvent.article_date >= previous_start,
                GraphEvent.article_date < recent_start,
            )
            .scalar()
        ) or 0

        velocity = float(recent_count - previous_count)

        if velocity > 0:
            trend_direction = "up"
        elif velocity < 0:
            trend_direction = "down"
        else:
            trend_direction = "stable"

        return {"velocity": velocity, "trend_direction": trend_direction}

    def _compute_sentiment(
        self, entity_id: int, db_session: Session
    ) -> dict[str, float]:
        events = (
            db_session.query(GraphEvent)
            .join(
                EntityResolutionLog,
                GraphEvent.extraction_id == EntityResolutionLog.extraction_id,
            )
            .filter(EntityResolutionLog.resolved_id == entity_id)
            .order_by(GraphEvent.article_date)
            .all()
        )

        if not events:
            return {"avg_sentiment": 0.0, "sentiment_velocity": 0.0}

        scored: list[tuple[GraphEvent, float]] = []
        for ev in events:
            sentiment_text = (ev.sentiment or "").lower().strip()
            score = _SENTIMENT_MAP.get(sentiment_text, 0.0)
            scored.append((ev, score))

        avg_sentiment = sum(s for _, s in scored) / len(scored)

        mid = len(scored) // 2
        first_half = scored[:mid]
        second_half = scored[mid:]

        if first_half and second_half:
            first_avg = sum(s for _, s in first_half) / len(first_half)
            second_avg = sum(s for _, s in second_half) / len(second_half)
            sentiment_velocity = second_avg - first_avg
        else:
            sentiment_velocity = 0.0

        return {"avg_sentiment": avg_sentiment, "sentiment_velocity": sentiment_velocity}

    def _compute_clusters(self, db_session: Session) -> dict[int, int]:
        all_entity_rows = db_session.query(CanonicalEntity.id).all()
        all_entity_ids = {row[0] for row in all_entity_rows}

        adj: dict[int, set[int]] = defaultdict(set)
        for rel in db_session.query(Relationship).all():
            adj[rel.source_entity].add(rel.target_entity)
            adj[rel.target_entity].add(rel.source_entity)

        visited: set[int] = set()
        clusters: dict[int, int] = {}
        cluster_id = 0

        for entity_id in all_entity_ids:
            if entity_id in visited:
                continue

            if entity_id not in adj:
                clusters[entity_id] = cluster_id
                visited.add(entity_id)
                cluster_id += 1
                continue

            component: set[int] = set()
            queue: deque[int] = deque([entity_id])

            while queue:
                node = queue.popleft()
                if node in visited:
                    continue
                visited.add(node)
                component.add(node)
                for neighbor in adj.get(node, set()):
                    if neighbor not in visited:
                        queue.append(neighbor)

            for node in component:
                clusters[node] = cluster_id
            cluster_id += 1

        return clusters

    def run_full_analytics(self) -> dict:
        logger.info("Starting full analytics run")

        metrics_stats = self.compute_all_metrics()

        session = self.get_session()
        clusters: dict[int, int] = {}
        try:
            clusters = self._compute_clusters(session)

            for entity_id, cluster_id_val in clusters.items():
                existing = (
                    session.query(GraphMetric)
                    .filter(GraphMetric.entity_id == entity_id)
                    .first()
                )
                if existing is not None:
                    existing.cluster_id = cluster_id_val
                else:
                    session.add(
                        GraphMetric(
                            entity_id=entity_id,
                            cluster_id=cluster_id_val,
                        )
                    )

            session.commit()
            logger.info("Cluster assignments updated for %s entities", len(clusters))
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

        combined_stats: dict[str, int | Any] = {
            **metrics_stats,
            "clusters_assigned": len(clusters),
        }

        logger.info("Full analytics complete — %s", combined_stats)
        return combined_stats
