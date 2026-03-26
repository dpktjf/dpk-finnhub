"""Constants for the Finnhub integration."""

from datetime import time

DOMAIN = "finnhub"

CONF_SYMBOLS = "symbols"
CONF_MARKET_OPEN = "market_open"
CONF_MARKET_CLOSE = "market_close"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_LEVELS = "levels"
DEFAULT_SCAN_INTERVAL_MINUTES = 5

# Price level keys
LEVEL_UPPER_1 = "upper_1"
LEVEL_UPPER_2 = "upper_2"
LEVEL_LOWER_1 = "lower_1"
LEVEL_LOWER_2 = "lower_2"
ALL_LEVELS = [LEVEL_UPPER_1, LEVEL_UPPER_2, LEVEL_LOWER_1, LEVEL_LOWER_2]

# Per-ticker config entity defaults
EVENT_PRICE_TRIGGER = "finnhub_price_trigger"
STATE_ALERTS_ENTITY_SUFFIX = "_alerts"
STATE_HYSTERESIS_ENTITY_SUFFIX = "_hysteresis"
DEFAULT_HYSTERESIS = 0.5  # USD — price must move this far back before re-alerting
MIN_HYSTERESIS = 0.0
MAX_HYSTERESIS = 50.0

FINNHUB_QUOTE_URL = "https://finnhub.io/api/v1/quote"
FINNHUB_MARKET_STATUS_URL = "https://finnhub.io/api/v1/stock/market-status"
# FINNHUB_QUOTE_URL = "http://127.0.0.1:5000/api/v1/quote"  # noqa: ERA001
# FINNHUB_MARKET_STATUS_URL = "http://127.0.0.1:5000/api/v1/stock/market-status"  # noqa: ERA001

# Market session — NYSE/NASDAQ core hours in America/New_York
MARKET_TIMEZONE = "America/New_York"
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)
MARKET_DAYS = frozenset({0, 1, 2, 3, 4})  # Monday=0 … Friday=4
MARKET_EXCHANGE = "US"

# How long to cache the market status response (avoid hammering the endpoint)
MARKET_STATUS_CACHE_SECONDS = 60

# Scan interval limits (in minutes)
MIN_SCAN_INTERVAL_MINUTES = 1
MAX_SCAN_INTERVAL_MINUTES = 60

# Rate limiter: stay under 60/min with a safety buffer
RATE_LIMIT_CALLS = 50  # max 60 calls at source
RATE_LIMIT_PERIOD = 60.0
RATE_LIMIT_BURST = 10  # max 30 calls at source
RATE_LIMIT_BURST_PERIOD = 1.0

# Backoff config
RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY = 0.5  # seconds
RETRY_MAX_DELAY = 10.0  # seconds
RETRY_JITTER = 0.25  # ± fraction of delay to add randomness

# Health sensor states
HEALTH_OK = "ok"
HEALTH_DEGRADED = "degraded"  # some symbols failed, others succeeded
HEALTH_PARTIAL = "partial"  # all retries exhausted for one or more symbols
HEALTH_ERROR = "error"  # coordinator update failed entirely
HEALTH_PAUSED = "paused"  # outside market hours

ATTR_OPEN = "open"
ATTR_HIGH = "high"
ATTR_LOW = "low"
ATTR_PREVIOUS_CLOSE = "previous_close"
ATTR_CHANGE = "change"
ATTR_CHANGE_PERCENT = "change_percent"
ATTR_SYMBOL = "symbol"
ATTR_DATA_AS_OF = "data_as_of"
ATTR_DATA_STALE = "data_stale"
