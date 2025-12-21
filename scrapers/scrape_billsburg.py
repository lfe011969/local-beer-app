import re
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

TAPLIST_URL = "https://taplist.io/taplist-739667"

# Billsburg also maintains a "Beers on Tap" page that usually lists both
# style and ABV for every beer. Taplist sometimes omits style (and our
# parser historically missed ABV due to formatting), so we optionally use
# this page to enrich missing fields.
BILLSBURG_ON_TAP_URL = "https://billsburg.com/beers-on-tap/"

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
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.text


def build_name_key(name: str) -> str:
    """Normalize beer names for fuzzy matching across sources."""
    return re.sub(r"[^a-z0-9]+", "", name.lower()).strip()


def parse_abv(line: str) -> float | None:
    """Parse ABV.

    Taplist commonly formats ABV as "ABV 5.3%" (not just "5.3%").
    Billsburg's own site may show just the percent value.
    """
    line = line.strip()
    m = re.search(r"\bABV\s*(\d+(?:\.\d+)?)\s*%\b", line, flags=re.IGNORECASE)
    if m:
        return float(m.group(1))

    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*%", line)
    if m:
        return float(m.group(1))

    return None


def parse_ibu(line: str) -> int | None:
    """Parse IBU.

    Taplist usually formats IBU as "IBU 22". We only accept lines that
    explicitly contain "IBU" to avoid accidentally treating SRM (e.g.,
    "SRM 2") as IBU.
    """
    line = line.strip()
    m = re.search(r"\bIBU\s*(\d{1,3})\b", line, flags=re.IGNORECASE)
    if not m:
        return None

    val = int(m.group(1))
    if 1 <= val <= 150:
        return val
    return None


def enrich_from_billsburg_site(beers: list["BeerRecord"]) -> None:
    """Fill missing style/abv using Billsburg's own "Beers on Tap" page.

    When the beer list is present in HTML text, it often appears as triplets:
    Name -> Style -> ABV (e.g., "6.7%"), which we can parse fairly robustly.
    """
    try:
        html = fetch_html(BILLSBURG_ON_TAP_URL)
    except Exception as e:
        print("DEBUG: Billsburg site enrichment fetch failed:", e)
        return

    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    mapping: dict[str, dict] = {}

    # Find ABV lines and grab the two preceding lines as (style, name)
    for idx, ln in enumerate(lines):
        abv = parse_abv(ln)
        if abv is None or idx < 2:
            continue

        style = lines[idx - 1]
        name = lines[idx - 2]

        # Sanity filters to reduce false positives
        if len(name) > 80 or len(style) > 60:
            continue
        if any(x in style.lower() for x in ["last updated", "powered by", "taplist", "menu"]):
            continue
        if any(x in name.lower() for x in ["last updated", "powered by", "taplist", "menu"]):
            continue

        key = build_name_key(name)
        if key:
            mapping[key] = {"style": style, "abv": abv}

    if not mapping:
        print("DEBUG: Billsburg site enrichment found no ABV triplets; skipping")
        return

    filled = 0
    for b in beers:
        key = build_name_key(b.name)
        m = mapping.get(key)
        if not m:
            continue

        if b.style is None and m.get("style"):
            b.style = m["style"]
            filled += 1
        if b.abv is None and m.get("abv") is not None:
            b.abv = m["abv"]
            filled += 1

    print(f"DEBUG: Billsburg site enrichment filled {filled} field(s)")


def parse_billsburg_page(html: str):
    soup = BeautifulSoup(html, "html.parser")
    now = datetime.now(timezone.utc).isoformat()

    text = soup.get_text("\n", strip=True)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    beers: list[BeerRecord] = []
    current_group = "On Tap"
    current_category = "on_tap"

    def is_brewery_line(line: str) -> bool:
        return line.strip().lower() == BREWERY_NAME.lower()

    def is_noise(line: str) -> bool:
        low = line.lower()
        return (
            low.startswith("last updated:")
            or low.startswith("powered by")
            or "powered by taplist" in low
            or low == "taplist.io"
            or "instant digital menus" in low
        )

    for i in range(len(lines)):
        line = lines[i]

        if line.lower().startswith("coming soon"):
            current_group = "Coming Soon"
            current_category = "coming_soon"
            continue

        if not is_brewery_line(line):
            continue

        # Beer name = closest valid line above "Billsburg Brewery"
        j = i - 1
        beer_name = None
        while j >= 0:
            prev = lines[j]
            if is_noise(prev) or prev.lower().startswith("coming soon") or "current menu" in prev.lower():
                j -= 1
                continue
            beer_name = prev
            break

        if not beer_name:
            continue

        style = None
        abv = None
        ibu = None

        # Scan forward until next beer block or section change
        k = i + 1
        while k < len(lines):
            nxt = lines[k]

            # Stop if next beer starts
            if k + 1 < len(lines) and is_brewery_line(lines[k + 1]):
                break
            if nxt.lower().startswith("coming soon"):
                break
            if is_noise(nxt):
                break
            if is_brewery_line(nxt):
                break

            # Extract ABV / IBU
            val_abv = parse_abv(nxt)
            if val_abv is not None:
                abv = val_abv
                k += 1
                continue

            val_ibu = parse_ibu(nxt)
            if val_ibu is not None:
                ibu = val_ibu
                k += 1
                continue

            # Ignore SRM lines (not stored in schema)
            if re.search(r"\bSRM\b", nxt, flags=re.IGNORECASE):
                k += 1
                continue

            # Style: must not be ABV/IBU/SRM and must not contain '%'
            upper = nxt.upper()
            if style is None:
                if ("ABV" not in upper) and ("IBU" not in upper) and ("SRM" not in upper):
                    if "%" in nxt:
                        pass
                    elif re.fullmatch(r"\d{1,3}", nxt.strip()):
                        pass
                    elif 2 <= len(nxt) <= 40:
                        style = nxt

            k += 1

        beers.append(
            BeerRecord(
                id=slugify(f"{BREWERY_NAME}-{beer_name}"),
                breweryName=BREWERY_NAME,
                breweryCity=BREWERY_CITY,
                producerName=BREWERY_NAME,
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

    # If Taplist omitted fields, try to enrich from Billsburg's own page.
    if any((b.abv is None) or (b.style is None) for b in beers):
        enrich_from_billsburg_site(beers)

    return beers


def scrape_billsburg_to_json(out: str = "beers_billsburg.json"):
    html = fetch_html(TAPLIST_URL)
    beers = parse_billsburg_page(html)
    with open(out, "w", encoding="utf-8") as f:
        json.dump([asdict(b) for b in beers], f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    scrape_billsburg_to_json()
