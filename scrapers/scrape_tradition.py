import re
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

SOURCE_URL = "https://traditionbrewing.com/location/taproom/"

BREWERY_NAME = "Tradition Brewing Company"
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


def parse_abv(line: str) -> float | None:
    # Accept "6.5%" or "6.5 %"
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*%\s*", line)
    if not m:
        return None
    return float(m.group(1))


def parse_tradition(html: str) -> list[BeerRecord]:
    soup = BeautifulSoup(html, "html.parser")
    now = datetime.now(timezone.utc).isoformat()

    # Turn page into normalized lines (this works well for this WordPress layout)
    text = soup.get_text("\n", strip=True)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    title = soup.title.get_text(strip=True) if soup.title else "(no title)"
    print("DEBUG: page title:", title)
    print("DEBUG: total lines:", len(lines))

    # Find the "What's On Tap" section and stop before "WEEKLY LINEUP"
    try:
        start = next(i for i, ln in enumerate(lines) if ln.lower() == "what's on tap")
    except StopIteration:
        print("WARNING: Could not find 'What's On Tap' section")
        return []

    # Some pages use "WEEKLY LINEUP" as the next major header after the list
    try:
        end = next(i for i, ln in enumerate(lines) if ln.strip().upper() == "WEEKLY LINEUP")
    except StopIteration:
        end = len(lines)

    section = lines[start:end]

    # Remove legend words that appear near the top of the taplist
    legend_words = {"draft", "can", "bottle", "growler", "crowler"}
    icon_words = {"draft", "can", "bottle", "growler", "crowler"}

    beers: list[BeerRecord] = []

    # Heuristic:
    # A beer block starts at a line that is the beer name.
    # Within the next few lines:
    #   - style is usually a short text line (e.g., "Hazy IPA", "Gose") before a "|" separator
    #   - abv is the percent line (e.g., "6.5%")
    #
    # We will:
    #   - treat any '%' line as ABV
    #   - treat the closest non-icon line before '|' as style
    #   - ignore legend/icon words and separators
    i = 0
    while i < len(section):
        ln = section[i]

        # Skip header/legend noise
        if ln.lower() in legend_words:
            i += 1
            continue

        # Many beer names appear as normal lines; we treat a line as a beer name if:
        # - It's not obviously a separator
        # - It's not the top headers
        if ln in {"Taproom", "Visit Us", "Location", "Hours"}:
            i += 1
            continue
        if ln.strip() in {"|", "* * *"}:
            i += 1
            continue

        beer_name = ln

        # Look ahead up to ~12 lines for style/abv until we hit the next "* * *" or another obvious beer heading
        style = None
        abv = None

        j = i + 1
        # Collect lines until separator
        chunk = []
        while j < len(section):
            nxt = section[j]
            if nxt.strip() == "* * *":
                break
            chunk.append(nxt)
            j += 1

        # ABV: first percent line in chunk
        for c in chunk:
            val = parse_abv(c)
            if val is not None:
                abv = val
                break

        # Style: try to find a line right before "|" if present; otherwise a short non-icon line
        if "|" in chunk:
            pipe_idx = chunk.index("|")
            # search backwards from pipe for a reasonable style line
            k = pipe_idx - 1
            while k >= 0:
                cand = chunk[k].strip()
                if not cand:
                    k -= 1
                    continue
                if cand.lower() in icon_words:
                    k -= 1
                    continue
                if cand in {"|"}:
                    k -= 1
                    continue
                if "%" in cand:  # not a style
                    k -= 1
                    continue
                # keep it fairly short to avoid picking up other text
                if 2 <= len(cand) <= 40:
                    style = cand
                break
        else:
            # fallback: first short non-icon non-percent line
            for cand in chunk:
                c = cand.strip()
                if not c:
                    continue
                if c.lower() in icon_words:
                    continue
                if "%" in c:
                    continue
                if c in {"|"}:
                    continue
                if 2 <= len(c) <= 40:
                    style = c
                    break

        beers.append(
            BeerRecord(
                id=slugify(f"{BREWERY_NAME}-{beer_name}"),
                breweryName=BREWERY_NAME,
                breweryCity=BREWERY_CITY,
                producerName=BREWERY_NAME,
                name=beer_name,
                style=style,
                abv=abv,
                ibu=None,
                tapGroup="On Tap",
                category="on_tap",
                sourceUrl=SOURCE_URL,
                lastScraped=now,
            )
        )

        # Move to after the separator if present
        i = j + 1 if (j < len(section) and section[j].strip() == "* * *") else (i + 1)

    # De-dupe by id (the page can include repeated headings in weird cases)
    dedup = {}
    for b in beers:
        dedup[b.id] = b
    beers = list(dedup.values())

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
