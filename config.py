"""
Bot configuration. Sensitive values (private key, address) are read from
environment variables so they are never hard-coded in source.

    set POLYMARKET_PRIVATE_KEY=0x...
    set POLYMARKET_WALLET_ADDRESS=0x...

The numbers below are conservative demo values, not tuned settings.
"""

import os

# -- Wallet ----------------------------------------------------------------------
WALLET_PRIVATE_KEY = os.getenv("POLYMARKET_PRIVATE_KEY", "")
WALLET_ADDRESS = os.getenv("POLYMARKET_WALLET_ADDRESS", "")

# -- Trading mode ----------------------------------------------------------------
# Leave True. Live trading needs a configured wallet and your own review.
PAPER_TRADING = True

# -- Market filter ---------------------------------------------------------------
# None = consider every supported market type, or e.g. {"totals"}.
ALLOWED_MARKET_TYPES = None

# -- Signal thresholds -----------------------------------------------------------
MIN_EDGE = 0.10            # minimum |fair_prob - clob_mid| to trigger a bet
MIN_DEPTH_SHARES = 100     # minimum shares of liquidity on the side we're buying

# -- Position sizing -------------------------------------------------------------
BANKROLL = 1000.0          # total USDC available for betting
KELLY_FRACTION = 0.10      # fraction of full Kelly to use
MAX_POSITION_USD = 10.0    # hard cap per bet regardless of Kelly output

# -- Order parameters ------------------------------------------------------------
ORDER_EXPIRY_MINUTES = 5   # GTC orders cancelled after this many minutes

# -- Bot loop --------------------------------------------------------------------
POLL_INTERVAL_SEC = 30     # seconds between market scans
