"""RSS feed configuration for construction industry news sources."""

RSS_FEEDS = [
    {
        "name": "ENR Top Stories",
        "url": "https://www.enr.com/rss/news",
        "source_type": "rss_enr",
    },
    {
        "name": "Construction Dive",
        "url": "https://www.constructiondive.com/feeds/news/",
        "source_type": "rss_construction_dive",
    },
    {
        "name": "GlobeNewswire Construction",
        "url": "https://www.globenewswire.com/RssFeed/subjectcode/25-Construction/feedTitle/GlobeNewswire%20-%20Construction",
        "source_type": "rss_globenewswire",
    },
]
