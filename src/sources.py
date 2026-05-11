SOURCES = [
    # Tier 1 — Official agencies (highest trust)
    {"name": "USGS Significant Quakes", "url": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/significant_week.atom", "tier": 1, "category": "disaster"},
    {"name": "GDACS Disaster Alerts", "url": "https://www.gdacs.org/xml/rss.xml", "tier": 1, "category": "disaster"},
    {"name": "WHO Outbreak News", "url": "https://www.who.int/feeds/entity/csr/don/en/rss.xml", "tier": 1, "category": "outbreak"},
    {"name": "ReliefWeb Headlines", "url": "https://reliefweb.int/headlines/rss.xml", "tier": 1, "category": "humanitarian"},
    {"name": "NOAA NWS Extreme", "url": "https://api.weather.gov/alerts/active.atom?severity=Extreme", "tier": 1, "category": "disaster"},

    # Tier 2 — Wire-style international news
    {"name": "BBC World", "url": "https://feeds.bbci.co.uk/news/world/rss.xml", "tier": 2, "category": "news"},
    {"name": "Al Jazeera", "url": "https://www.aljazeera.com/xml/rss/all.xml", "tier": 2, "category": "news"},
    {"name": "France 24 Intl", "url": "https://www.france24.com/en/rss", "tier": 2, "category": "news"},
    {"name": "DW World", "url": "https://rss.dw.com/rdf/rss-en-world", "tier": 2, "category": "news"},

    # Tier 3 — Specialized
    {"name": "ProMED Outbreaks", "url": "https://promedmail.org/rss/promed_news.rss", "tier": 3, "category": "outbreak"},
]
