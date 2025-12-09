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
    tapGroup: str          # "On Tap" or "Coming Soon"
    category: str          # "on_tap" or "coming_soon"
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
    resp = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()
    return resp.text


def parse_billsburg_page(html: str):
    soup = BeautifulSoup(html, "html.parser")
    beers: list[BeerRecord] = []
    now = datetime.now(timezone.utc).isoformat()

    def ul_is_coming_soon(ul: Tag) -> bool:
        """Look for the nearest previous heading that says 'Coming Soon'."""
        heading = ul.find_previous(
            lambda tag: isinstance(tag, Tag)
            and tag.name in ["h1", "h2", "h3", "h4"]
        )
        if not heading:
            return False
        return "coming soon" in heading.get_text(strip=True).lower()

    for ul in soup.find_all("ul"):
        lis = ul.find_all("li")
        if not lis:
            continue

        texts = [li.get_text(strip=True) for li in lis]

        # must contain the brewery line to be a beer entry
        if BREWERY_NAME not in texts:
            continue

        idx_brew = texts.index(BREWERY_NAME)
        if idx_brew == 0:
            # there's no line before the brewery, so we don't know the name
            continue

        # Beer name is the <li> immediately before "Billsburg Brewery"
        raw_name = texts[idx_brew - 1]

        # Try to split out style if it is embedded, e.g. "Invisible Light (Schwarzbier)"
        style = None
        name = raw_name
        m = re.match(r"(.+?)\s*\((.+)\)", raw_name)
        if m:
            name = m.group(1).strip()
            style = m.group(2).strip()

        abv: float | None = None
        ibu: int | None = None

        # Look at lines after the brewery for ABV / IBU
        for text in texts[idx_brew + 1 :]:
            upper = text.upper()

            if "ABV" in upper:
                m_abv = re.search(r"(\d+(?:\.\d+)?)", text)
                if m_abv:
                    abv = float(m_abv.group(1))

            if "IBU" in upper:
                m_ibu = re.search(r"(\d+)", text)
                if m_ibu:
                    ibu = int(m_ibu.group(1))

        coming = ul_is_coming_soon(ul)
        tap_group = "Coming Soon" if coming else "On Tap"
        category = "coming_soon" if coming else "on_tap"

        beer_id = slugify(f"{BREWERY_NAME}-{name}")

        beers.append(
            BeerRecord(
                id=beer_id,
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
    for b in beers[:10]:
        print("DEBUG Billsburg:", repr(b.name), "ABV=", b.abv, "IBU=", b.ibu, "Style=", b.style)

    return beers


def scrape_billsburg_to_json(out: str = "beers_billsburg.json"):
    print("DEBUG: starting scrape_billsburg_to_json, output:", out)
    html = fetch_html(TAPLIST_URL)
    beers = parse_billsburg_page(html)
    print("DEBUG: about to write", len(beers), "Billsburg beers")
    data = [asdict(b) for b in beers]
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print("DEBUG: finished writing", out)


if __name__ == "__main__":
    scrape_billsburg_to_json()
