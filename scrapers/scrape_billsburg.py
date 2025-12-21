import re
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

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
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.text


def parse_abv(line: str) -> float | None:
    line = line.strip()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*%", line)
    if m:
        return float(m.group(1))
    return None


def parse_ibu(line: str) -> int | None:
    line = line.strip()
    m = re.fullmatch(r"(\d{1,3})", line)
    if m:
        val = int(m.group(1))
        if 1 <= val <= 150:
            return val
    return None




def parse_billsburg_page(html: str):
    soup = BeautifulSoup(html, "html.parser")
    now = datetime.now(timezone.utc).isoformat()

    text = soup.get_text("\n", strip=True)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    title = soup.title.get_text(strip=True) if soup.title else "(no title)"
    print("DEBUG: page title:", title)
    print("DEBUG: total lines:", len(lines))

    beers: list[BeerRecord] = []

    current_group = "On Tap"
    current_category = "on_tap"

    def is_brewery_line(line: str) -> bool:
        return line.strip().lower() == BREWERY_NAME.lower()

    def is_noise(line: str) -> bool:
        low = line.lower()
        return (
            low.startswith("last updated:")
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

            # Stop if next beer starts (some line followed by brewery line)
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


            # Style: must not be ABV/IBU/SRM and must not contain '%'
            upper = nxt.upper()
            if style is None:
                if ("ABV" not in upper) and ("IBU" not in upper) and ("SRM" not in upper):
                    # Don't treat % lines or pure numbers as style
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

    print("Parsed", len(beers), "Billsburg beers")
    for b in beers[:12]:
        print("DEBUG Billsburg:", b.name, "ABV=", b.abv, "IBU=", b.ibu, "Style=", b.style, "Group=", b.tapGroup)

    return beers


def scrape_billsburg_to_json(out: str = "beers_billsburg.json"):
    print("DEBUG: starting scrape_billsburg_to_json, output:", out)
    html = fetch_html(TAPLIST_URL)
    beers = parse_billsburg_page(html)
    print("DEBUG: about to write", len(beers), "Billsburg beers")
    with open(out, "w", encoding="utf-8") as f:
        json.dump([asdict(b) for b in beers], f, indent=2, ensure_ascii=False)
    print("DEBUG: finished writing", out)


if __name__ == "__main__":
    scrape_billsburg_to_json()
