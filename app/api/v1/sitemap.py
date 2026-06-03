from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.news import NewsArticle

router = APIRouter(tags=["SEO"])


@router.get("/sitemap.xml", response_class=PlainTextResponse, include_in_schema=False)
def generate_sitemap(db: Session = Depends(get_db)):
    articles = db.query(NewsArticle).order_by(NewsArticle.created_at.desc()).all()

    urls = ['https://arinedge.com/']

    for article in articles:
        slug = str(article.id)
        urls.append(f'https://arinedge.com/news/{slug}')

    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for url in urls:
        xml += '  <url>\n'
        xml += f'    <loc>{url}</loc>\n'
        xml += '  </url>\n'
    xml += '</urlset>'

    return PlainTextResponse(content=xml, media_type="application/xml")
