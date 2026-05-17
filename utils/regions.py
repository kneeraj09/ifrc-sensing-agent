"""Country → region mapping for the sensing dashboard."""

_AFRICA = {
    "Algeria", "Angola", "Benin", "Botswana", "Burkina Faso", "Burundi",
    "Cabo Verde", "Cape Verde", "Cameroon", "Central African Republic", "CAR",
    "Chad", "Comoros", "Congo", "Côte d'Ivoire", "Ivory Coast",
    "Democratic Republic of the Congo", "DRC", "DR Congo",
    "Djibouti", "Egypt", "Equatorial Guinea", "Eritrea", "Eswatini", "Swaziland",
    "Ethiopia", "Gabon", "Gambia", "Ghana", "Guinea", "Guinea-Bissau",
    "Kenya", "Lesotho", "Liberia", "Libya", "Madagascar", "Malawi", "Mali",
    "Mauritania", "Mauritius", "Morocco", "Mozambique", "Namibia", "Niger",
    "Nigeria", "Rwanda", "Senegal", "Sierra Leone", "Somalia", "Somaliland",
    "South Africa", "South Sudan", "Sudan", "São Tomé and Príncipe",
    "Tanzania", "Togo", "Tunisia", "Uganda", "Zambia", "Zimbabwe",
}

_MIDDLE_EAST = {
    "Bahrain", "Iran", "Iraq", "Israel", "Jordan", "Kuwait", "Lebanon",
    "Oman", "Palestine", "Palestinian Territory", "Gaza", "West Bank",
    "Qatar", "Saudi Arabia", "Syria", "United Arab Emirates", "UAE",
    "Yemen", "Turkey", "Türkiye",
}

_ASIA = {
    "Afghanistan", "Bangladesh", "Bhutan", "Cambodia", "China", "India",
    "Indonesia", "Japan", "Kazakhstan", "Kyrgyzstan", "Laos", "Malaysia",
    "Maldives", "Mongolia", "Myanmar", "Burma", "Nepal", "North Korea",
    "Pakistan", "Philippines", "Singapore", "South Korea", "Sri Lanka",
    "Tajikistan", "Thailand", "Timor-Leste", "East Timor", "Turkmenistan",
    "Uzbekistan", "Vietnam",
}

_LATIN_AMERICA = {
    "Argentina", "Belize", "Bolivia", "Brazil", "Chile", "Colombia",
    "Costa Rica", "Cuba", "Dominican Republic", "Ecuador", "El Salvador",
    "Guatemala", "Guyana", "Haiti", "Honduras", "Jamaica", "Mexico",
    "Nicaragua", "Panama", "Paraguay", "Peru", "Suriname",
    "Trinidad and Tobago", "Uruguay", "Venezuela",
}

_EUROPE = {
    "Albania", "Austria", "Belarus", "Belgium", "Bosnia and Herzegovina",
    "Bulgaria", "Croatia", "Cyprus", "Czech Republic", "Czechia", "Denmark",
    "Estonia", "Finland", "France", "Georgia", "Germany", "Greece",
    "Hungary", "Iceland", "Ireland", "Italy", "Kosovo", "Latvia",
    "Lithuania", "Luxembourg", "Malta", "Moldova", "Montenegro",
    "Netherlands", "North Macedonia", "Norway", "Poland", "Portugal",
    "Romania", "Russia", "Serbia", "Slovakia", "Slovenia", "Spain",
    "Sweden", "Switzerland", "Ukraine", "United Kingdom", "UK",
}

_NORTH_AMERICA = {
    "Canada", "United States", "USA", "United States of America",
    "Greenland", "Mexico",  # Mexico sometimes grouped here
}

_OCEANIA = {
    "Australia", "Fiji", "Kiribati", "Marshall Islands", "Micronesia",
    "Nauru", "New Zealand", "Palau", "Papua New Guinea", "Samoa",
    "Solomon Islands", "Tonga", "Tuvalu", "Vanuatu",
}

_REGION_SETS = [
    ("Africa",        _AFRICA),
    ("Middle East",   _MIDDLE_EAST),
    ("Asia",          _ASIA),
    ("Latin America", _LATIN_AMERICA),
    ("Europe",        _EUROPE),
    ("North America", _NORTH_AMERICA),
    ("Oceania",       _OCEANIA),
]


def classify(country: str | None) -> str:
    """Return the region name for a given country string, or 'Global' if unknown."""
    if not country:
        return "Global"
    country = country.strip()
    for region, country_set in _REGION_SETS:
        if country in country_set:
            return region
    # Fuzzy fallback — handles partial matches like "Congo, Rep." or "Korea, South"
    country_lower = country.lower()
    for region, country_set in _REGION_SETS:
        if any(c.lower() in country_lower or country_lower in c.lower() for c in country_set):
            return region
    return "Global"
