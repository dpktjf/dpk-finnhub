"""Constants for the Finnhub integration."""

from datetime import time

DOMAIN = "finnhub"

CONF_SYMBOLS = "symbols"
CONF_MARKET_OPEN = "market_open"
CONF_MARKET_CLOSE = "market_close"


# FINNHUB_QUOTE_URL = "https://finnhub.io/api/v1/quote"
FINNHUB_QUOTE_URL = "http://127.0.0.1:5000/api/v1/quote"
# FINNHUB_MARKET_STATUS_URL = "https://finnhub.io/api/v1/stock/market-status"
FINNHUB_MARKET_STATUS_URL = "http://127.0.0.1:5000/api/v1/stock/market-status"


# Market session — NYSE/NASDAQ core hours in America/New_York
MARKET_TIMEZONE = "America/New_York"
# MARKET_OPEN = time(9, 30)
# MARKET_CLOSE = time(16, 0)
MARKET_OPEN = time(2, 39)
MARKET_CLOSE = time(5, 55)
MARKET_DAYS = frozenset({0, 1, 2, 3, 4})  # Monday=0 … Friday=4
MARKET_EXCHANGE = "US"

# How long to cache the market status response (avoid hammering the endpoint)
MARKET_STATUS_CACHE_SECONDS = 60

# Rate limiter: stay under 60/min with a safety buffer
RATE_LIMIT_CALLS = 50  # max 60 calls at source
RATE_LIMIT_PERIOD = 60.0
RATE_LIMIT_BURST = 10  # max 30 calls at source
RATE_LIMIT_BURST_PERIOD = 1.0

# Default polling interval in seconds (recalculated dynamically per symbol count)
DEFAULT_SCAN_INTERVAL_SECONDS = 60

ATTR_OPEN = "open"
ATTR_HIGH = "high"
ATTR_LOW = "low"
ATTR_PREVIOUS_CLOSE = "previous_close"
ATTR_CHANGE = "change"
ATTR_CHANGE_PERCENT = "change_percent"
ATTR_SYMBOL = "symbol"
