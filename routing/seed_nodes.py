"""
Static seed data — humanitarian waypoint network across Africa.

Run `python main.py route-seed` to upsert these nodes into the database.
Coordinates are approximate city-centre points; adjust for actual depot/
warehouse locations as needed.

node_type values:
  hub       — major logistics hub (warehouse, regional depot)
  port      — sea or river port with regular cargo handling
  forward   — forward operating base / field office
  waypoint  — intermediate rest/fuel/checkpoint stop
"""

from datetime import datetime

_NOW = datetime.utcnow().isoformat()

SEED_NODES = [
    # ── East Africa ──────────────────────────────────────────────────────────
    {"id": "NBO",  "name": "Nairobi",          "lat": -1.286,  "lon":  36.817, "node_type": "hub",     "country": "Kenya",        "iso3": "KEN"},
    {"id": "MBA",  "name": "Mombasa",           "lat": -4.043,  "lon":  39.668, "node_type": "port",    "country": "Kenya",        "iso3": "KEN"},
    {"id": "KMP",  "name": "Kampala",           "lat":  0.347,  "lon":  32.582, "node_type": "hub",     "country": "Uganda",       "iso3": "UGA"},
    {"id": "DAR",  "name": "Dar es Salaam",     "lat": -6.793,  "lon":  39.208, "node_type": "port",    "country": "Tanzania",     "iso3": "TZA"},
    {"id": "MWZ",  "name": "Mwanza",            "lat": -2.517,  "lon":  32.900, "node_type": "waypoint","country": "Tanzania",     "iso3": "TZA"},
    {"id": "ADD",  "name": "Addis Ababa",       "lat":  9.025,  "lon":  38.747, "node_type": "hub",     "country": "Ethiopia",     "iso3": "ETH"},
    {"id": "DJI",  "name": "Djibouti",          "lat": 11.588,  "lon":  43.145, "node_type": "port",    "country": "Djibouti",     "iso3": "DJI"},
    {"id": "MGQ",  "name": "Mogadishu",         "lat":  2.046,  "lon":  45.342, "node_type": "forward", "country": "Somalia",      "iso3": "SOM"},
    {"id": "GNF",  "name": "Garowe",            "lat":  8.408,  "lon":  48.484, "node_type": "forward", "country": "Somalia",      "iso3": "SOM"},
    {"id": "HGS",  "name": "Hargeisa",          "lat":  9.560,  "lon":  44.065, "node_type": "waypoint","country": "Somaliland",   "iso3": "SOM"},
    {"id": "KRT",  "name": "Khartoum",          "lat": 15.551,  "lon":  32.532, "node_type": "hub",     "country": "Sudan",        "iso3": "SDN"},
    {"id": "JUB",  "name": "Juba",              "lat":  4.859,  "lon":  31.571, "node_type": "forward", "country": "South Sudan",  "iso3": "SSD"},
    {"id": "MAL",  "name": "Malakal",           "lat":  9.533,  "lon":  31.660, "node_type": "forward", "country": "South Sudan",  "iso3": "SSD"},
    {"id": "KGL",  "name": "Kigali",            "lat": -1.944,  "lon":  30.061, "node_type": "hub",     "country": "Rwanda",       "iso3": "RWA"},
    {"id": "BJM",  "name": "Bujumbura",         "lat": -3.382,  "lon":  29.361, "node_type": "hub",     "country": "Burundi",      "iso3": "BDI"},
    {"id": "LLW",  "name": "Lilongwe",          "lat":-13.962,  "lon":  33.787, "node_type": "hub",     "country": "Malawi",       "iso3": "MWI"},

    # ── Central Africa ───────────────────────────────────────────────────────
    {"id": "BGF",  "name": "Bangui",            "lat":  4.361,  "lon":  18.555, "node_type": "forward", "country": "CAR",          "iso3": "CAF"},
    {"id": "NDJ",  "name": "N'Djamena",         "lat": 12.107,  "lon":  15.044, "node_type": "hub",     "country": "Chad",         "iso3": "TCD"},
    {"id": "FIH",  "name": "Kinshasa",          "lat": -4.322,  "lon":  15.322, "node_type": "hub",     "country": "DRC",          "iso3": "COD"},
    {"id": "FBM",  "name": "Lubumbashi",        "lat":-11.665,  "lon":  27.479, "node_type": "waypoint","country": "DRC",          "iso3": "COD"},
    {"id": "KWZ",  "name": "Kolwezi",           "lat":-10.718,  "lon":  25.468, "node_type": "waypoint","country": "DRC",          "iso3": "COD"},
    {"id": "MJM",  "name": "Mbuji-Mayi",        "lat": -6.136,  "lon":  23.590, "node_type": "waypoint","country": "DRC",          "iso3": "COD"},
    {"id": "NDL",  "name": "Ndola",             "lat":-12.958,  "lon":  28.637, "node_type": "waypoint","country": "Zambia",       "iso3": "ZMB"},
    {"id": "GOM",  "name": "Goma",              "lat": -1.679,  "lon":  29.228, "node_type": "forward", "country": "DRC",          "iso3": "COD"},
    {"id": "BNI",  "name": "Beni",              "lat":  0.490,  "lon":  29.474, "node_type": "forward", "country": "DRC",          "iso3": "COD"},
    {"id": "DLA",  "name": "Douala",            "lat":  4.048,  "lon":   9.700, "node_type": "port",    "country": "Cameroon",     "iso3": "CMR"},

    # ── Southern Africa ──────────────────────────────────────────────────────
    {"id": "LUN",  "name": "Lusaka",            "lat":-15.417,  "lon":  28.283, "node_type": "hub",     "country": "Zambia",       "iso3": "ZMB"},
    {"id": "HRE",  "name": "Harare",            "lat":-17.829,  "lon":  31.052, "node_type": "hub",     "country": "Zimbabwe",     "iso3": "ZWE"},
    {"id": "BEW",  "name": "Beira",             "lat":-19.844,  "lon":  34.844, "node_type": "port",    "country": "Mozambique",   "iso3": "MOZ"},
    {"id": "MPM",  "name": "Maputo",            "lat":-25.966,  "lon":  32.573, "node_type": "port",    "country": "Mozambique",   "iso3": "MOZ"},
    {"id": "ANC",  "name": "Luanda",            "lat": -8.836,  "lon":  13.234, "node_type": "hub",     "country": "Angola",       "iso3": "AGO"},
    {"id": "WIN",  "name": "Windhoek",          "lat":-22.558,  "lon":  17.085, "node_type": "hub",     "country": "Namibia",      "iso3": "NAM"},
    {"id": "JNB",  "name": "Johannesburg",      "lat":-26.205,  "lon":  28.046, "node_type": "hub",     "country": "South Africa", "iso3": "ZAF"},

    # ── West Africa ──────────────────────────────────────────────────────────
    {"id": "DKR",  "name": "Dakar",             "lat": 14.693,  "lon": -17.447, "node_type": "port",    "country": "Senegal",      "iso3": "SEN"},
    {"id": "BKO",  "name": "Bamako",            "lat": 12.650,  "lon":  -8.000, "node_type": "hub",     "country": "Mali",         "iso3": "MLI"},
    {"id": "MOP",  "name": "Mopti",             "lat": 14.480,  "lon":  -4.183, "node_type": "waypoint","country": "Mali",         "iso3": "MLI"},
    {"id": "OUA",  "name": "Ouagadougou",       "lat": 12.360,  "lon":  -1.534, "node_type": "hub",     "country": "Burkina Faso", "iso3": "BFA"},
    {"id": "NIM",  "name": "Niamey",            "lat": 13.511,  "lon":   2.125, "node_type": "hub",     "country": "Niger",        "iso3": "NER"},
    {"id": "ZND",  "name": "Zinder",            "lat": 13.804,  "lon":   8.989, "node_type": "waypoint","country": "Niger",        "iso3": "NER"},
    {"id": "DIF",  "name": "Diffa",             "lat": 13.315,  "lon":  12.614, "node_type": "forward", "country": "Niger",        "iso3": "NER"},
    {"id": "ABV",  "name": "Abuja",             "lat":  9.070,  "lon":   7.399, "node_type": "hub",     "country": "Nigeria",      "iso3": "NGA"},
    {"id": "LOS",  "name": "Lagos",             "lat":  6.524,  "lon":   3.379, "node_type": "port",    "country": "Nigeria",      "iso3": "NGA"},
    {"id": "ACC",  "name": "Accra",             "lat":  5.558,  "lon":  -0.197, "node_type": "hub",     "country": "Ghana",        "iso3": "GHA"},
    {"id": "ABJ",  "name": "Abidjan",           "lat":  5.359,  "lon":  -4.008, "node_type": "port",    "country": "Côte d'Ivoire","iso3": "CIV"},

    # ── North / NE Africa ────────────────────────────────────────────────────
    {"id": "CAI",  "name": "Cairo",             "lat": 30.044,  "lon":  31.236, "node_type": "hub",     "country": "Egypt",        "iso3": "EGY"},
    {"id": "ASM",  "name": "Asmara",            "lat": 15.338,  "lon":  38.932, "node_type": "waypoint","country": "Eritrea",      "iso3": "ERI"},
]

# Attach created_at timestamps
for _n in SEED_NODES:
    _n.setdefault("notes", "")
    _n["created_at"] = _NOW
