import requests
from bs4 import BeautifulSoup
import re
import json

# ─────────────────────────────────────────────────────────────────────────────
# WHY THE OLD SCRAPER RETURNED ALL ZEROS:
#   pagasa.dost.gov.ph and gaswatchph.com are JavaScript-rendered sites.
#   requests + BeautifulSoup only get the raw HTML shell — the data tables
#   are populated AFTER the browser runs JS. The old scraper found no <tr>
#   rows with weather data because they simply don't exist in the raw HTML.
#
# THE FIX:
#   - Weather  → Open-Meteo API (free, no API key, pure REST, very reliable)
#   - Diesel   → Parse GasWatch's embedded __NEXT_DATA__ JSON from <script>
#                tags (Next.js sites embed their data there), with a DOE
#                legacy site fallback.
# ─────────────────────────────────────────────────────────────────────────────

# ── WMO weather code → human-readable label ──────────────────────────────────
WMO_CODES = {
    0: "Clear",       1: "Mostly Clear", 2: "Partly Cloudy", 3: "Overcast",
    45: "Foggy",      48: "Foggy",
    51: "Lt Drizzle", 53: "Drizzle",     55: "Hvy Drizzle",
    61: "Lt Rain",    63: "Rain",        65: "Hvy Rain",
    71: "Lt Snow",    73: "Snow",        75: "Hvy Snow",
    77: "Snow",
    80: "Showers",    81: "Showers",     82: "Hvy Showers",
    85: "Snow Shwr",  86: "Snow Shwr",
    95: "Thunderstm", 96: "T-Storm",     99: "T-Storm",
}

# ── Province coordinates (capital/main city) ─────────────────────────────────
PROVINCES = [
    {"code": "IN", "name": "Ilocos Norte", "lat": 18.1969, "lon": 120.5936},  # Laoag
    {"code": "IS", "name": "Ilocos Sur",   "lat": 17.5747, "lon": 120.3869},  # Vigan
    {"code": "LU", "name": "La Union",     "lat": 16.6157, "lon": 120.3166},  # San Fernando
    {"code": "PG", "name": "Pangasinan",   "lat": 16.0433, "lon": 120.3333},  # Dagupan
]


def get_region1_weather():
    """
    Fetch current weather for Region I provinces via the Open-Meteo API.
    Returns a dict of lists ready for your app's table widget.

    Open-Meteo docs: https://open-meteo.com/en/docs
    Free, no API key, no rate-limit for non-commercial use.
    """
    weather_results = {
        "Prov": [p["code"] for p in PROVINCES],
        "Stat": ["N/A"] * len(PROVINCES),
        "°C":   [0]     * len(PROVINCES),
    }

    for i, prov in enumerate(PROVINCES):
        try:
            url = (
                "https://api.open-meteo.com/v1/forecast"
                f"?latitude={prov['lat']}"
                f"&longitude={prov['lon']}"
                "&current=temperature_2m,weather_code"
                "&timezone=Asia%2FManila"
            )
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            current = data["current"]
            temp    = round(current["temperature_2m"])
            wmo     = current["weather_code"]
            label   = WMO_CODES.get(wmo, "Variable")

            weather_results["°C"][i]   = temp
            weather_results["Stat"][i] = label

        except Exception as e:
            print(f"[Weather] Error for {prov['name']}: {e}")
            # Keeps "N/A" / 0 for that province on failure

    return weather_results


# ── Diesel price scraper ──────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def _parse_gaswatch_next_data(soup: BeautifulSoup) -> float | None:
    """
    GasWatch is a Next.js app. It embeds all its data in a <script> tag:
        <script id="__NEXT_DATA__" type="application/json">…</script>
    We parse that JSON tree looking for an average diesel price.
    """
    script = soup.find("script", {"id": "__NEXT_DATA__"})
    if not script:
        return None

    try:
        next_data = json.loads(script.string)
        # Walk the props → pageProps tree; key names may vary by deploy.
        # We search recursively for any numeric value paired with a key
        # that contains "diesel" and "avg" / "average" / "price".
        return _deep_find_diesel(next_data)
    except (json.JSONDecodeError, TypeError):
        return None


def _deep_find_diesel(obj, depth: int = 0) -> float | None:
    """Recursively search a JSON tree for a diesel average price."""
    if depth > 10:
        return None
    if isinstance(obj, dict):
        for k, v in obj.items():
            key_lower = k.lower()
            if "diesel" in key_lower and ("avg" in key_lower or "average" in key_lower or "price" in key_lower):
                if isinstance(v, (int, float)) and 50 < v < 300:
                    return float(v)
            result = _deep_find_diesel(v, depth + 1)
            if result is not None:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = _deep_find_diesel(item, depth + 1)
            if result is not None:
                return result
    return None


def _parse_gaswatch_text_fallback(soup: BeautifulSoup) -> float | None:
    """
    Secondary fallback: scan all visible text on the page for a pattern like
    'Avg. Diesel … XX.XX' or a PHP price near the word 'diesel'.
    """
    text = soup.get_text(" ", strip=True)
    # Look for "diesel" near a peso price, e.g. "₱92.20" or "92.20"
    patterns = [
        r"(?i)diesel[^₱\d]{0,60}[₱]?\s*(\d{2,3}\.\d{1,2})",
        r"(?i)(\d{2,3}\.\d{1,2})[^₱\d]{0,40}diesel",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            val = float(m.group(1))
            if 50 < val < 300:
                return val
    return None


def get_diesel_price() -> float:
    """
    Fetch the current average diesel price (PHP/L) from GasWatch PH.

    Strategy:
      1. Fetch gaswatchph.com and try to extract the __NEXT_DATA__ JSON.
      2. Fall back to regex-scanning visible page text.
      3. If both fail, return 0.0 (signals "unavailable" to the caller).

    NOTE: If GasWatch ever fully blocks scraping, switch to the DOE
    legacy site: https://legacy.doe.gov.ph/oil-monitor
    which publishes weekly pump-price tables in static HTML.
    """
    url = "https://gaswatchph.com/"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser")

        price = _parse_gaswatch_next_data(soup)
        if price:
            print(f"[Diesel] GasWatch __NEXT_DATA__ → ₱{price:.2f}/L")
            return price

        price = _parse_gaswatch_text_fallback(soup)
        if price:
            print(f"[Diesel] GasWatch text fallback → ₱{price:.2f}/L")
            return price

        print("[Diesel] GasWatch returned no parsable price — trying DOE fallback.")

    except Exception as e:
        print(f"[Diesel] GasWatch fetch failed: {e}")

    # ── DOE legacy fallback ───────────────────────────────────────────────────
    return _get_diesel_doe_fallback()


def _get_diesel_doe_fallback() -> float:
    """
    Scrape the DOE legacy oil-monitor page (static HTML, no JS required).
    Looks for a retail pump price table row containing 'Diesel'.
    """
    url = "https://legacy.doe.gov.ph/oil-monitor"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser")

        for row in soup.find_all("tr"):
            row_text = row.get_text()
            if re.search(r"(?i)\bdiesel\b", row_text) and "premium" not in row_text.lower():
                prices = re.findall(r"\d{2,3}\.\d{2}", row_text)
                valid  = [float(p) for p in prices if 50 < float(p) < 300]
                if valid:
                    avg = round(sum(valid) / len(valid), 2)
                    print(f"[Diesel] DOE fallback → ₱{avg:.2f}/L")
                    return avg

    except Exception as e:
        print(f"[Diesel] DOE fallback failed: {e}")

    return 0.0  # Caller should treat 0.0 as "data unavailable"


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=== Region I Weather (Open-Meteo) ===")
    weather = get_region1_weather()
    for i, prov in enumerate(weather["Prov"]):
        print(f"  {prov}: {weather['Stat'][i]}, {weather['°C'][i]}°C")

    print("\n=== Diesel Price ===")
    diesel = get_diesel_price()
    if diesel:
        print(f"  Avg. Diesel: ₱{diesel:.2f}/L")
    else:
        print("  Diesel price unavailable.")