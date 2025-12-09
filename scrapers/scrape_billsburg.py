import re
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

# Public current menu for Billsburg on Taplist.io
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


def parse_stats_from_line(line: str):
    """
    Extract ABV / IBU from a line like:
      'ABV 5.3%'
      'IBU 15'
      'ABV 5.3% IBU 15'
    """
    abv = None
    ibu = None

    # ABV: look for something like '5.3%' or '5.3 %'
    m_abv = re.search(r"(\d+(?:\.\d+)?)\s*%?", line, re.IGNORECASE)
    if "ABV" in line.upper() and m_abv:
        abv = float(m_abv.group(1))

    # IBU: look for '15 IBU' or 'IBU 15'
    m_ibu = re.search(r"(\d+)\s*IBU|IBU\s*(\d+)", line, re.IGNORECASE)
    if "IBU" in line.upper() and m_ibu:
        num = m_ibu.group(1) or m_ibu.group(2)
        ibu = int(num)

    return abv, ibu


def parse_billsburg_page(html: str):
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    beers: list[BeerRecord] = []
    now = datetime.now(timezone.utc).isoformat()

    current_group = "On Tap"
    current_category = "on_tap"

    # When we hit "Coming Soon", everything after that becomes coming_soon
    for idx, line in enumerate(lines):
        if line.startswith("Coming Soon"):
            current_group = "Coming Soon"
            current_category = "coming_soon"
            # We don't break; we only use this later when building records
            break

    i = 0
    while i < len(lines) - 1:
        name_line = lines[i]
        next_line = lines[i + 1]

        # Heuristics to detect a beer block:
        if (
            next_line == BREWERY_NAME
            and "Last Updated:" not in name_line
            and "Taplist.io" not in name_line
            and "Powered by" not in name_line
            and not name_line.startswith("#")
        ):
            beer_name = name_line
            producer_name = BREWERY_NAME
            abv = None
            ibu = None
            style = None  # Taplist doesn't expose style here as plain text

            # Look forward a few lines for ABV/IBU
            j = i + 2
            while j < len(lines) and j <= i + 8:
                line_j = lines[j]

                # Stop if we hit the next beer (name followed by brewery)
                if (
                    j + 1 < len(lines)
                    and lines[j + 1] == BREWERY_NAME
                ):
                    break

                # Detect ABV / IBU lines
                if "ABV" in line_j.upper() or "IBU" in line_j.upper():
                    abv_j, ibu_j = parse_stats_from_line(line_j)
                    if abv_j is not None:
                        abv = abv_j
                    if ibu_j is not None:
                        ibu = ibu_j

                j += 1

            beer_id = slugify(f"{BREWERY_NAME}-{beer_name}")

            beers.append(
                BeerRecord(
                    id=beer_id,
                    breweryName=BREWERY_NAME,
                    breweryCity=BREWERY_CITY,
                    producerName=producer_name,
                    name=beer_name,
                    style=style,
                    abv=abv,
                    ibu=ibu,
                    tapGroup=current_group,
                    category=current_category,
                    sourceUrl=TAPLIST_URL,
                    lastScraped=now,
                )
            )

            # Jump forward to continue after this beer block
            i = j
        else:
            i += 1

    print("Parsed", len(beers), "Billsburg beers")
    # For debugging, show a few with stats
    for b in beers[:5]:
        print("DEBUG Billsburg:", b.name, "ABV=", b.abv, "IBU=", b.ibu)

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
