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
        "User-Agent": "LocalBeerAppBot/0.1 (contact: youremail@example.com)"
    }
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.text


def parse_abv_ibu_and_style_from_line(line: str) -> tuple[float | None, int | None, str | None, str | None]:
    """
    Given a line like:
      '5.3% ABV | 22 IBU | 1700 Brewing'
      '(Honey Bourbon Barrel Coffee) • Belgian Golden Strong | 9.2% ABV | N/A IBU | 1700 Brewing'
    return (abv, ibu, style_from_line, producer_name)
    """
    # Extract producer name (last chunk after |)
    producer_name = None
    chunks = [c.strip() for c in line.split("|")]
    if chunks:
        producer_name_guess = chunks[-1].strip()
        if producer_name_guess:
            producer_name = producer_name_guess

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

    # Style (if present between '•' and '|' or in the middle)
    style_from_line = None
    if "•" in line and "|" in line:
        after_bullet = line.split("•", 1)[1]
        style_segment = after_bullet.split("|", 1)[0].strip()
        if style_segment:
            style_from_line = style_segment

    return abv, ibu, style_from_line, producer_name


def parse_beer_header(text: str) -> tuple[str, str | None]:
    """
    Turn something like:
        '1. Plain Old Lager (P.O.L.), Lager - Vienna'
        '12. Minute of Angle MOA'
    into (name, style_from_header_or_none)
    """
    text = text.strip()
    m = re.match(r"^\d+\.\s*(.+)$", text)
    if m:
        text = m.group(1).strip()

    name = text
    style = None

    # If there's a comma, assume 'Name, Style'
    if "," in text:
        name_part, style_part = text.split(",", 1)
        name = name_part.strip()
        style = style_part.strip()

    return name, style


def parse_1700_page(html: str) -> list[BeerRecord]:
    soup = BeautifulSoup(html, "html.parser")
    beers: list[BeerRecord] = []
    now_str = datetime.now(tz=timezone.utc).isoformat()

    # Get all tap group headings (h2) on the page.
    tap_groups = soup.find_all("h2")
    print(f"Found {len(tap_groups)} tap groups")  # helpful debug

    for h2 in tap_groups:
        tap_group = h2.get_text(" ", strip=True)
        if not tap_group:
            continue

        # classify category (simple rule: Reserves = guest/NA, others = on_tap)
        if "Reserves" in tap_group:
            category = "guest_na"
        else:
            category = "on_tap"

        # Walk forward through siblings until we hit the next h2
        node = h2.next_sibling
        while node:
            if isinstance(node, Tag) and node.name == "h2":
                break  # next tap group

            if isinstance(node, Tag) and node.name == "h3":
                header_text = node.get_text(" ", strip=True)
                beer_name, style_from_header = parse_beer_header(header_text)

                # Find ABV/IBU line after the h3
                abv_line = None
                info_node = node.next_sibling
                while info_node and not (isinstance(info_node, Tag) and info_node.name in ("h2", "h3")):
                    text = ""
                    if isinstance(info_node, Tag):
                        text = info_node.get_text(" ", strip=True)
                    elif isinstance(info_node, NavigableString):
                        text = str(info_node).strip()

                    if text:
                        if "ABV" in text and "IBU" in text and abv_line is None:
                            abv_line = text
                            break
                    info_node = info_node.next_sibling

                if not abv_line:
                    print(f"Skipping beer with no ABV/IBU line: {beer_name}")
                    node = node.next_sibling
                    continue

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
                    tapGroup=tap_group,
                    category=category,
                    sourceUrl=DRINK_MENU_URL,
                    lastScraped=now_str,
                )
                beers.append(record)

            node = node.next_sibling

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
