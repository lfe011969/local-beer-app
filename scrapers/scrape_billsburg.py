import re
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup, Tag

TAPLIST_URL = "https://taplist.io/taplist-739667"

BREWERY_NAME = "Billsburg Brewery"
BREWERY_CITY = "Williamsburg"


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
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.text


def parse_billsburg_page(html: str):
    soup = BeautifulSoup(html, "html.parser")
    now = datetime.now(timezone.utc).isoformat()
    beers: list[BeerRecord] = []

    title = soup.title.get_text(strip=True) if soup.title else "(no title)"
    print("DEBUG: page title:", title)
    print("DEBUG: html contains 'Billsburg':", "billsburg" in html.lower())

    def ul_is_coming_soon(ul: Tag) -> bool:
        heading = ul.find_previous(lambda t: isinstance(t, Tag) and t.name in ["h1", "h2", "h3", "h4"])
        if not heading:
            return False
        return "coming soon" in heading.get_text(strip=True).lower()

    # Robust match: producer line might be "Billsburg Brewery " or "Billsburg Brewery •"
    def is_billsburg_line(text: str) -> bool:
        t = text.strip().lower()
        return "billsburg" in t and "brew" in t  # catches "Billsburg Brewery", "Billsburg Brewing", etc.

    for ul in soup.find_all("ul"):
        lis = ul.find_all("li")
        if not lis:
            continue

        texts = [li.get_text(" ", strip=True) for li in lis]
        # Find the index of the producer line (approx)
        idx_brew = None
        for idx, t in enumerate(texts):
            if is_billsburg_line(t):
                idx_brew = idx
                break

        if idx_brew is None:
            continue

        # Beer name is typically the line immediately before producer
        if idx_brew == 0:
            continue

        raw_name = texts[idx_brew - 1].strip()
        if not raw_name or "try a flight" in raw_name.lower():
            # Avoid grabbing the promo header as a "beer"
            continue

        # Optional style embedded in name: "Name (Style)"
        style = None
        name = raw_name
        m = re.match(r"(.+?)\s*\((.+)\)", raw_name)
        if m:
            name = m.group(1).strip()
            style = m.group(2).strip()

        abv = None
        ibu = None

        for t in texts[idx_brew + 1 :]:
            upper = t.upper()
            if "ABV" in upper:
                m_abv = re.search(r"(\d+(?:\.\d+)?)", t)
                if m_abv:
                    abv = float(m_abv.group(1))
            if "IBU" in upper:
                m_ibu = re.search(r"(\d+)", t)
                if m_ibu:
                    ibu = int(m_ibu.group(1))

            # If Taplist has a plain style line after producer and before ABV, capture it
            if style is None and ("ABV" not in upper) and ("IBU" not in upper) and ("SRM" not in upper):
                # only accept short-ish tokens (avoid grabbing huge descriptions)
                if 2 <= len(t) <= 40:
                    style = t

        coming = ul_is_coming_soon(ul)
        tap_group = "Coming Soon" if coming else "On Tap"
        category = "coming_soon" if coming else "on_tap"

        beers.append(
            BeerRecord(
                id=slugify(f"{BREWERY_NAME}-{name}"),
                breweryName=BREWERY_NAME,
                breweryCity=BREWERY_CITY,
                producerName=BREWERY_NAME,
                name=name,
                style=style,
                abv=abv,
                ibu=ibu,
                tapGroup=tap_group,
                category=category,
                sourceUrl=TAPLIST_URL,
                lastScraped=now,
            )
        )

    print("Parsed", len(beers), "Billsburg beers")
    for b in beers[:8]:
        print("DEBUG Billsburg:", b.name, "ABV=", b.abv, "IBU=", b.ibu, "Style=", b.style)

    # If still zero, print a short excerpt so we can see what the runner received
    if len(beers) == 0:
        snippet = re.sub(r"\s+", " ", html)[:2000]
        print("DEBUG: HTML snippet (first 2000 chars):", snippet)

    return beers


def scrape_billsburg_to_json(out: str = "beers_billsburg.json"):
    print("DEBUG: starting scrape_billsburg_to_json, output:", out)
    html = fetch_html(TAPLIST_URL)
    beers = parse_billsburg_page(html)
    print("DEBUG: about to write", len(beers), "Billsburg beers")
    with open(out, "w", encoding="utf-8") as f:
        json.dump([asdict(b) for b in beers], f, indent=2, ensure_ascii=False)
    print("DEBUG: finished writing", out)


if __name__ == "__main__":
    scrape_billsburg_to_json()
