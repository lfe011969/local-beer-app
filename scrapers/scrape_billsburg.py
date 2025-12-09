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

    # We'll treat an <h2>/<h3>/<h4> containing "Coming Soon" as the divider
    def ul_is_coming_soon(ul: Tag) -> bool:
        heading = ul.find_previous(
            lambda tag: isinstance(tag, Tag)
            and tag.name in ["h2", "h3", "h4"]
            and "coming soon" in tag.get_text(strip=True).lower()
        )
        return heading is not None

    # For each <ul> that lists Billsburg beers
    for ul in soup.find_all("ul"):
        lis = ul.find_all("li")
        if not lis:
            continue

        if not any(li.get_text(strip=True) == BREWERY_NAME for li in lis):
            continue

        # --- Find beer name from previous siblings ---
        name_tag: Tag | None = None
        for sib in ul.previous_siblings:
            if not isinstance(sib, Tag):
                continue
            text = sib.get_text(strip=True)
            if not text:
                continue
            # Ignore global headings / boilerplate
            if text == BREWERY_NAME:
                continue
            if "Billsburg Brewery - Current Menu" in text:
                continue
            if "Coming Soon" in text:
                continue
            name_tag = sib
            break

        if name_tag is None:
            # Fallback: previous heading
            name_tag = ul.find_previous(["h1", "h2", "h3", "h4", "h5", "h6"])
            if name_tag is None:
                continue

        beer_name = name_tag.get_text(strip=True)

        # --- Parse stats from <li>s AFTER the 'Billsburg Brewery' line ---
        abv: float | None = None
        ibu: int | None = None
        style: str | None = None

        passed_brewery = False
        for li in lis:
            text = li.get_text(strip=True)
            upper = text.upper()

            if text == BREWERY_NAME:
                passed_brewery = True
                continue
            if not passed_brewery:
                continue

            if "ABV" in upper:
                m = re.search(r"(\d+(?:\.\d+)?)", text)
                if m:
                    abv = float(m.group(1))
                continue

            if "IBU" in upper:
                m = re.search(r"(\d+)", text)
                if m:
                    ibu = int(m.group(1))
                continue

            if "SRM" in upper:
                # color only; ignore for now
                continue

            # Anything else after brewery/ABV/IBU we treat as style (e.g. "Schwarzbier")
            if style is None:
                style = text

        # --- Decide tap group / category ---
        coming = ul_is_coming_soon(ul)
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
    for b in beers[:10]:
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
