"""
RSS feed sources for NewsLeader.

Curated for:
- Real-time updates (published within 24h)
- Geographic diversity (Korea, US, Europe, Asia, Middle East)
- Political balance (public broadcasters, multilateral bodies, left/right/center)
- Actual public accessibility (no paywall, no deprecated endpoints)

Excluded intentionally:
- Reuters / Bloomberg / FT / Economist: no public RSS as of 2020/2021
- AFP: client-restricted XML endpoints
- Xinhua / China Daily: state-controlled propaganda (Reporters Without Borders)
- FeedBurner URLs: deprecated by Google, unreliable
- Reddit r/worldnews|technology|science: block RSS without auth
- Sites that block RSS from server environments (IEEE Spectrum, Dark Reading, HBR, etc.)
"""

RSS_FEEDS = [
    # ── Global Wire / News Agencies ──────────────────────────────────────────
    ("AP World",            "https://apnews.com/world-news.rss"),
    ("AP Business",         "https://apnews.com/business.rss"),
    ("AP Technology",       "https://apnews.com/technology.rss"),

    # ── English Public Broadcasters ──────────────────────────────────────────
    # BBC — UK public broadcaster, highly trusted, global reach
    ("BBC Business",        "https://feeds.bbci.co.uk/news/business/rss.xml"),
    ("BBC Technology",      "https://feeds.bbci.co.uk/news/technology/rss.xml"),
    ("BBC World",           "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("BBC Science",         "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml"),
    # NPR — US public radio
    ("NPR Business",        "https://feeds.npr.org/1006/rss.xml"),
    ("NPR Technology",      "https://feeds.npr.org/1019/rss.xml"),
    ("NPR World",           "https://feeds.npr.org/1004/rss.xml"),
    # France 24 — French public broadcaster, strong Africa/Middle East desk
    ("France 24",           "https://www.france24.com/en/rss"),
    ("France 24 Business",  "https://www.france24.com/en/business-tech/rss"),
    # Deutsche Welle — German public broadcaster, strong Asia desk
    ("DW Business",         "https://rss.dw.com/rdf/rss-en-bus"),
    ("DW Asia",             "https://rss.dw.com/rdf/rss-en-asia"),
    ("DW World",            "https://rss.dw.com/rdf/rss-en-all"),
    # NHK World — Japan's public broadcaster, Asia-Pacific focus
    ("NHK World",           "https://www3.nhk.or.jp/rss/news/cat0.xml"),
    # Al Jazeera — Qatar-funded, non-Western perspective, respected English service
    ("Al Jazeera",          "https://www.aljazeera.com/xml/rss/all.xml"),

    # ── Finance / Business (English) ─────────────────────────────────────────
    ("CNBC Business",       "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10001147"),
    ("CNBC Technology",     "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=19854910"),
    ("CNBC World",          "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114"),
    ("MarketWatch",         "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("Fortune Finance",     "https://fortune.com/feed/fortune-section-finance/"),
    ("Guardian Business",   "https://www.theguardian.com/uk/business/rss"),
    ("Guardian World",      "https://www.theguardian.com/world/rss"),

    # ── Multilateral Institutions / Central Banks ─────────────────────────────
    ("IMF News",            "https://www.imf.org/en/News/rss?language=ENG"),
    ("IMF Blog",            "https://www.imf.org/en/blogs/rss?language=ENG"),
    ("Federal Reserve",     "https://www.federalreserve.gov/feeds/press_all.xml"),
    ("ECB",                 "https://www.ecb.europa.eu/rss/press.html"),
    ("OECD",                "https://www.oecd.org/newsroom/rss.xml"),
    ("BIS Research",        "https://www.bis.org/rss/speeches.rss"),
    ("EIA Energy",          "https://www.eia.gov/rss/todayinenergy.xml"),

    # ── Geopolitics / Think Tanks ─────────────────────────────────────────────
    ("Brookings",           "https://www.brookings.edu/feed/"),
    ("CFR",                 "https://www.cfr.org/rss/publications.xml"),
    ("Foreign Affairs",     "https://www.foreignaffairs.com/rss.xml"),

    # ── Technology / Science ─────────────────────────────────────────────────
    ("TechCrunch",          "https://techcrunch.com/feed/"),
    ("Ars Technica",        "https://feeds.arstechnica.com/arstechnica/index"),
    ("Wired",               "https://www.wired.com/feed/rss"),
    ("The Verge",           "https://www.theverge.com/rss/index.xml"),
    ("MIT Tech Review",     "https://www.technologyreview.com/feed/"),
    ("VentureBeat",         "https://venturebeat.com/feed/"),
    ("Guardian Tech",       "https://www.theguardian.com/technology/rss"),

    # ── Asian News (English) ─────────────────────────────────────────────────
    ("Nikkei Asia",         "https://asia.nikkei.com/rss/feed/nar"),
    ("SCMP Business",       "https://www.scmp.com/rss/92/feed"),

    # ── Korean Domestic ───────────────────────────────────────────────────────
    # Economic / Business (Korean)
    ("연합뉴스경제",          "https://www.yna.co.kr/economy/index.xml"),
    ("매일경제",              "https://www.mk.co.kr/rss/30000001/"),
    ("한국경제",              "https://www.hankyung.com/feed/economy"),
    # Technology / IT (Korean)
    ("전자신문",              "https://rss.etnews.com/Section901.xml"),
    ("ZDNet Korea",           "https://zdnet.co.kr/rss.do"),
    # Korean news in English (for global context with Korean perspective)
    ("Korea Herald Business", "https://www.koreaherald.com/rss/kh_Business"),
    ("Korea Times",           "https://www.koreatimes.co.kr/www2/common/rss.asp"),
    ("Yonhap English",        "https://en.yna.co.kr/RSS/news.xml"),
    # Central bank
    ("한국은행",              "https://www.bok.or.kr/portal/bbs/P0000559/list.do?menuNo=200431&pageType=rss"),

    # ── 한국 경제/금융 추가 매체 ──────────────────────────────────────
    ("파이낸셜뉴스",          "https://www.fnnews.com/rss"),
    ("뉴스핌",                "https://www.newspim.com/rss/newsrss.asp"),
    ("아시아경제",            "https://www.asiae.co.kr/rss"),

    # ── 국제 추가 금융기관 ─────────────────────────────────────────────
    ("World Bank Blog",       "https://blogs.worldbank.org/rss.xml"),
    ("OPEC",                  "https://www.opec.org/opec_web/en/press_room/rss.xml"),
    ("Asian Dev Bank",        "https://www.adb.org/news/rss"),
    ("Bank of Japan",         "https://www.boj.or.jp/en/new/rss.xml"),

    # ── 지정학/외교 추가 ──────────────────────────────────────────────
    ("Politico World",        "https://rss.politico.com/politics-news.xml"),
    ("Foreign Policy",        "https://foreignpolicy.com/feed/"),

    # ── AI / 반도체 전문 ──────────────────────────────────────────────
    ("Hugging Face Blog",     "https://huggingface.co/blog/feed.xml"),
    ("Semiconductor Eng.",    "https://semiengineering.com/feed/"),

    # ── 아시아 영문 추가 ──────────────────────────────────────────────
    ("Straits Times Asia",    "https://www.straitstimes.com/rss/world/asia/rss.xml"),
    ("The Hindu Business",    "https://www.thehindu.com/business/feeder/default.rss"),

    # ── AI 회사 공식 블로그 ────────────────────────────────────────
    ("OpenAI Blog",           "https://openai.com/blog/rss.xml"),
    ("Google DeepMind",       "https://deepmind.google/blog/rss/"),
    ("Meta AI Blog",          "https://ai.meta.com/blog/rss/"),
    ("Mistral AI",            "https://mistral.ai/news/rss"),

    # ── 스포츠 ─────────────────────────────────────────────────────
    ("ESPN Top",              "https://www.espn.com/espn/rss/news"),
    ("BBC Sport",             "https://feeds.bbci.co.uk/sport/rss.xml"),
    ("연합뉴스 스포츠",        "https://www.yna.co.kr/sports/index.xml"),
    ("AP Sports",             "https://apnews.com/sports.rss"),

    # ── 환경 / 기후 ────────────────────────────────────────────────
    ("Guardian Environment",  "https://www.theguardian.com/environment/rss"),
    ("Climate Home News",     "https://www.climatechangenews.com/feed/"),

    # ── 과학 ───────────────────────────────────────────────────────
    ("Science Daily",         "https://www.sciencedaily.com/rss/top/science.xml"),
    ("New Scientist",         "https://www.newscientist.com/feed/home/"),
    ("NASA News",             "https://www.nasa.gov/news-release/feed/"),

    # ── 한국 사회 / 정치 / 문화 ───────────────────────────────────
    ("한겨레",                "https://www.hani.co.kr/rss/"),
    ("경향신문",              "https://www.khan.co.kr/rss/rssdata/total_news.xml"),
    ("연합뉴스 정치",          "https://www.yna.co.kr/politics/index.xml"),
    ("연합뉴스 문화",          "https://www.yna.co.kr/culture/index.xml"),
    ("노컷뉴스",              "https://www.nocutnews.co.kr/rss"),

    # ── Reddit (트렌딩 이슈) ───────────────────────────────────────
    ("Reddit Korea",          "https://www.reddit.com/r/korea/top/.rss?t=day&limit=10"),

    # ── 중동 / 아프리카 / 라틴아메리카 ────────────────────────────
    ("AllAfrica",             "https://allafrica.com/tools/headlines/rdf/latest/headlines.rdf"),
    ("Merco Press",           "https://en.mercopress.com/rss"),

    # ── AI / ML 전문 블로그 ─────────────────────────────────────────
    # Simon Willison — LLM/AI 도구 최신 동향, 매우 신뢰도 높음
    ("Simon Willison",        "https://simonwillison.net/atom/everything/"),
    # Import AI — Jack Clark(Anthropic 공동창업자)의 주간 AI 뉴스
    ("Import AI",             "https://importai.substack.com/feed"),
    # Last Week in AI — 주간 AI 뉴스 큐레이션
    ("Last Week in AI",       "https://lastweekin.ai/feed"),
    # Sebastian Raschka — ML 연구/논문 해설
    ("Sebastian Raschka",     "https://magazine.sebastianraschka.com/feed"),

    # ── 빅테크 엔지니어링 블로그 ────────────────────────────────────
    # Meta Engineering — React, PyTorch, 인프라
    ("Meta Engineering",      "https://engineering.fb.com/feed/"),
    # AWS News — 클라우드 신규 서비스 발표
    ("AWS News Blog",         "https://aws.amazon.com/blogs/aws/feed/"),
    # GitHub Blog — 개발 도구, Copilot, 오픈소스
    ("GitHub Blog",           "https://github.blog/feed/"),
    # Cloudflare Blog — 네트워크, 보안, Workers
    ("Cloudflare Blog",       "https://blog.cloudflare.com/rss/"),
    # Stripe Engineering — 결제, API 설계
    ("Stripe Blog",           "https://stripe.com/blog/feed.rss"),
    # Google Developers — Google 개발자 뉴스
    ("Google Developers",     "https://developers.googleblog.com/feeds/posts/default"),

    # ── 보안 뉴스 ───────────────────────────────────────────────────
    # Krebs on Security — 사이버보안 최신 사건/취약점
    ("Krebs on Security",     "https://krebsonsecurity.com/feed/"),
    # Schneier on Security — 암호학/보안 정책 전문가
    ("Schneier on Security",  "https://www.schneier.com/feed/"),
    # The Hacker News — 가장 대중적인 사이버보안 뉴스 매체
    ("The Hacker News",       "https://thehackernews.com/feeds/posts/default"),
    # Bleeping Computer — 랜섬웨어, 취약점, 악성코드 사건 보도
    ("Bleeping Computer",     "https://www.bleepingcomputer.com/feed/"),
    # CISA Alerts — 미국 사이버보안청 공식 보안 경보
    ("CISA Alerts",           "https://www.cisa.gov/cybersecurity-advisories/all.xml"),
    # Palo Alto Unit 42 — 위협 인텔리전스, APT 분석
    ("Unit 42",               "https://unit42.paloaltonetworks.com/feed/"),
    # Malwarebytes Labs — 악성코드/랜섬웨어 분석
    ("Malwarebytes Labs",     "https://www.malwarebytes.com/blog/feed/"),
    # Recorded Future — 위협 인텔리전스
    ("Recorded Future",       "https://www.recordedfuture.com/feed"),
    # 보안 뉴스 (한국)
    ("보안뉴스",              "https://www.boannews.com/media/boannews_rss.xml"),

    # ── 개발자 커뮤니티 / 스타트업 ─────────────────────────────────
    # Stack Overflow Blog — 개발 트렌드, 설문조사
    ("Stack Overflow Blog",   "https://stackoverflow.blog/feed/"),
    # a16z — VC 시각의 기술/스타트업 트렌드
    ("a16z",                  "https://a16z.com/feed/"),
    # Y Combinator Blog — 스타트업 인사이트
    ("YC Blog",               "https://www.ycombinator.com/blog/rss"),

    # ── 하드웨어 / 반도체 ───────────────────────────────────────────
    ("ExtremeTech",           "https://www.extremetech.com/feed"),

    # ── 코인 / 크립토 ───────────────────────────────────────────────
    # CoinDesk — 글로벌 1위 크립토 미디어
    ("CoinDesk",              "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    # CoinTelegraph — 크립토 뉴스 + 분석
    ("CoinTelegraph",         "https://cointelegraph.com/rss"),
    # Decrypt — 크립토/Web3 대중 매체
    ("Decrypt",               "https://decrypt.co/feed"),
    # Bitcoin Magazine — 비트코인 전문
    ("Bitcoin Magazine",      "https://bitcoinmagazine.com/.rss/full/"),
    # 블록미디어 — 한국 크립토/블록체인 전문
    ("블록미디어",            "https://www.blockmedia.co.kr/feed"),
    # 토큰포스트 — 한국 크립토 뉴스
    ("토큰포스트",            "https://www.tokenpost.kr/rss"),

    # ── 거시경제 / 글로벌 매크로 인사이트 ──────────────────────────
    # Project Syndicate — 세계 석학/전 장관들의 경제 논평
    ("Project Syndicate",     "https://www.project-syndicate.org/rss"),
    # Peterson Institute (PIIE) — 국제경제 싱크탱크
    ("PIIE",                  "https://www.piie.com/rss.xml"),
    # Calculated Risk — 주택/경기 사이클 전문 매크로 블로그
    ("Calculated Risk",       "https://www.calculatedriskblog.com/feeds/posts/default"),
    # Macro Hive — FX/금리/원자재 매크로 분석
    ("Macro Hive",            "https://macrohive.com/feed/"),

    # ── 주식 / 투자 분석 ────────────────────────────────────────────
    # Axios Markets — 월스트리트 핵심 이슈 간결 요약
    ("Axios Markets",         "https://api.axios.com/feed/markets"),
    # Axios Pro Rata — VC/M&A/딜 소식
    ("Axios Pro Rata",        "https://api.axios.com/feed/pro-rata"),
    # Motley Fool — 개인투자자용 종목 분석
    ("Motley Fool",           "https://www.fool.com/a/feeds/featured-rss-feed.aspx"),
    # Seeking Alpha — 전문 투자자 분석 (무료 기사)
    ("Seeking Alpha",         "https://seekingalpha.com/feed.xml"),
    # 한국 주식
    ("한국경제 증권",          "https://www.hankyung.com/feed/finance"),
    ("매일경제 증권",          "https://www.mk.co.kr/rss/40300001/"),

    # ── 인사이트 / 비즈니스 분석 ────────────────────────────────────
    # Quartz — 글로벌 비즈니스 트렌드 분석
    ("Quartz",                "https://qz.com/rss"),
    # Morning Brew — 비즈니스/기술 데일리 브리핑
    ("Morning Brew",          "https://www.morningbrew.com/daily/feed"),
    # McKinsey Insights — 글로벌 컨설팅 시각
    ("McKinsey",              "https://www.mckinsey.com/rss/insights.rss"),
    # Economist (무료 기사) — 심층 글로벌 분석
    ("The Economist",         "https://www.economist.com/finance-and-economics/rss.xml"),
]
