from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str
    NEO4J_URI: str
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str
    REDIS_URL: str = "redis://localhost:6379"

    OLLAMA_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.1:8b"
    ANTHROPIC_API_KEY: Optional[str] = None

    CHROMADB_DIR: str = "./data/chromadb"

    ACLED_API_KEY: Optional[str] = None
    ACLED_EMAIL: Optional[str] = None
    NASA_FIRMS_KEY: Optional[str] = None
    OPENSKY_USERNAME: Optional[str] = None
    OPENSKY_PASSWORD: Optional[str] = None

    FRONTEND_URL: str = "http://localhost:3000"
    API_SECRET_KEY: str
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"

    SENDGRID_API_KEY: Optional[str] = None
    ALERT_EMAIL_TO: Optional[str] = None

    # ── RSS & News ──
    RSS_PROXY_ENABLED: bool = False
    RSS_PROXY_URL: Optional[str] = None

    # ── Government Advisories / Aviation ──
    ICAO_API_KEY: Optional[str] = None
    AVIATIONSTACK_API_KEY: Optional[str] = None
    FAA_ASWS_ENABLED: bool = True

    # ── Cybersecurity ──
    ALIENVAULT_OTX_KEY: Optional[str] = None
    ABUSEIPDB_API_KEY: Optional[str] = None

    # ── Financial ──
    FRED_API_KEY: Optional[str] = None
    EIA_API_KEY: Optional[str] = None
    FINNHUB_API_KEY: Optional[str] = None
    COINGECKO_API_KEY: Optional[str] = None

    # ── Internet / GPS ──
    CLOUDFLARE_API_TOKEN: Optional[str] = None

    # ── Humanitarian ──
    HAPI_APP_IDENTIFIER: Optional[str] = None
    UNHCR_API_TOKEN: Optional[str] = None

    # ── OREF ──
    OREF_PROXY_URL: Optional[str] = None

    # ── Polymarket ──
    POLYMARKET_ENABLED: bool = True

    # ── WTO / BIS ──
    WTO_FEEDS_ENABLED: bool = True
    BIS_FEEDS_ENABLED: bool = True

    # ── Live Streams ──
    LIVE_STREAMS_ENABLED: bool = True

    # ── Phase 2 Integration ──
    NASA_EARTHDATA_TOKEN: Optional[str] = None
    OPENSKY_CLIENT_ID: Optional[str] = None
    OPENSKY_CLIENT_SECRET: Optional[str] = None
    IPINFO_TOKEN: Optional[str] = None
    AISSTREAM_API_KEY: Optional[str] = None
    UCDP_ENABLED: bool = True
    NGA_NAVWARNINGS_ENABLED: bool = True

    # ── News Scraper Agent ─────────────────────────────────────────────
    PLAYWRIGHT_ENABLED:           bool = True
    PLAYWRIGHT_HEADLESS:          bool = True
    WORLD_MONITOR_WS_ENABLED:     bool = True
    WORLD_MONITOR_POLL_INTERVAL:  int  = 180    # seconds
    PLAYWRIGHT_POLL_INTERVAL:     int  = 900    # seconds (15 min — expensive)
    AI_DIRECTOR_POLL_INTERVAL:    int  = 1800   # seconds (30 min)
    SCRAPER_MAX_SIGNALS_PER_RUN:  int  = 50
    SCRAPER_RATE_LIMIT_DEFAULT:   int  = 8      # seconds between requests to same domain

    # ── MiroFish Plugin ──
    MIROFISH_ENABLED: bool = False
    MIROFISH_URL: str = "http://localhost:5001"
    MIROFISH_API_KEY: Optional[str] = None
    MIROFISH_NUM_AGENTS: int = 500
    MIROFISH_SIMULATION_ROUNDS: int = 10
    MIROFISH_TIMEOUT_SECONDS: int = 120
    MIROFISH_ZEP_API_KEY: Optional[str] = None


settings = Settings()


def get_settings() -> Settings:
    return settings
