"""Scheduled jobs. Run: python -m jobs.daily_job [daily|crypto|backup|history]"""
import argparse
import logging
import sys
from datetime import datetime, timedelta

from core import config, portfolio, snapshot
from jobs import alerts, backup, telegram

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.FileHandler(config.LOG_DIR / "jobs.log", encoding="utf-8"), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("jobs")


def update_prices(crypto_only: bool = False) -> list[str]:
    from prices import amfi, coingecko, fx, nse

    steps = [("USD/INR rate", fx.update), ("Crypto", coingecko.update_latest)]
    if not crypto_only:
        steps = [("Mutual fund NAVs", amfi.update_latest), ("Stocks", nse.update), ("Stock sectors", nse.fill_sectors)] + steps
    errors = []
    for label, fn in steps:
        try:
            n = fn()
            log.info("%s: %s prices saved", label, n)
        except Exception as e:  # one failing feed shouldn't stop the others
            log.exception("%s update failed", label)
            errors.append(f"{label}: {e}")
    return errors


def send_alerts(p, summary: bool, errors: list[str]):
    pending = alerts.collect(p)
    key = f"summary:{p.as_of}"
    if summary and not alerts.was_sent(key):
        pending.insert(0, (key, alerts.daily_summary(p, errors)))
    if pending and telegram.send("\n\n".join(m for _, m in pending)):
        alerts.mark_sent([k for k, _ in pending])


def daily():
    errors = update_prices()
    p = portfolio.load()
    snapshot.take(p.as_of, p)
    send_alerts(p, summary=True, errors=errors)
    last = backup.last_backup()
    if last is None or datetime.now() - last > timedelta(days=7):
        log.info("Backup saved to %s", backup.run())


def crypto():
    update_prices(crypto_only=True)
    p = portfolio.load()
    snapshot.take(p.as_of, p)
    send_alerts(p, summary=False, errors=[])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", nargs="?", default="daily", choices=["daily", "crypto", "backup", "history"])
    mode = ap.parse_args().mode
    log.info("Job started: %s", mode)
    if mode == "daily":
        daily()
    elif mode == "crypto":
        crypto()
    elif mode == "backup":
        log.info("Backup saved to %s", backup.run())
    elif mode == "history":
        log.info("Rebuilt %s snapshots", snapshot.rebuild_history(lambda f, m: log.info("%3.0f%% %s", f * 100, m)))
    log.info("Job finished: %s", mode)


if __name__ == "__main__":
    main()
