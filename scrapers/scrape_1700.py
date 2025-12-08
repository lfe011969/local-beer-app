import re
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

DRINK_MENU_URL = "https://1700brewing.beer/newport-news-1700-brewing-drink-menu"

BREWERY_NAME = "1700 Brewing"
BREWERY_CITY = "Newport News"


@dataclass
class BeerRecord:
    id: str
    breweryName: str
    breweryCity: str
    producerName: str
    name: str
    style: str | None
    abv: float | None
    ibu: int | None
    tapGroup: str
    category: str
    sourceUrl: str
    lastScraped: str


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[’']", "", text)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


def fetch_html(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        )
    }
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.text


def parse_stats_line(line: str):
    abv = None
    ibu = None
    style_from_line = None
    producer_name = None

    parts = [p.strip() for p in line.split("|")]
    if parts:
        producer_name = parts[-1]

    m_abv = re.search(r"(\d+(?:\.\d+)?)\s*%?\s*ABV", line, re.IGNORECASE)
    if m_abv:
        abv = float(m_abv.group(1))

    m_ibu = re.search(r"(\d+|N/A)\s*IBU", line, re.IGNORECASE)
    if m_ibu:
        v = m_ibu.group(1).upper()
        if v != "N/A":
            ibu = int(v)

    if "•" in line and "|" in line:
        after = line.split("•", 1)[1]
        style_from_line = after.split("|", 1)[0].strip()

    return abv, ibu, style_from_line, producer_name


def parse_header(text: str):
    text = text.strip()
    m = re.match(r"^\d+\.\s*(.+)$", text)
    if m:
        text = m.group(1).strip()

    if "," in text:
        name_part, style_part = text.split(",", 1)
        return name_part.strip(), style_part.strip()

    return text, None


def parse_1700_page(html: str):
    soup = BeautifulSoup(html, "html.parser")
    beers = []
    now = datetime.now(timezone.utc).isoformat()

    headings = soup.find_all(["h2", "h3"])
    print("DEBUG: found", len(headings), "<h2>/<h3> headings")
