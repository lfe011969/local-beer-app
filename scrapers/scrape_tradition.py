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


def parse_abv(text: str) -> float | None:
    # Accept "5%", "5.9%", "5.9 %"
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", text.strip())
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def clean_line(s: str) -> str:
    s = s.strip()
    s = re.sub(r"\s+", " ", s)
    return s


def looks_like_style(s: str) -> bool:
    s2 = s.strip()
    if not s2:
        return False
    low = s2.lower()
    if low in ICON_WORDS:
        return False
    if s2 == "|":
        return False
    if "%" in s2:
        return False
    # keep it sane length
    return 2 <= len(s2) <= 40


def collect_text_until_next_h2(h2: Tag) -> list[str]:
    """
    Collect readable text lines following this beer's <h2> heading
    until the next <h2> appears.
    """
    lines: list[str] = []
    for sib in h2.next_siblings:
        if isinstance(sib, Tag) and sib.name == "h2":
            break

        # include text from tags; ignore empty
        if isinstance(sib, Tag):
            txt = sib.get_text("\n", strip=True)
        else:
            txt = str(sib).strip()

        if not txt:
            continue

        for ln in txt.splitlines():
            ln = clean_line(ln)
            if not ln:
                continue
            # skip legend words if they appear in this block
            if ln.lower() in ICON_WORDS:
                continue
            lines.append(ln)

    return lines


def parse_tradition(html: str) -> list[BeerRecord]:
    soup = BeautifulSoup(html, "html.parser")
    now = datetime.now(timezone.utc).isoformat()

    title = soup.title.get_text(strip=True) if soup.title else "(no title)"
    print("DEBUG: page title:", title)

    # Find the "What's On Tap" header <h2>
    start_h2 = None
    for h2 in soup.find_all("h2"):
        if h2.get_text(" ", strip=True).strip().lower() == "what's on tap":
            start_h2 = h2
            break

    if not start_h2:
        print("WARNING: Could not find 'What's On Tap' h2")
        return []

    # We stop at the "WEEKLY LINEUP" header
    end_h2 = None
    for h2 in soup.find_all("h2"):
        if h2.get_text(" ", strip=True).strip().upper() == "WEEKLY LINEUP":
            end_h2 = h2
            break

    # Collect all beer <h2> headings between start and end.
    beer_h2s: list[Tag] = []
    in_section = False
    for h2 in soup.find_all("h2"):
        txt = h2.get_text(" ", strip=True).strip()
        if h2 == start_h2:
            in_section = True
            continue
        if end_h2 and h2 == end_h2:
            break
        if in_section:
            # Beer headings on this page are h2 with an <a> inside (beer detail link)
            a = h2.find("a")
            if a and a.get_text(strip=True):
                beer_h2s.append(h2)

    beers: list[BeerRecord] = []

    for h2 in beer_h2s:
        a = h2.find("a")
        name = a.get_text(strip=True) if a else h2.get_text(" ", strip=True)

        # Now parse following block for style/abv
        lines = collect_text_until_next_h2(h2)

        abv = None
        style = None

        # ABV: first percent we see
        for ln in lines:
            val = parse_abv(ln)
            if val is not None:
                abv = val
                break

        # Style: first "style-like" line (often appears before "|")
        for ln in lines:
            if looks_like_style(ln):
                style = ln
                break

        beers.append(
            BeerRecord(
                id=slugify(f"{BREWERY_NAME}-{name}"),
                breweryName=BREWERY_NAME,
                breweryCity=BREWERY_CITY,
                producerName=BREWERY_NAME,
                name=name,
                style=style,
                abv=abv,
                ibu=None,  # site doesn't consistently provide IBU here
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
