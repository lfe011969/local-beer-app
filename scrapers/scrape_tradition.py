import re
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup, Tag

SOURCE_URL = "https://traditionbrewing.com/location/taproom/"

BREWERY_NAME = "Tradition Brewing Company"
BREWERY_CITY = "Newport News"

ICON_WORDS = {"draft", "can", "bottle", "growler", "crowler"}


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
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.text


def extract_abv(text: str) -> float | None:
    # Finds first "6.5%" anywhere in a block
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def normalize_space(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def looks_like_style(s: str) -> bool:
    if not s:
        return False
    low = s.lower()
    if low in ICON_WORDS:
        return False
    if "%" in s:
        return False
    if s == "|":
        return False
    # keep it sane for a style name
    return 2 <= len(s) <= 45


def collect_block_text_until_next_h2(h2: Tag) -> str:
    """
    Walk forward in document order after this <h2> and collect meaningful text
    until the next <h2> is encountered.
    This handles nested WP containers that aren't direct siblings.
    """
    parts: list[str] = []

    started = False
    for el in h2.next_elements:
        if not started:
            started = True
            continue

        if isinstance(el, Tag):
            # Stop when we hit the next beer header
            if el.name == "h2":
                break

            # Skip non-content
            if el.name in {"script", "style", "noscript"}:
                continue

            # Grab text from common content tags
            if el.name in {"p", "div", "span", "li"}:
                txt = el.get_text(" ", strip=True)
                txt = normalize_space(txt)
                if not txt:
                    continue

                # Filter icon/legend noise if it appears
                if txt.lower() in ICON_WORDS:
                    continue

                parts.append(txt)

    # De-dupe while preserving order (WP layouts can repeat text)
    seen = set()
    deduped = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            deduped.append(p)

    return " \n ".join(deduped)


def extract_style_from_block(block_text: str) -> str | None:
    """
    Tradition often formats as: "Hazy IPA | 6.5%"
    If a '|' exists, style is typically left side of first pipe.
    """
    if not block_text:
        return None

    # Prefer "Style | ABV" pattern if present
    if "|" in block_text:
        left = block_text.split("|", 1)[0].strip()
        left = normalize_space(left)
        if looks_like_style(left):
            return left

    # Otherwise: find a short plausible style phrase from lines
    for line in block_text.splitlines():
        line = normalize_space(line)
        # Avoid grabbing large marketing text; focus on shorter phrases
        if looks_like_style(line) and len(line) <= 45:
            return line

    return None


def parse_tradition(html: str) -> list[BeerRecord]:
    soup = BeautifulSoup(html, "html.parser")
    now = datetime.now(timezone.utc).isoformat()

    title = soup.title.get_text(strip=True) if soup.title else "(no title)"
    print("DEBUG: page title:", title)

    # Find section bounds
    start_h2 = None
    end_h2 = None

    for h2 in soup.find_all("h2"):
        t = h2.get_text(" ", strip=True).strip()
        if t.lower() == "what's on tap":
            start_h2 = h2
        if t.upper() == "WEEKLY LINEUP":
            end_h2 = h2
            break

    if not start_h2:
        print("WARNING: Could not find 'What's On Tap'")
        return []

    # Collect beer h2s between start and end (beer headers are <h2><a>Beer</a></h2>)
    beer_h2s: list[Tag] = []
    in_section = False

    for h2 in soup.find_all("h2"):
        if h2 == start_h2:
            in_section = True
            continue
        if end_h2 and h2 == end_h2:
            break
        if not in_section:
            continue

        a = h2.find("a")
        if a and a.get_text(strip=True):
            beer_h2s.append(h2)

    beers: list[BeerRecord] = []

    print("DEBUG: found", len(beer_h2s), "candidate beer headings")

    for h2 in beer_h2s:
        a = h2.find("a")
        name = a.get_text(strip=True) if a else h2.get_text(" ", strip=True).strip()

        # Pull the associated block text for this beer
        block = collect_block_text_until_next_h2(h2)

        # Remove obvious junk that can appear in blocks
        block_clean = block
        block_clean = block_clean.replace("What's On Tap", "")
        block_clean = normalize_space(block_clean)

        abv = extract_abv(block_clean)
        style = extract_style_from_block(block_clean)

        beers.append(
            BeerRecord(
                id=slugify(f"{BREWERY_NAME}-{name}"),
                breweryName=BREWERY_NAME,
                breweryCity=BREWERY_CITY,
                producerName=BREWERY_NAME,
                name=name,
                style=style,
                abv=abv,
                ibu=None,  # not reliably provided on this page
                tapGroup="On Tap",
                category="on_tap",
                sourceUrl=SOURCE_URL,
                lastScraped=now,
            )
        )

    print("Parsed", len(beers), "Tradition beers")
    for b in beers[:12]:
        print("DEBUG Tradition:", b.name, "Style=", b.style, "ABV=", b.abv)

    return beers


def scrape_tradition_to_json(out: str = "beers_tradition.json"):
    print("DEBUG: starting scrape_tradition_to_json, output:", out)
    html = fetch_html(SOURCE_URL)
    beers = parse_tradition(html)
    with open(out, "w", encoding="utf-8") as f:
        json.dump([asdict(b) for b in beers], f, indent=2, ensure_ascii=False)
    print("DEBUG: finished writing", out)


if __name__ == "__main__":
    scrape_tradition_to_json()
