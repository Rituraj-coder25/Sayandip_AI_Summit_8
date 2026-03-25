"""
Extracts clean article text from raw HTML.
Used by both the Playwright scraper and the world-monitor scraper.
"""
import re
from bs4 import BeautifulSoup


def extract_article_text(html: str, max_chars: int = 800) -> str:
    """
    Clean article text from raw HTML.
    Strips nav, header, footer, ads, scripts, styles.
    Returns plain text up to max_chars.
    """
    soup = BeautifulSoup(html, "lxml")

    # Remove noise elements
    for tag in soup(["script", "style", "nav", "header", "footer", "aside",
                     "iframe", "noscript", "advertisement", "[document]"]):
        tag.decompose()

    # Try to find the article body
    article = (
        soup.find("article") or
        soup.find("main") or
        soup.find(class_=re.compile(r"article|content|story|body|post", re.I)) or
        soup.find("body")
    )

    text = (article or soup).get_text(separator=" ", strip=True)
    # Collapse whitespace
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text[:max_chars]


def extract_headline(html: str) -> str:
    """Extract the headline/title from raw HTML."""
    soup = BeautifulSoup(html, "lxml")
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)[:200]
    og_title = soup.find("meta", property="og:title")
    if og_title:
        return og_title.get("content", "")[:200]
    title = soup.find("title")
    return title.get_text(strip=True)[:200] if title else ""


def extract_meta(html: str) -> dict:
    """Extract Open Graph and Twitter card metadata."""
    soup = BeautifulSoup(html, "lxml")
    meta = {}
    for m in soup.find_all("meta"):
        prop = m.get("property") or m.get("name", "")
        val  = m.get("content", "")
        if prop.startswith("og:") or prop.startswith("twitter:"):
            meta[prop] = val[:300]
    return meta
