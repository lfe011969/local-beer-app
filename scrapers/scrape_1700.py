import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional, List

import requests
from bs4 import BeautifulSoup, Tag


VENUE_URL = "https://untappd.com/v/1700-brewing/10975639"

BREWERY_NAME = "1700 Brewing"
BREWERY_CITY = "Newport News"


@dataclass
class BeerRecord:
    id: str
    breweryName: str          # venue name (where it’s on tap)
    breweryCity: str
    producerName: str         # brewery that made it (collab/guest taps)
    name: str
    style: Optional[str]
    abv: Optional[float]
    ibu: Optional[int]
    tapGroup: str             # section heading on the menu
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


def strip_tap_number(name: str) -> str:
    # "2. Scud Light" -> "Scud Light"
    name = " ".join(name.split())
    name = re.sub(r"^\s*\d+\.\s*", "", name)
    return name.strip()


def parse_style_from_h5(h5: Tag) -> Optional[str]:
    """
    Untappd venue menu typically looks like:
      <h5> <a> 2. Scud Light </a> Lager - American </h5>

    So: style is the text of the h5 minus the <a> text.
    """
    a = h5.find("a")
    full = h5.get_text(" ", strip=True)
    full = " ".join(full.split())

    if a:
        a_text = a.get_text(" ", strip=True)
        a_text = " ".join(a_text.split())
        # remove linked name portion, remaining becomes style
        style = full.replace(a_text, "", 1).strip()
        return style or None

    # Some lines may not have a link; try to split by "  " patterns won't survive,
    # so we fall back to a few known tokens (rare).
    return None


def parse_abv_ibu_producer(h6: Tag):
    """
    Example h6 text:
      "4% ABV • N/A IBU • 1700 Brewing •"
      "5.7% ABV • 45 IBU • 1700 Brewing •"
    Producer is usually a link inside h6.
    """
    text = h6.get_text(" ", strip=True)
    text = " ".join(text.split())

    # producer often inside <a>
    producer = None
    a = h6.find("a")
    if a:
        producer = " ".join(a.get_text(" ", strip=True).split())

    # ABV
    abv = None
    m = re.search(r"(\d+(?:\.\d+)?)\s*%\s*ABV", text, flags=re.I)
    if m:
        try:
            abv = float(m.group(1))
        except ValueError:
            abv = None

    # IBU
    ibu = None
    m = re.search(r"(\d+)\s*IBU", text, flags=re.I)
    if m:
        try:
            ibu = int(m.group(1))
        except ValueError:
            ibu = None

    # If producer link missing, try parse from bullets
    if not producer:
        parts = [p.strip() for p in text.split("•") if p.strip()]
        # pick last part that isn't ABV/IBU
        for p in reversed(parts):
            if re.search(r"ABV", p, flags=re.I):
                continue
            if re.search(r"IBU", p, flags=re.I):
                continue
            # ignore "(3.84)" etc if present
            if re.fullmatch(r"\(?\d+(?:\.\d+)?\)?", p):
                continue
            producer = p
            break

    if not producer:
        producer = BREWERY_NAME

    return abv, ibu, producer


def scrape_1700_to_json(output_path: str = "beers_1700.json"):
    print("DEBUG: starting scrape_1700_to_json (Untappd Venue Menu)")
    print("DEBUG: url:", VENUE_URL)
    print("DEBUG: output:", output_path)

    html = fetch_html(VENUE_URL)
    soup = BeautifulSoup(html, "html.parser")

    title = soup.title.get_text(strip=True) if soup.title else "(no title)"
    print("DEBUG: page title:", title)

    now = datetime.now(timezone.utc).isoformat()

    # We’ll walk through h4 (group), h5 (beer), h6 (stats) in order.
    nodes: List[Tag] = soup.find_all(["h4", "h5", "h6"])
    print("DEBUG: found", len(nodes), "<h4>/<h5>/<h6> tags")

    beers: List[BeerRecord] = []
    current_group = "Menu"
    pending = None  # dict with name/style/group while waiting for h6

    for node in nodes:
        if not isinstance(node, Tag):
            continue

        if node.name == "h4":
            # group heading like "Air Force Taps-Light/Lager (4 Items)"
            grp = node.get_text(" ", strip=True)
            grp = " ".join(grp.split())
            # remove "(X Items)"
            grp = re.sub(r"\(\s*\d+\s*Items?\s*\)\s*$", "", grp).strip()
            if grp:
                current_group = grp
            continue

        if node.name == "h5":
            # beer line
            a = node.find("a")
            full = node.get_text(" ", strip=True)
            full = " ".join(full.split())

            if a:
                raw_name = a.get_text(" ", strip=True)
                raw_name = " ".join(raw_name.split())
                name = strip_tap_number(raw_name)
                style = parse_style_from_h5(node)
            else:
                # fallback (rare): whole h5 is name (no style)
                name = full.strip()
                style = None

            if not name:
                continue

            pending = {
                "name": name,
                "style": style,
                "group": current_group,
            }
            continue

        if node.name == "h6" and pending:
            abv, ibu, producer = parse_abv_ibu_producer(node)

            rec = BeerRecord(
                id=slugify(f"{BREWERY_NAME}-{pending['name']}-{pending['group']}"),
                breweryName=BREWERY_NAME,
                breweryCity=BREWERY_CITY,
                producerName=producer,
                name=pending["name"],
                style=pending["style"],
                abv=abv,
                ibu=ibu,
                tapGroup=pending["group"],
                category="on_tap",
                sourceUrl=VENUE_URL,
                lastScraped=now,
            )
            beers.append(rec)
            pending = None

    print("Parsed", len(beers), "beers from 1700 venue menu")
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
