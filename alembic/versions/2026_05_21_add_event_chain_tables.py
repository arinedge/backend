"""add event chain intelligence tables

Revision ID: 20260521001
Revises: 20260514001
Create Date: 2026-05-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260521001"
down_revision: Union[str, None] = "20260514001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # nse_canonical_entities
    op.create_table(
        "nse_canonical_entities",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("canonical_name", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("sector", sa.Text(), nullable=True),
        sa.Column("ticker", sa.Text(), nullable=True),
        sa.Column("isin", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("confidence", sa.Float(), server_default=sa.text("1.0"), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("canonical_name"),
    )

    # nse_entity_aliases
    op.create_table(
        "nse_entity_aliases",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("canonical_id", sa.BigInteger(), nullable=True),
        sa.Column("alias", sa.Text(), nullable=False),
        sa.Column("alias_type", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), server_default=sa.text("0.8"), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_foreign_key(
        "fk_entity_aliases_canonical",
        "nse_entity_aliases", "nse_canonical_entities",
        ["canonical_id"], ["id"],
    )
    op.create_index("ix_entity_aliases_alias", "nse_entity_aliases", ["alias"])
    op.execute(
        "CREATE INDEX ix_entity_aliases_alias_trgm ON nse_entity_aliases USING gin (alias gin_trgm_ops)"
    )

    # nse_entity_embeddings
    op.create_table(
        "nse_entity_embeddings",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("canonical_id", sa.BigInteger(), nullable=True),
        sa.Column("embedding", postgresql.ARRAY(sa.Float()), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_foreign_key(
        "fk_entity_embeddings_canonical",
        "nse_entity_embeddings", "nse_canonical_entities",
        ["canonical_id"], ["id"],
    )

    # nse_entity_resolution_log
    op.create_table(
        "nse_entity_resolution_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("extraction_id", sa.Integer(), nullable=True),
        sa.Column("raw_name", sa.Text(), nullable=False),
        sa.Column("resolved_id", sa.BigInteger(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("method", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_foreign_key(
        "fk_entity_resolution_log_extraction",
        "nse_entity_resolution_log", "news_extraction",
        ["extraction_id"], ["id"],
    )
    op.create_foreign_key(
        "fk_entity_resolution_log_canonical",
        "nse_entity_resolution_log", "nse_canonical_entities",
        ["resolved_id"], ["id"],
    )

    # nse_event_types
    op.create_table(
        "nse_event_types",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("parent_type", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_type"),
    )

    # nse_events
    op.create_table(
        "nse_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("extraction_id", sa.Integer(), nullable=True),
        sa.Column("news_id", sa.Integer(), nullable=True),
        sa.Column("event_type_id", sa.Integer(), nullable=True),
        sa.Column("event_type_raw", sa.Text(), nullable=True),
        sa.Column("sentiment", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("importance", sa.Integer(), nullable=True),
        sa.Column("evidence_span", sa.Text(), nullable=True),
        sa.Column("event_date", sa.Date(), nullable=True),
        sa.Column("article_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_foreign_key(
        "fk_events_extraction",
        "nse_events", "news_extraction",
        ["extraction_id"], ["id"],
    )
    op.create_foreign_key(
        "fk_events_news",
        "nse_events", "market_news",
        ["news_id"], ["id"],
    )
    op.create_foreign_key(
        "fk_events_event_type",
        "nse_events", "nse_event_types",
        ["event_type_id"], ["id"],
    )
    op.create_index("ix_nse_events_news_id", "nse_events", ["news_id"])
    op.create_index("ix_nse_events_extraction_id", "nse_events", ["extraction_id"])

    # nse_relationships
    op.create_table(
        "nse_relationships",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("source_entity", sa.BigInteger(), nullable=True),
        sa.Column("target_entity", sa.BigInteger(), nullable=True),
        sa.Column("relation_type", sa.Text(), nullable=False),
        sa.Column("weight", sa.Float(), server_default=sa.text("1.0"), nullable=True),
        sa.Column("confidence", sa.Float(), server_default=sa.text("0.5"), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_count", sa.Integer(), server_default=sa.text("1"), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_foreign_key(
        "fk_relationships_source",
        "nse_relationships", "nse_canonical_entities",
        ["source_entity"], ["id"],
    )
    op.create_foreign_key(
        "fk_relationships_target",
        "nse_relationships", "nse_canonical_entities",
        ["target_entity"], ["id"],
    )
    op.create_index(
        "ix_nse_relationships_source_target",
        "nse_relationships",
        ["source_entity", "target_entity"],
    )

    # nse_relationship_evidence
    op.create_table(
        "nse_relationship_evidence",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("relationship_id", sa.BigInteger(), nullable=True),
        sa.Column("extraction_id", sa.Integer(), nullable=True),
        sa.Column("news_id", sa.Integer(), nullable=True),
        sa.Column("evidence_span", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_foreign_key(
        "fk_relationship_evidence_rel",
        "nse_relationship_evidence", "nse_relationships",
        ["relationship_id"], ["id"],
    )
    op.create_foreign_key(
        "fk_relationship_evidence_extraction",
        "nse_relationship_evidence", "news_extraction",
        ["extraction_id"], ["id"],
    )
    op.create_foreign_key(
        "fk_relationship_evidence_news",
        "nse_relationship_evidence", "market_news",
        ["news_id"], ["id"],
    )

    # nse_graph_metrics
    op.create_table(
        "nse_graph_metrics",
        sa.Column("entity_id", sa.BigInteger(), nullable=False),
        sa.Column("pagerank", sa.Float(), nullable=True),
        sa.Column("degree_centrality", sa.Float(), nullable=True),
        sa.Column("betweenness", sa.Float(), nullable=True),
        sa.Column("mention_velocity", sa.Float(), nullable=True),
        sa.Column("sentiment_score", sa.Float(), nullable=True),
        sa.Column("sentiment_velocity", sa.Float(), nullable=True),
        sa.Column("cluster_id", sa.Integer(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("entity_id"),
    )
    op.create_foreign_key(
        "fk_graph_metrics_entity",
        "nse_graph_metrics", "nse_canonical_entities",
        ["entity_id"], ["id"],
    )

    # nse_propagation_scores
    op.create_table(
        "nse_propagation_scores",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("source_id", sa.BigInteger(), nullable=True),
        sa.Column("target_id", sa.BigInteger(), nullable=True),
        sa.Column("propagation_score", sa.Float(), nullable=True),
        sa.Column("influence_path", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("hop_count", sa.Integer(), nullable=True),
        sa.Column("decay_factor", sa.Float(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_foreign_key(
        "fk_propagation_scores_source",
        "nse_propagation_scores", "nse_canonical_entities",
        ["source_id"], ["id"],
    )
    op.create_foreign_key(
        "fk_propagation_scores_target",
        "nse_propagation_scores", "nse_canonical_entities",
        ["target_id"], ["id"],
    )
    op.create_index(
        "ix_nse_propagation_scores_source_target",
        "nse_propagation_scores",
        ["source_id", "target_id"],
    )

    # Seed 31 event types
    event_types = [
        ("management_change", "corporate_action", "Changes in executive leadership or board composition"),
        ("merger", "corporate_action", "Two companies combine to form a single entity"),
        ("acquisition", "corporate_action", "One company acquires ownership of another company"),
        ("divestiture", "corporate_action", "Company sells off a portion of its business"),
        ("spin_off", "corporate_action", "Company separates a subsidiary into an independent entity"),
        ("stock_split", "corporate_action", "Company increases number of shares by dividing existing shares"),
        ("buyback", "corporate_action", "Company repurchases its own shares from the market"),
        ("dividend", "corporate_action", "Company distributes portion of earnings to shareholders"),
        ("bonus_issue", "corporate_action", "Company issues additional shares to existing shareholders"),
        ("rights_issue", "corporate_action", "Company offers existing shareholders right to buy new shares"),
        ("ipo", "corporate_action", "Company offers shares to the public for the first time"),
        ("fpo", "corporate_action", "Company issues additional shares after an IPO"),
        ("earnings", "financial_event", "Company releases quarterly or annual financial results"),
        ("profit_warning", "financial_event", "Company warns that earnings will be below expectations"),
        ("revenue_milestone", "financial_event", "Company achieves a significant revenue target"),
        ("debt_restructuring", "financial_event", "Company renegotiates terms of its debt obligations"),
        ("fundraising", "financial_event", "Company raises capital through debt or equity"),
        ("credit_rating_change", "financial_event", "Credit rating agency upgrades or downgrades company rating"),
        ("regulatory_action", "regulatory_event", "Regulatory body takes action affecting the company"),
        ("legal_dispute", "regulatory_event", "Company is involved in a legal case or regulatory dispute"),
        ("compliance_milestone", "regulatory_event", "Company achieves regulatory compliance approval"),
        ("policy_change", "regulatory_event", "Government policy change that affects the company or sector"),
        ("fraud_allegation", "regulatory_event", "Company is accused of fraudulent activity"),
        ("contract_win", "business_development", "Company wins a significant contract or client"),
        ("partnership", "business_development", "Company enters into a strategic partnership or joint venture"),
        ("expansion", "business_development", "Company expands operations into new markets or geographies"),
        ("product_launch", "business_development", "Company launches a new product or service"),
        ("plant_shutdown", "operational_event", "Company closes or temporarily halts operations at a facility"),
        ("supply_chain_disruption", "operational_event", "Company faces disruption in its supply chain"),
        ("cyber_incident", "operational_event", "Company experiences a cybersecurity breach or attack"),
        ("natural_disaster_impact", "operational_event", "Natural disaster affects company operations or assets"),
    ]
    conn = op.get_bind()
    for event_type, parent_type, description in event_types:
        conn.execute(
            sa.text(
                "INSERT INTO nse_event_types (event_type, parent_type, description) "
                "VALUES (:event_type, :parent_type, :description)"
                " ON CONFLICT (event_type) DO NOTHING"
            ),
            {"event_type": event_type, "parent_type": parent_type, "description": description},
        )


def downgrade() -> None:
    op.drop_table("nse_propagation_scores")
    op.drop_table("nse_graph_metrics")
    op.drop_table("nse_relationship_evidence")
    op.drop_table("nse_relationships")
    op.drop_table("nse_events")
    op.drop_table("nse_event_types")
    op.drop_table("nse_entity_resolution_log")
    op.drop_table("nse_entity_embeddings")
    op.drop_table("nse_entity_aliases")
    op.drop_table("nse_canonical_entities")
