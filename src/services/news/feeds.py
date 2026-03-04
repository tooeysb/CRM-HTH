"""Feed configuration for construction industry news sources."""

RSS_FEEDS = [
    {
        "name": "Construction Dive",
        "url": "https://www.constructiondive.com/feeds/news/",
        "source_type": "rss_construction_dive",
    },
    {
        "name": "Google News - Construction Companies",
        "url": (
            "https://news.google.com/rss/search?"
            "q=construction+company+contractor&hl=en-US&gl=US&ceid=US:en"
        ),
        "source_type": "google_news",
    },
    {
        "name": "Google News - Construction Projects",
        "url": (
            "https://news.google.com/rss/search?"
            "q=construction+project+awarded&hl=en-US&gl=US&ceid=US:en"
        ),
        "source_type": "google_news",
    },
    {
        "name": "Google News - General Contractors",
        "url": (
            "https://news.google.com/rss/search?"
            'q="general+contractor"+construction&hl=en-US&gl=US&ceid=US:en'
        ),
        "source_type": "google_news",
    },
]

# Web-scraped news sites (HTML parsing, not RSS)
WEB_FEEDS = [
    {
        "name": "ENR News",
        "url": "https://www.enr.com/news",
        "source_type": "enr",
    },
    {
        "name": "Bisnow Construction & Development",
        "url": "https://www.bisnow.com/construction-development",
        "source_type": "bisnow",
    },
    {
        "name": "BldUp News",
        "url": "https://www.bldup.com/posts",
        "source_type": "bldup",
    },
]
