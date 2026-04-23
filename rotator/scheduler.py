import yaml
import logging
from pathlib import Path
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from .core import rotate_key

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def run(config_path: Path) -> None:
    if not config_path.exists():
        log.warning("Config not found at %s — scheduler will wait and retry on next restart", config_path)
        log.warning("Create config: cp %s/config.example.yaml %s", "/home/z/Projects/key-rotator", config_path)
        import time; time.sleep(3600)  # sleep so systemd doesn't spin-restart
        return
    config = yaml.safe_load(config_path.read_text())
    scheduler = BlockingScheduler(timezone="UTC")
    scheduled = 0

    for key in config.get("keys", []):
        schedule = key.get("schedule")
        if not schedule:
            continue
        parts = schedule.split()
        if len(parts) != 5:
            log.warning("Invalid cron expression for %s: %r — skipping", key["id"], schedule)
            continue

        trigger = CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=parts[4],
            timezone="UTC",
        )
        scheduler.add_job(
            _rotate_job,
            trigger=trigger,
            args=[key],
            id=key["id"],
            name=f"rotate-{key['id']}",
            misfire_grace_time=3600,  # allow up to 1h late if machine was asleep
        )
        log.info("Scheduled %s → %s (UTC)", key["id"], schedule)
        scheduled += 1

    if scheduled == 0:
        log.warning("No keys with schedules found in config. Scheduler will run but do nothing.")

    log.info("Scheduler started with %d job(s)", scheduled)
    scheduler.start()


def _rotate_job(key_config: dict) -> None:
    """Wrapper so APScheduler can call rotate_key without interactive prompts."""
    try:
        rotate_key(key_config, dry_run=False)
    except Exception as e:
        log.error("Unhandled error rotating %s: %s", key_config.get("id"), e)
