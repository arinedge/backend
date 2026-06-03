from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.news_service import NewsService
from app.schemas.news import NewsArticleOut, NewsExtractionOut, PaginatedNewsResponse, NewsFiltersOut
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(tags=["News"])


@router.get("", response_model=PaginatedNewsResponse)
def list_articles(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    source: str | None = Query(None),
    author: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    db: Session = Depends(get_db),
):
    service = NewsService(db)
    items, total = service.get_articles(
        page=page, per_page=per_page,
        source=source, author=author,
        date_from=date_from, date_to=date_to,
    )
    pages = max(1, (total + per_page - 1) // per_page)
    return PaginatedNewsResponse(
        items=[NewsArticleOut.model_validate(a) for a in items],
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
        has_next=page < pages,
        has_prev=page > 1,
    )


@router.get("/{news_id}", response_model=NewsArticleOut)
def get_article(news_id: int, db: Session = Depends(get_db)):
    service = NewsService(db)
    article = service.get_article_by_id(news_id)
    if not article:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")
    return NewsArticleOut.model_validate(article)


@router.get("/{news_id}/extraction", response_model=NewsExtractionOut)
def get_article_extraction(news_id: int, db: Session = Depends(get_db)):
    service = NewsService(db)
    extraction = service.get_extraction_by_news_id(news_id)
    if not extraction:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Extraction not found")
    return NewsExtractionOut.model_validate(extraction)


@router.get("/filters", response_model=NewsFiltersOut)
def get_filters(db: Session = Depends(get_db)):
    service = NewsService(db)
    return NewsFiltersOut(**service.get_filters())
