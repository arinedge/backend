from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.landing import LandingResponse
from app.services.landing_page_service import LandingPageService
from app.utils.logger import get_logger

router = APIRouter(prefix="/api/landing", tags=["Landing"])
logger = get_logger(__name__)


@router.get("/stocks/{symbol}/financials", response_model=LandingResponse)
def get_stock_financials(symbol: str, db: Session = Depends(get_db)):
    logger.info("GET /api/landing/stocks/%s/financials", symbol)
    return LandingPageService(db).get_stock_financials(symbol)


@router.get("/stocks/{symbol}/overview", response_model=LandingResponse)
def get_stock_overview(symbol: str, db: Session = Depends(get_db)):
    logger.info("GET /api/landing/stocks/%s/overview", symbol)
    return LandingPageService(db).get_stock_overview(symbol)


@router.get("/stocks/{symbol}/ratios", response_model=LandingResponse)
def get_stock_ratios(symbol: str, db: Session = Depends(get_db)):
    logger.info("GET /api/landing/stocks/%s/ratios", symbol)
    return LandingPageService(db).get_stock_ratios(symbol)


@router.get("/stocks/{symbol}/price-history", response_model=LandingResponse)
def get_stock_price_history(symbol: str, db: Session = Depends(get_db)):
    logger.info("GET /api/landing/stocks/%s/price-history", symbol)
    return LandingPageService(db).get_stock_price_history(symbol)


@router.get("/stocks/{symbol}/bull-bear-context", response_model=LandingResponse)
def get_stock_bull_bear(symbol: str, db: Session = Depends(get_db)):
    logger.info("GET /api/landing/stocks/%s/bull-bear-context", symbol)
    return LandingPageService(db).get_stock_bull_bear(symbol)


@router.get("/stocks/{symbol}/risk-signals", response_model=LandingResponse)
def get_stock_risk_signals(symbol: str, db: Session = Depends(get_db)):
    logger.info("GET /api/landing/stocks/%s/risk-signals", symbol)
    return LandingPageService(db).get_stock_risk_signals(symbol)


@router.get("/stocks/{symbol}/competitors", response_model=LandingResponse)
def get_stock_competitors(symbol: str, db: Session = Depends(get_db)):
    logger.info("GET /api/landing/stocks/%s/competitors", symbol)
    return LandingPageService(db).get_stock_competitors(symbol)


@router.get("/stocks/{symbol}/fno-positioning", response_model=LandingResponse)
def get_stock_fno_positioning(symbol: str, db: Session = Depends(get_db)):
    logger.info("GET /api/landing/stocks/%s/fno-positioning", symbol)
    return LandingPageService(db).get_stock_fno_positioning(symbol)


@router.get("/stocks/{symbol}/oi-analysis", response_model=LandingResponse)
def get_stock_oi_analysis(symbol: str, db: Session = Depends(get_db)):
    logger.info("GET /api/landing/stocks/%s/oi-analysis", symbol)
    return LandingPageService(db).get_stock_oi_analysis(symbol)


@router.get("/stocks/{symbol}/open-interest", response_model=LandingResponse)
def get_stock_open_interest(symbol: str, db: Session = Depends(get_db)):
    logger.info("GET /api/landing/stocks/%s/open-interest", symbol)
    return LandingPageService(db).get_stock_oi_analysis(symbol)


@router.get("/stocks/{symbol}/put-call-ratio", response_model=LandingResponse)
def get_stock_pcr(symbol: str, db: Session = Depends(get_db)):
    logger.info("GET /api/landing/stocks/%s/put-call-ratio", symbol)
    return LandingPageService(db).get_stock_pcr(symbol)


@router.get("/stocks/{symbol}/gamma-exposure", response_model=LandingResponse)
def get_stock_gamma_exposure(symbol: str, db: Session = Depends(get_db)):
    logger.info("GET /api/landing/stocks/%s/gamma-exposure", symbol)
    return LandingPageService(db).get_stock_gamma_exposure(symbol)


@router.get("/stocks/{symbol}/events", response_model=LandingResponse)
def get_stock_events(symbol: str, db: Session = Depends(get_db)):
    logger.info("GET /api/landing/stocks/%s/events", symbol)
    return LandingPageService(db).get_stock_events(symbol)


@router.get("/stocks/{symbol}/bulk-block-deals", response_model=LandingResponse)
def get_stock_bulk_block_deals(symbol: str, db: Session = Depends(get_db)):
    logger.info("GET /api/landing/stocks/%s/bulk-block-deals", symbol)
    return LandingPageService(db).get_stock_bulk_block_deals(symbol)


@router.get("/stocks/{symbol}/corporate-actions", response_model=LandingResponse)
def get_stock_corporate_actions(symbol: str, db: Session = Depends(get_db)):
    logger.info("GET /api/landing/stocks/%s/corporate-actions", symbol)
    return LandingPageService(db).get_stock_corporate_actions(symbol)


@router.get("/sectors/{slug}", response_model=LandingResponse)
def get_sector_overview(slug: str, db: Session = Depends(get_db)):
    logger.info("GET /api/landing/sectors/%s", slug)
    return LandingPageService(db).get_sector_overview(slug)


@router.get("/sectors/{slug}/fno-positioning", response_model=LandingResponse)
def get_sector_fno_positioning(slug: str, db: Session = Depends(get_db)):
    logger.info("GET /api/landing/sectors/%s/fno-positioning", slug)
    return LandingPageService(db).get_sector_fno_positioning(slug)


@router.get("/sectors/{slug}/risk-signals", response_model=LandingResponse)
def get_sector_risk_signals(slug: str, db: Session = Depends(get_db)):
    logger.info("GET /api/landing/sectors/%s/risk-signals", slug)
    return LandingPageService(db).get_sector_risk_signals(slug)


@router.get("/market-flow/fii-dii", response_model=LandingResponse)
def get_market_flow_fii_dii(db: Session = Depends(get_db)):
    logger.info("GET /api/landing/market-flow/fii-dii")
    return LandingPageService(db).get_market_flow_fii_dii()


@router.get("/participant-oi", response_model=LandingResponse)
def get_participant_oi(db: Session = Depends(get_db)):
    logger.info("GET /api/landing/participant-oi")
    return LandingPageService(db).get_participant_oi()


@router.get("/market-breadth", response_model=LandingResponse)
def get_market_breadth(db: Session = Depends(get_db)):
    logger.info("GET /api/landing/market-breadth")
    return LandingPageService(db).get_market_breadth()


@router.get("/sector-rotation", response_model=LandingResponse)
def get_sector_rotation(db: Session = Depends(get_db)):
    logger.info("GET /api/landing/sector-rotation")
    return LandingPageService(db).get_sector_rotation()


@router.get("/events/{slug}", response_model=LandingResponse)
def get_event_impact(slug: str, db: Session = Depends(get_db)):
    logger.info("GET /api/landing/events/%s", slug)
    return LandingPageService(db).get_event_impact(slug)


@router.get("/stocks-affected/{slug}", response_model=LandingResponse)
def get_affected_stocks(slug: str, db: Session = Depends(get_db)):
    logger.info("GET /api/landing/stocks-affected/%s", slug)
    return LandingPageService(db).get_affected_stocks(slug)


@router.get("/ipos", response_model=LandingResponse)
def get_ipo_hub(db: Session = Depends(get_db)):
    logger.info("GET /api/landing/ipos")
    return LandingPageService(db).get_ipo_hub()


@router.get("/ipos/{symbol}", response_model=LandingResponse)
def get_ipo_detail(symbol: str, db: Session = Depends(get_db)):
    logger.info("GET /api/landing/ipos/%s", symbol)
    return LandingPageService(db).get_ipo_detail(symbol)


@router.get("/signals", response_model=LandingResponse)
def get_signal_catalog(db: Session = Depends(get_db)):
    logger.info("GET /api/landing/signals")
    return LandingPageService(db).get_signal_catalog()


@router.get("/signals/{signal_code}", response_model=LandingResponse)
def get_signal_detail(signal_code: str, db: Session = Depends(get_db)):
    logger.info("GET /api/landing/signals/%s", signal_code)
    return LandingPageService(db).get_signal_detail(signal_code)


@router.get("/nexus-signals/{signal_code}", response_model=LandingResponse)
def get_nexus_signal_detail(signal_code: str, db: Session = Depends(get_db)):
    logger.info("GET /api/landing/nexus-signals/%s", signal_code)
    return LandingPageService(db).get_nexus_signal_detail(signal_code)


@router.get("/stocks/{symbol}/insider-trading")
def get_stock_insider_trading(symbol: str, db: Session = Depends(get_db)):
    logger.info("GET /api/landing/stocks/%s/insider-trading", symbol)
    result = LandingPageService(db).get_stock_insider_trading(symbol)
    return {"data": result or []}
