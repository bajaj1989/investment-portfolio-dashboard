import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
DEFAULT_BACKUP_DIR = DATA_DIR / "backups"
TAX_RULES_PATH = BASE_DIR / "config" / "tax_rules.yaml"
LOG_DIR = DATA_DIR / "logs"

DB_URL = os.environ.get("PORTFOLIO_DB_URL", f"sqlite:///{(DATA_DIR / 'portfolio.db').as_posix()}")

KEYRING_SERVICE = "investment_portfolio_dashboard"

ASSET_CLASSES = ["stock", "mf", "crypto", "fd"]
ASSET_LABELS = {"stock": "Stocks", "mf": "Mutual Funds", "crypto": "Crypto", "fd": "Fixed Deposits"}

for _d in (DATA_DIR, UPLOAD_DIR, LOG_DIR):
    _d.mkdir(parents=True, exist_ok=True)
