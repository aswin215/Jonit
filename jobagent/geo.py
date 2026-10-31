"""Decide whether a posting's location string is in the United States."""

import re

STATES = {
    "AL": "alabama", "AK": "alaska", "AZ": "arizona", "AR": "arkansas", "CA": "california",
    "CO": "colorado", "CT": "connecticut", "DE": "delaware", "FL": "florida", "GA": "georgia",
    "HI": "hawaii", "ID": "idaho", "IL": "illinois", "IN": "indiana", "IA": "iowa", "KS": "kansas",
    "KY": "kentucky", "LA": "louisiana", "ME": "maine", "MD": "maryland", "MA": "massachusetts",
    "MI": "michigan", "MN": "minnesota", "MS": "mississippi", "MO": "missouri", "MT": "montana",
    "NE": "nebraska", "NV": "nevada", "NH": "new hampshire", "NJ": "new jersey", "NM": "new mexico",
    "NY": "new york", "NC": "north carolina", "ND": "north dakota", "OH": "ohio", "OK": "oklahoma",
    "OR": "oregon", "PA": "pennsylvania", "RI": "rhode island", "SC": "south carolina",
    "SD": "south dakota", "TN": "tennessee", "TX": "texas", "UT": "utah", "VT": "vermont",
    "VA": "virginia", "WA": "washington", "WV": "west virginia", "WI": "wisconsin", "WY": "wyoming",
    "DC": "district of columbia",
}

# Boards often list only the city.
CITIES = [
    "san francisco", "san jose", "palo alto", "mountain view", "menlo park", "sunnyvale", "santa clara",
    "cupertino", "redwood city", "san mateo", "oakland", "berkeley", "bay area", "silicon valley",
    "los angeles", "san diego", "irvine", "seattle", "bellevue", "redmond", "portland", "austin",
    "dallas", "houston", "denver", "boulder", "chicago", "boston", "cambridge, ma", "new york city", "nyc",
    "brooklyn", "manhattan", "washington, d.c.", "atlanta", "miami", "phoenix", "salt lake city",
    "pittsburgh", "philadelphia", "minneapolis", "raleigh", "nashville", "detroit", "columbus",
]

US_WORDS = re.compile(r"\b(united states|usa|u\.s\.a?\.?|us|america)\b", re.I)
ABBREV = re.compile(r"(?:,\s*|\b)(" + "|".join(STATES) + r")\b")  # case-sensitive: "CA", not "ca"
NON_US = re.compile(
    r"\b(canada|uk|united kingdom|england|ireland|germany|france|netherlands|spain|india|singapore|"
    r"japan|china|australia|brazil|mexico|israel|poland|switzerland|sweden|korea|toronto|london|"
    r"vancouver, bc|ontario|british columbia)\b",
    re.I,
)


def is_us(location: str) -> bool:
    if not location:
        return False
    low = location.lower()
    if US_WORDS.search(location):
        return True
    # A named US state or city wins, so "New York, London" still counts.
    if any(name in low for name in STATES.values()) or any(city in low for city in CITIES):
        return True
    if NON_US.search(location):
        return False
    return bool(ABBREV.search(location))
