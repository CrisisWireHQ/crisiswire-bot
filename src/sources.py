SOURCES = [
    # Tier 1 — Official agencies (highest trust)
    {"name": "USGS Significant Quakes", "type": "rss", "url": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/significant_week.atom", "tier": 1, "category": "disaster"},
    {"name": "GDACS Disaster Alerts", "type": "rss", "url": "https://www.gdacs.org/xml/rss.xml", "tier": 1, "category": "disaster"},
    {"name": "WHO Outbreak News", "type": "rss", "url": "https://www.who.int/feeds/entity/csr/don/en/rss.xml", "tier": 1, "category": "outbreak"},
    {"name": "ReliefWeb Headlines", "type": "rss", "url": "https://reliefweb.int/headlines/rss.xml", "tier": 1, "category": "humanitarian"},
    {"name": "NOAA NWS Extreme", "type": "rss", "url": "https://api.weather.gov/alerts/active.atom?severity=Extreme", "tier": 1, "category": "disaster"},

    # Tier 2 — Wire-style international news
    {"name": "BBC World", "type": "rss", "url": "https://feeds.bbci.co.uk/news/world/rss.xml", "tier": 2, "category": "news"},
    {"name": "Al Jazeera", "type": "rss", "url": "https://www.aljazeera.com/xml/rss/all.xml", "tier": 2, "category": "news"},
    {"name": "France 24 Intl", "type": "rss", "url": "https://www.france24.com/en/rss", "tier": 2, "category": "news"},
    {"name": "DW World", "type": "rss", "url": "https://rss.dw.com/rdf/rss-en-world", "tier": 2, "category": "news"},

    # Tier 3 — Specialized
    {"name": "ProMED Outbreaks", "type": "rss", "url": "https://promedmail.org/rss/promed_news.rss", "tier": 3, "category": "outbreak"},

    # Tier 2 — OSINT mirrors (public Telegram channels, scraped from t.me/s/{channel})
    {"name": "TG: BNO News", "type": "tg", "channel": "BNONews", "tier": 2, "category": "news"},
    {"name": "TG: Disclose.tv", "type": "tg", "channel": "disclosetv", "tier": 2, "category": "news"},
    {"name": "TG: Breaking911", "type": "tg", "channel": "breaking911", "tier": 2, "category": "news"},
    {"name": "TG: OSINTdefender", "type": "tg", "channel": "OSINTdefender", "tier": 2, "category": "conflict"},
    {"name": "TG: Faytuks Network", "type": "tg", "channel": "Faytuks_Network", "tier": 2, "category": "conflict"},
    {"name": "TG: WarMonitors", "type": "tg", "channel": "warmonitors", "tier": 2, "category": "conflict"},
    {"name": "TG: AuroraIntel", "type": "tg", "channel": "AuroraIntel", "tier": 2, "category": "conflict"},
    {"name": "TG: Global Mil Info", "type": "tg", "channel": "Global_Mil_Info", "tier": 2, "category": "conflict"},
    {"name": "TG: OSINTtechnical", "type": "tg", "channel": "Osinttechnical", "tier": 2, "category": "conflict"},
    {"name": "TG: Raws Alert", "type": "tg", "channel": "Rawsalert", "tier": 2, "category": "news"},
    {"name": "TG: Spectator Index", "type": "tg", "channel": "spectatorindex", "tier": 2, "category": "news"},
]
