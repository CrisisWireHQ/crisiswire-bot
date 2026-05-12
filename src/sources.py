SOURCES = [
    # =====================================================================
    # Tier 1 — Official agencies (highest trust, automatic relevance boost)
    # =====================================================================
    {"name": "USGS Quakes M4.5+", "type": "rss", "url": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.atom", "tier": 1, "category": "disaster"},
    {"name": "USGS Significant Quakes", "type": "rss", "url": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/significant_week.atom", "tier": 1, "category": "disaster"},
    {"name": "GDACS Disaster Alerts", "type": "rss", "url": "https://www.gdacs.org/xml/rss.xml", "tier": 1, "category": "disaster"},
    {"name": "WHO All News", "type": "rss", "url": "https://www.who.int/rss-feeds/news-english.xml", "tier": 1, "category": "outbreak"},
    {"name": "ReliefWeb Updates", "type": "rss", "url": "https://reliefweb.int/updates/rss.xml", "tier": 1, "category": "humanitarian"},
    {"name": "NOAA NWS Extreme", "type": "rss", "url": "https://api.weather.gov/alerts/active.atom?severity=Extreme", "tier": 1, "category": "disaster"},
    {"name": "USGS Volcanoes", "type": "rss", "url": "https://volcanoes.usgs.gov/vhpss/notices_rss.php", "tier": 1, "category": "disaster"},

    # =====================================================================
    # Tier 2 — Major wire-style international news (English)
    # =====================================================================
    {"name": "BBC World", "type": "rss", "url": "https://feeds.bbci.co.uk/news/world/rss.xml", "tier": 2, "category": "news"},
    {"name": "Al Jazeera", "type": "rss", "url": "https://www.aljazeera.com/xml/rss/all.xml", "tier": 2, "category": "news"},
    {"name": "France 24 Intl", "type": "rss", "url": "https://www.france24.com/en/rss", "tier": 2, "category": "news"},
    {"name": "DW World", "type": "rss", "url": "https://rss.dw.com/rdf/rss-en-world", "tier": 2, "category": "news"},
    {"name": "Sky News", "type": "rss", "url": "https://feeds.skynews.com/feeds/rss/world.xml", "tier": 2, "category": "news"},
    {"name": "CNN World", "type": "rss", "url": "http://rss.cnn.com/rss/edition_world.rss", "tier": 2, "category": "news"},
    {"name": "NPR World", "type": "rss", "url": "https://feeds.npr.org/1004/rss.xml", "tier": 2, "category": "news"},
    {"name": "Guardian World", "type": "rss", "url": "https://www.theguardian.com/world/rss", "tier": 2, "category": "news"},
    {"name": "CBS News World", "type": "rss", "url": "https://www.cbsnews.com/latest/rss/world", "tier": 2, "category": "news"},
    {"name": "NHK World", "type": "rss", "url": "https://www3.nhk.or.jp/nhkworld/upld/en/news/news.rss", "tier": 2, "category": "news"},
    {"name": "Kyodo News", "type": "rss", "url": "https://english.kyodonews.net/rss/news.xml", "tier": 2, "category": "news"},
    {"name": "Times of India World", "type": "rss", "url": "https://timesofindia.indiatimes.com/rssfeeds/296589292.cms", "tier": 2, "category": "news"},

    # =====================================================================
    # Tier 2 — Google News topic-tracking queries (broad capture, recent only)
    # =====================================================================
    {"name": "GN: Breaking News", "type": "rss", "url": "https://news.google.com/rss/search?q=%22breaking+news%22+when:6h&hl=en-US&gl=US&ceid=US:en", "tier": 2, "category": "news"},
    {"name": "GN: Mass Shooting", "type": "rss", "url": "https://news.google.com/rss/search?q=%22mass+shooting%22+when:24h&hl=en-US&gl=US&ceid=US:en", "tier": 2, "category": "attack"},
    {"name": "GN: Explosion", "type": "rss", "url": "https://news.google.com/rss/search?q=explosion+OR+blast+when:12h&hl=en-US&gl=US&ceid=US:en", "tier": 2, "category": "attack"},
    {"name": "GN: Plane Crash", "type": "rss", "url": "https://news.google.com/rss/search?q=%22plane+crash%22+OR+%22aircraft+crash%22+when:24h&hl=en-US&gl=US&ceid=US:en", "tier": 2, "category": "disaster"},
    {"name": "GN: Earthquake", "type": "rss", "url": "https://news.google.com/rss/search?q=earthquake+when:12h&hl=en-US&gl=US&ceid=US:en", "tier": 2, "category": "disaster"},
    {"name": "GN: Terror Attack", "type": "rss", "url": "https://news.google.com/rss/search?q=%22terror+attack%22+OR+%22terrorist+attack%22+when:24h&hl=en-US&gl=US&ceid=US:en", "tier": 2, "category": "attack"},
    {"name": "GN: Hostage", "type": "rss", "url": "https://news.google.com/rss/search?q=hostage+when:24h&hl=en-US&gl=US&ceid=US:en", "tier": 2, "category": "attack"},
    {"name": "GN: Wildfire", "type": "rss", "url": "https://news.google.com/rss/search?q=wildfire+evacuation+when:12h&hl=en-US&gl=US&ceid=US:en", "tier": 2, "category": "disaster"},
    {"name": "GN: Outbreak", "type": "rss", "url": "https://news.google.com/rss/search?q=outbreak+OR+%22disease+spread%22+when:24h&hl=en-US&gl=US&ceid=US:en", "tier": 2, "category": "outbreak"},
    {"name": "GN: Coup", "type": "rss", "url": "https://news.google.com/rss/search?q=coup+OR+%22military+takeover%22+when:24h&hl=en-US&gl=US&ceid=US:en", "tier": 2, "category": "unrest"},
    {"name": "GN: Strike Attack", "type": "rss", "url": "https://news.google.com/rss/search?q=%22airstrike%22+OR+%22missile+strike%22+when:6h&hl=en-US&gl=US&ceid=US:en", "tier": 2, "category": "conflict"},

    # =====================================================================
    # Tier 3 — Specialized
    # =====================================================================
    {"name": "ProMED Outbreaks", "type": "rss", "url": "https://promedmail.org/promed-posts/rss/", "tier": 3, "category": "outbreak"},

    # =====================================================================
    # Tier 2 — OSINT mirrors (public Telegram channels via t.me/s/)
    # =====================================================================
    {"name": "TG: BNO News", "type": "tg", "channel": "BNONews", "tier": 2, "category": "news"},
    {"name": "TG: Disclose.tv", "type": "tg", "channel": "disclosetv", "tier": 2, "category": "news"},
    {"name": "TG: Breaking911", "type": "tg", "channel": "breaking911", "tier": 2, "category": "news"},
    {"name": "TG: OSINTdefender", "type": "tg", "channel": "OSINTdefender", "tier": 2, "category": "conflict"},
    {"name": "TG: Faytuks Network", "type": "tg", "channel": "Faytuks_Network", "tier": 2, "category": "conflict"},
    {"name": "TG: WarMonitors", "type": "tg", "channel": "warmonitors", "tier": 2, "category": "conflict"},
    {"name": "TG: AuroraIntel", "type": "tg", "channel": "AuroraIntel", "tier": 2, "category": "conflict"},
    {"name": "TG: OSINTtechnical", "type": "tg", "channel": "Osinttechnical", "tier": 2, "category": "conflict"},
    {"name": "TG: Spectator Index", "type": "tg", "channel": "spectatorindex", "tier": 2, "category": "news"},
]
