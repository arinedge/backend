from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.compare import (
    ComparisonErrorItem,
    ComparisonErrorResponse,
    ComparisonRequest,
    SeoEligibility,
    StockComparisonResponse,
)
from app.services.stock_compare_service import StockCompareService
from app.utils.logger import get_logger

router = APIRouter(prefix="/api/compare", tags=["Stock Comparison"])
logger = get_logger(__name__)


def _comparison_failure(stock1: str, stock2: str) -> ComparisonErrorResponse:
    return ComparisonErrorResponse(
        request=ComparisonRequest(stock1_input=stock1, stock2_input=stock2),
        errors=[
            ComparisonErrorItem(
                side="stock1",
                input=stock1,
                reason="Comparison data is temporarily unavailable",
            ),
            ComparisonErrorItem(
                side="stock2",
                input=stock2,
                reason="Comparison data is temporarily unavailable",
            ),
        ],
        seo_eligibility=SeoEligibility(
            indexable=False,
            sitemap_eligible=False,
            noindex_recommended=True,
            reason="Comparison generation failed",
            minimum_content_passed=False,
        ),
    )


@router.get("/stocks", response_model=StockComparisonResponse | ComparisonErrorResponse)
def compare_stocks_query(
    stock1: str = Query(..., min_length=1),
    stock2: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
):
    service = StockCompareService(db)
    try:
        return service.compare_stocks(stock1, stock2)
    except Exception:
        logger.exception("Stock comparison failed for %s vs %s", stock1, stock2)
        return _comparison_failure(stock1, stock2)


@router.get("/stocks/{stock1}/vs/{stock2}", response_model=StockComparisonResponse | ComparisonErrorResponse)
def compare_stocks_path(
    stock1: str,
    stock2: str,
    db: Session = Depends(get_db),
):
    service = StockCompareService(db)
    try:
        return service.compare_stocks(stock1, stock2)
    except Exception:
        logger.exception("Stock comparison failed for %s vs %s", stock1, stock2)
        return _comparison_failure(stock1, stock2)
