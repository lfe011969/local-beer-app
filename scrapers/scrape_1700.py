import re
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup, NavigableString

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
    category: str          # "on_tap" or "guest_na"
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
    for h in headings[:10]:
        print("DEBUG heading:", h.name, "-", h.get_text(" ", strip=True)[:80])

    current_group = None
    current_category = "on_tap"

    for node in headings:
        text = node.get_text(" ", strip=True)

        # tap group headings
        if node.name == "h2":
            if (
                "Taps -" in text
                or "Spec Ops" in text
                or "Odd Stuff" in text
                or "Reserves -" in text
            ):
                current_group = text
                current_category = "guest_na" if "Reserves" in text else "on_tap"
            else:
                continue

        # beer entries
        elif node.name == "h3":
            if not current_group:
                continue

            beer_name, style_from_header = parse_header(text)

            stats_node = node.find_next(
                string=lambda t: isinstance(t, NavigableString)
                and "ABV" in t
                and "IBU" in t
            )
            if not stats_node:
                continue

            stats_line = stats_node.strip()
            abv, ibu, style_from_line, producer = parse_stats_line(stats_line)
            style = style_from_header or style_from_line
            if not producer:
                producer = BREWERY_NAME

            beer_id = slugify(f"{BREWERY_NAME}-{beer_name}")

            beers.append(
                BeerRecord(
                    id=beer_id,
                    breweryName=BREWERY_NAME,
                    breweryCity=BREWERY_CITY,
                    producerName=producer,
                    name=beer_name,
                    style=style,
                    abv=abv,
                    ibu=ibu,
                    tapGroup=current_group,
                    category=current_category,
                    sourceUrl=DRINK_MENU_URL,
                    lastScraped=now,
                )
            )

    print("Parsed", len(beers), "beers from 1700")
    return beers


def scrape_1700_to_json(out: str = "beers_1700.json"):
    print("DEBUG: starting scrape_1700_to_json, output:", out)
    html = fetch_html(DRINK_MENU_URL)
    beers = parse_1700_page(html)
    print("DEBUG: about to write", len(beers), "beers")
    data = [asdict(b) for b in beers]
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print("DEBUG: finished writing", out)


if __name__ == "__main__":
    scrape_1700_to_json()
