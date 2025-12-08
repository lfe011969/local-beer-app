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
    category: str  # "on_tap", "guest_na", etc.
    sourceUrl: str
    lastScraped: str


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"['’]", "", text)      # remove apostrophes
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text


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


def parse_abv_ibu_and_style_from_line(line: str) -> tuple[float | None, int | None, str | None, str | None]:
    """
    Given a line like:
      '5.3% ABV | 22 IBU | 1700 Brewing'
      '(Honey Bourbon Barrel Coffee) • Belgian Golden Strong | 9.2% ABV | N/A IBU | 1700 Brewing'
      '(Orange, Passion Fruit, Guava) • 4% ABV | 10 IBU | 1700 Brewing'
    return (abv, ibu, style_from_line, producer_name)
    """
    # Producer (last chunk after '|')
    producer_name = None
    chunks = [c.strip() for c in line.split("|")]
    if chunks:
        candidate = chunks[-1].strip()
        if candidate:
            producer_name = candidate

    # ABV
    abv = None
    m_abv = re.search(r"(\d+(?:\.\d+)?)\s*%?\s*ABV", line, re.IGNORECASE)
    if m_abv:
        abv = float(m_abv.group(1))

    # IBU
    ibu = None
    m_ibu = re.search(r"(\d+|N/A)\s*IBU", line, re.IGNORECASE)
    if m_ibu:
        val = m_ibu.group(1).upper()
        if val != "N/A":
            ibu = int(val)

    # Style between "•" and "|" if present
    style_from_line = None
    if "•" in line and "|" in line:
        after_bullet = line.split("•", 1)[1]
        style_segment = after_bullet.split("|", 1)[0].strip()
        if style_segment:
            style_from_line = style_segment

    return abv, ibu, style_from_line, producer_name


def parse_beer_header(text: str) -> tuple[str, str | None]:
    """
    '1. Plain Old Lager (P.O.L.), Lager - Vienna'
    '12. Minute of Angle MOA'
    -> (beer_name, style_from_header_or_none)
    """
    text = text.strip()
    m = re.match(r"^\d+\.\s*(.+)$", text)
    if m:
        text = m.group(1).strip()

    name = text
    style = None

    if "," in text:
        name_part, style_part = text.split(",", 1)
        name = name_part.strip()
        style = style_part.strip()

    return name, style


def parse_1700_page(html: str) -> list[BeerRecord]:
    soup = BeautifulSoup(html, "html.parser")
    beers: list[BeerRecord] = []
    now_str = datetime.now(tz=timezone.utc).isoformat()

    # DEBUG: see how many h2/h3 we actually get
    headings = soup.find_all(["h2", "h3"])
    print(f"DEBUG: found {len(headings)} <h2>/<h3> headings on page")
    for h in headings[:10]:
        print("DEBUG heading:", h.name, "-", h.get_text(" ", strip=True)[:80])

    current_tap_group = None
    current_category = "on_tap"

    # Walk all h2 and h3 in document order
    for node in soup.find_all(["h2", "h3"]):
        text = node.get_text(" ", strip=True)

        if node.name == "h2":
            # We're only interested in the tap group sections
            if any(keyword in text for keyword in [
                "Taps -",       # Air Force / Army / Marine / Coast Guard
                "Spec Ops",
                "Odd Stuff",
                "Reserves -"
            ]):
                current_tap_group = text
                current_category = "guest_na" if "Reserves" in text else "on_tap"
            else:
                # e.g. 'Menus' etc – ignore
                continue

        elif node.name == "h3":
            if not current_tap_group:
                # h3 before a tap group – ignore just in case
                continue

            header_text = text
            beer_name, style_from_header = parse_beer_header(header_text)

                    header_text = text
        beer_name, style_from_header = parse_beer_header(header_text)

        # Find the next text snippet in the document that contains both "ABV" and "IBU".
        # This is usually in a <p> or <strong> right after the h3, but using find_next
        # is more robust than walking siblings manually.
        stats_node = node.find_next(
            string=lambda t: isinstance(t, NavigableString) and "ABV" in t and "IBU" in t
        )

        if not stats_node:
            # No stats line – skip this beer
            continue

        abv_line = stats_node.strip()
        abv, ibu, style_from_line, producer_name = parse_abv_ibu_and_style_from_line(abv_line)

        style = style_from_header or style_from_line
        if not producer_name:
            producer_name = BREWERY_NAME

        beer_id = f"{slugify(BREWERY_NAME)}-{slugify(beer_name)}"

        record = BeerRecord(
            id=beer_id,
            breweryName=BREWERY_NAME,
            breweryCity=BREWERY_CITY,
            producerName=producer_name,
            name=beer_name,
            style=style,
            abv=abv,
            ibu=ibu,
            tapGroup=current_tap_group,
            category=current_category,
            sourceUrl=DRINK_MENU_URL,
            lastScraped=now_str,
        )
        beers.append(record)


            beer_id = f"{slugify(BREWERY_NAME)}-{slugify(beer_name)}"

            record = BeerRecord(
                id=beer_id,
                breweryName=BREWERY_NAME,
                breweryCity=BREWERY_CITY,
                producerName=producer_name,
                name=beer_name,
                style=style,
                abv=abv,
                ibu=ibu,
                tapGroup=current_tap_group,
                category=current_category,
                sourceUrl=DRINK_MENU_URL,
                lastScraped=now_str,
            )
            beers.append(record)

    print(f"Parsed {len(beers)} beers from 1700")
    return beers


def scrape_1700_to_json(output_path: str = "beers_1700.json") -> None:
    html = fetch_html(DRINK_MENU_URL)
    beers = parse_1700_page(html)
    data = [asdict(b) for b in beers]
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Wrote {len(beers)} beers to {output_path}")


if __name__ == "__main__":
    scrape_1700_to_json()
