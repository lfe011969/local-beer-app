import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional

import requests
from bs4 import BeautifulSoup, Tag

# Scrape the VENUE MENU source (1700's site drink menu mirrors their current tap list)
MENU_URL = "https://untappd.com/v/1700-brewing/10975639"

BREWERY_NAME = "1700 Brewing"
BREWERY_CITY = "Newport News"


@dataclass
class BeerRecord:
    id: str
    breweryName: str
    breweryCity: str
    producerName: str
    name: str
    style: Optional[str]
    abv: Optional[float]
    ibu: Optional[int]
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
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return r.text


def parse_abv_ibu_producer(line: str):
    """
    Expected format on 1700 menu page:
      "5.3% ABV | 22 IBU | 1700 Brewing"
    Sometimes IBU may be missing or "N/A".
    """
    # Normalize separators/spaces
    raw = " ".join(line.strip().split())

    # Split by pipe
    parts = [p.strip() for p in raw.split("|")]
    # parts often: ["5.3% ABV", "22 IBU", "1700 Brewing"]
    abv = None
    ibu = None
    producer = BREWERY_NAME

    # ABV
    for p in parts:
        m = re.search(r"(\d+(?:\.\d+)?)\s*%\s*ABV", p, flags=re.I)
        if m:
            try:
                abv = float(m.group(1))
            except ValueError:
                abv = None
            break

    # IBU
    for p in parts:
        # allow "N/A IBU"
        m = re.search(r"(\d+)\s*IBU", p, flags=re.I)
        if m:
            try:
                ibu = int(m.group(1))
            except ValueError:
                ibu = None
            break

    # Producer: usually last part that isn't ABV/IBU
    for p in reversed(parts):
        if re.search(r"ABV", p, flags=re.I):
            continue
        if re.search(r"IBU", p, flags=re.I):
            continue
        if p and p.lower() != "n/a":
            producer = p
            break

    return abv, ibu, producer


def parse_beer_heading(h3_text: str):
    """
    Heading example:
      "1. Plain Old Lager (P.O.L.), Lager - Vienna"
      "8. SchWARz Brr, Schwarzbier/Dark Lager"
    We want:
      name = "Plain Old Lager (P.O.L.)"
      style = "Lager - Vienna"
    """
    text = " ".join(h3_text.strip().split())

    # remove leading number like "1." or "12."
    text = re.sub(r"^\s*\d+\.\s*", "", text)

    # split on first comma
    if "," in text:
        name, style = text.split(",", 1)
        name = name.strip()
        style = style.strip() or None
    else:
        name = text.strip()
        style = None

    return name, style


def scrape_1700_to_json(output_path: str = "beers_1700.json"):
    print("DEBUG: starting scrape_1700_to_json, output:", output_path)

    html = fetch_html(MENU_URL)
    soup = BeautifulSoup(html, "html.parser")

    title = soup.title.get_text(strip=True) if soup.title else "(no title)"
    print("DEBUG: page title:", title)

    now = datetime.now(timezone.utc).isoformat()

    beers: list[BeerRecord] = []

    # The page structure (at least currently) uses:
    # - h2 for tap group headings (e.g., "Air Force Taps - Light / Lager")
    # - h3 for each beer line
    current_group = "On Tap"

    h2_h3 = soup.find_all(["h2", "h3"])
    print("DEBUG: found", len(h2_h3), "<h2>/<h3> headings")

    for node in h2_h3:
        if not isinstance(node, Tag):
            continue

        if node.name == "h2":
            grp = node.get_text(" ", strip=True)
            grp = " ".join(grp.split())
            if grp:
                current_group = grp
            continue

        if node.name != "h3":
            continue

        h3_text = node.get_text(" ", strip=True)
        h3_text = " ".join(h3_text.split())
        if not h3_text:
            continue

        name, style = parse_beer_heading(h3_text)

        # Find the next meaningful text after this h3 which contains ABV/IBU/producer
        abv = None
        ibu = None
        producer = BREWERY_NAME

        info_text = None
        for sib in node.next_siblings:
            if isinstance(sib, Tag) and sib.name in {"h2", "h3"}:
                break
            if isinstance(sib, Tag):
                t = sib.get_text(" ", strip=True)
            else:
                t = str(sib).strip()
            t = " ".join(t.split())
            if t:
                info_text = t
                break

        if info_text:
            abv, ibu, producer = parse_abv_ibu_producer(info_text)

        rec = BeerRecord(
            id=slugify(f"{BREWERY_NAME}-{name}-{current_group}"),
            breweryName=BREWERY_NAME,
            breweryCity=BREWERY_CITY,
            producerName=producer,
            name=name,
            style=style,
            abv=abv,
            ibu=ibu,
            tapGroup=current_group,
            category="on_tap",
            sourceUrl=MENU_URL,
            lastScraped=now,
        )
        beers.append(rec)

    print("Parsed", len(beers), "beers from 1700 menu")
    for b in beers[:10]:
        print(
            "DEBUG 1700:",
            b.tapGroup,
            "|",
            b.name,
            "| style=",
            b.style,
            "| abv=",
            b.abv,
            "| ibu=",
            b.ibu,
            "| producer=",
            b.producerName,
        )

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump([asdict(b) for b in beers], f, indent=2, ensure_ascii=False)

    print("DEBUG: finished writing", output_path)


if __name__ == "__main__":
    scrape_1700_to_json()
