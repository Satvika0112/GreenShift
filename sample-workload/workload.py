#!/usr/bin/env python3
"""
GreenShift Sample Workload

A simple CPU-bound workload that runs for DURATION_SECONDS and exits successfully.
Used to demonstrate real Kubernetes Job execution.

Environment variables:
  JOB_ID           — GreenShift job identifier
  TEAM_ID          — Team identifier
  DURATION_SECONDS — How long to run (default: 60)
"""

import os
import sys
import time
import math
import logging
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("greenshift-workload")


def cpu_work(duration_seconds: int) -> None:
    """Simulate CPU-bound compute work."""
    start = time.monotonic()
    iterations = 0
    while time.monotonic() - start < duration_seconds:
        # CPU-bound work: compute primes
        n = 10000 + iterations
        _ = all(n % i != 0 for i in range(2, int(math.sqrt(n)) + 1))
        iterations += 1
        if iterations % 5000 == 0:
            elapsed = time.monotonic() - start
            logger.info(f"Progress: {elapsed:.1f}s / {duration_seconds}s elapsed")


def main() -> None:
    job_id          = os.environ.get("JOB_ID", "UNKNOWN")
    team_id         = os.environ.get("TEAM_ID", "UNKNOWN")
    duration        = int(os.environ.get("DURATION_SECONDS", "60"))

    logger.info("=" * 60)
    logger.info(f"GreenShift Sample Workload Starting")
    logger.info(f"  Job ID  : {job_id}")
    logger.info(f"  Team    : {team_id}")
    logger.info(f"  Duration: {duration}s")
    logger.info(f"  Started : {datetime.now(timezone.utc).isoformat()}")
    logger.info("=" * 60)

    cpu_work(duration)

    logger.info("=" * 60)
    logger.info(f"GreenShift Sample Workload COMPLETED")
    logger.info(f"  Finished: {datetime.now(timezone.utc).isoformat()}")
    logger.info("=" * 60)

    sys.exit(0)


if __name__ == "__main__":
    main()
