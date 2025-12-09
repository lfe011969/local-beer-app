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
    tapGroup: str          # e.g. "On Tap", "Coming Soon"
    category: str          # e.g. "on_tap", "coming_soon"
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

    # Find the node that marks the "Coming Soon" section so we can distinguish groups
    coming_soon_tag = None
    for h in soup.find_all(["h2", "h3", "h4"]):
        if "coming soon" in h.get_text(strip=True).lower():
            coming_soon_tag = h
            break

    def is_coming_soon(heading: Tag) -> bool:
        # If we never found a Coming Soon header, treat everything as on tap
        if coming_soon_tag is None:
            return False
        # heading comes after coming_soon_tag in document order?
        for elem in soup.descendants:
            if elem is coming_soon_tag:
                # from this point on, anything we see is "coming soon"
                seen_marker = True
            if elem is heading:
                # if we hit heading before marker, it's not coming soon
                return False
        # Fallback: if we couldn't determine order, just say not coming soon
        return False

    # Strategy:
    # For every <ul> containing a <li> equal to "Billsburg Brewery",
    # treat the nearest previous heading as the beer name, and the other <li>s
    # in that <ul> as stats (style, ABV, IBU, etc).
    for ul in soup.find_all("ul"):
        lis = ul.find_all("li")
        if not lis:
            continue

        has_brewery = any(
            li.get_text(strip=True) == BREWERY_NAME for li in lis
        )
        if not has_brewery:
            continue

        # Find the beer's heading just before this <ul>
        heading = ul.find_previous(["h1", "h2", "h3", "h4", "h5", "h6"])
        if not heading:
            continue

        beer_name = heading.get_text(strip=True)
        abv = None
        ibu = None
        style = None

        # We only want lines AFTER the "Billsburg Brewery" li
        passed_brewery = False
        for li in lis:
            text = li.get_text(strip=True)

            if text == BREWERY_NAME:
                passed_brewery = True
                continue
            if not passed_brewery:
                continue

            upper = text.upper()

            # ABV line
            if "ABV" in upper:
                m = re.search(r"(\d+(?:\.\d+)?)", text)
                if m:
                    abv = float(m.group(1))
                continue

            # IBU line
            if "IBU" in upper:
                m = re.search(r"(\d+)", text)
                if m:
                    ibu = int(m.group(1))
                continue

            # Potential style line (ignore SRM)
            if "SRM" not in upper and style is None:
                style = text

        # Decide tap group/category
        if coming_soon_tag is not None and heading.sourceline and coming_soon_tag.sourceline:
            coming = heading.sourceline > coming_soon_tag.sourceline
        else:
            # Fallback: simple heuristic based on text
            coming = "coming soon" in beer_name.lower()

        tap_group = "Coming Soon" if coming else "On Tap"
        category = "coming_soon" if coming else "on_tap"

        beer_id = slugify(f"{BREWERY_NAME}-{beer_name}")

        beers.append(
            BeerRecord(
                id=beer_id,
                breweryName=BREWERY_NAME,
                breweryCity=BREWERY_CITY,
                producerName=BREWERY_NAME,
                name=beer_name,
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
