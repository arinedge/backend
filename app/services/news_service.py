from datetime import datetime, timedelta

from sqlalchemy import func, distinct
from sqlalchemy.orm import Session

from app.models.news import NewsArticle, NewsExtraction


class NewsService:
    def __init__(self, db: Session):
        self.db = db

    def get_articles(
        self,
        page: int = 1,
        per_page: int = 20,
        source: str | None = None,
        author: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> tuple[list[NewsArticle], int]:
        query = self.db.query(NewsArticle)

        if source:
            query = query.filter(NewsArticle.source_name == source)
        if author:
            query = query.filter(NewsArticle.author == author)
        if date_from:
            query = query.filter(NewsArticle.published_at >= datetime.fromisoformat(date_from))
        if date_to:
            query = query.filter(NewsArticle.published_at <= datetime.fromisoformat(date_to) + timedelta(days=1))

        total = query.count()
        query = query.order_by(NewsArticle.published_at.desc().nullslast())
        query = query.offset((page - 1) * per_page).limit(per_page)
        items = query.all()
        return items, total

    def get_article_by_id(self, news_id: int) -> NewsArticle | None:
        return self.db.query(NewsArticle).filter(NewsArticle.id == news_id).first()

    def get_extraction_by_news_id(self, news_id: int) -> NewsExtraction | None:
        return self.db.query(NewsExtraction).filter(NewsExtraction.news_id == news_id).first()

    def get_filters(self) -> dict:
        sources = [
            row[0] for row in self.db.query(distinct(NewsArticle.source_name))
            .filter(NewsArticle.source_name.isnot(None))
            .order_by(NewsArticle.source_name)
            .all()
        ]
        authors = [
            row[0] for row in self.db.query(distinct(NewsArticle.author))
            .filter(NewsArticle.author.isnot(None))
            .order_by(NewsArticle.author)
            .all()
        ]
        date_range = self.db.query(
            func.min(NewsArticle.published_at),
            func.max(NewsArticle.published_at),
        ).first()
        return {
            "sources": sources,
            "authors": authors,
            "date_range": {
                "min": date_range[0].strftime("%Y-%m-%d") if date_range[0] else None,
                "max": date_range[1].strftime("%Y-%m-%d") if date_range[1] else None,
            },
        }
