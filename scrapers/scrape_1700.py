import re
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup


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
    # Strip leading '1.' / '12.' / etc
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

    # Get all H2 sections under "Our Drinks"
    # We'll treat every h2 as a tap group title, then walk until the next h2.
    beers: list[BeerRecord] = []

    # To be safe, find the "Our Drinks" heading and then look for h2 after it
    our_drinks_h1 = None
    for h1 in soup.find_all(["h1", "h2"]):
        if "Our Drinks" in h1.get_text(strip=True):
            our_drinks_h1 = h1
            break

    if our_drinks_h1 is None:
        raise RuntimeError("Couldn't find 'Our Drinks' anchor in page")

    # From that anchor, collect subsequent h2s as tap groups
    tap_groups = []
    node = our_drinks_h1.find_next_sibling()
    while node:
        if getattr(node, "name", None) == "h2":
            tap_groups.append(node)
        node = node.next_sibling

    now_str = datetime.now(tz=timezone.utc).isoformat()

    for h2 in tap_groups:
        tap_group = h2.get_text(" ", strip=True)

        # classify category (simple rule: Reserves = guest/NA, others = on_tap)
        if "Reserves" in tap_group:
            category = "guest_na"
        else:
            category = "on_tap"

        # Walk siblings until next h2 to find h3 beer headers
        node = h2.find_next_sibling()
        while node and not (getattr(node, "name", None) == "h2"):
            if getattr(node, "name", None) == "h3":
                header_text = node.get_text(" ", strip=True)
                beer_name, style_from_header = parse_beer_header(header_text)

                # Find ABV/IBU line and any description immediately associated
                abv_line = None
                description = None

                info_node = node.find_next_sibling()
                while info_node and getattr(info_node, "name", None) not in ("h2", "h3"):
                    text = info_node.get_text(" ", strip=True) if hasattr(info_node, "get_text") else str(info_node).strip()
                    if text:
                        if "ABV" in text and "IBU" in text and abv_line is None:
                            abv_line = text
                        else:
                            # could be description; we only save first non-ABV line
                            if description is None:
                                description = text
                    info_node = info_node.next_sibling

                if not abv_line:
                    # If we somehow didn't find an ABV/IBU line, skip this beer
                    node = node.next_sibling
                    continue

                abv, ibu, style_from_line, producer_name = parse_abv_ibu_and_style_from_line(abv_line)

                # Decide final style
                style = style_from_header or style_from_line

                # Producer default to brewery if not parsed
                if not producer_name:
                    producer_name = BREWERY_NAME

                # Create an id; include brewery + beer name
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
