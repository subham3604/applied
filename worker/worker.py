import os
import sys
import logging
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("worker")

def poll_job():
    logger.info("Polling trigger fired at %s", datetime.utcnow().isoformat())
    # Worker logic to be populated in Phase 2

if __name__ == "__main__":
    logger.info("Autonomous Career Pipeline Worker started.")
    logger.info("Database URL configured: %s", bool(os.getenv("DATABASE_URL")))
    # For initial scaffold, log readiness
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
        scheduler = BlockingScheduler()
        scheduler.add_job(poll_job, "interval", minutes=15)
        logger.info("APScheduler initialized. Polling interval: 15 minutes.")
        # When running in container, uncomment scheduler.start()
        # For now, run one dry check
        poll_job()
    except ImportError:
        logger.warning("APScheduler not installed in current environment.")
