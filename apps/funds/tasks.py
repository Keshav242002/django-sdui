"""
Celery tasks for the funds app (PRD §10, §9A).

Every task here is a thin wrapper around a service function in
apps/funds/services.py -- no business logic is duplicated here
(rules.md §2). Task arguments and return values are kept JSON-safe
(CELERY_TASK_SERIALIZER = "json"): user_id is always a str, never a
UUID, and return values are small dicts for log/debug visibility only --
nothing reads them.

All tasks are ignore_result=True: with nothing reading a result, there
is no reason to pay for one. This also matters for the broker-down
fallback at the .delay() call sites (apps/funds/models.py,
apps/screens/services.py) -- without it, .delay() also opens a result
backend connection (same Redis) to track the task, and that failure
surfaces as a plain RuntimeError, not kombu.exceptions.OperationalError,
which those call sites don't catch. ignore_result=True skips that
connection entirely, so a dead Redis is only ever an OperationalError.

Fault tolerance for the nightly batch (plan.md Key Decisions §14):
  - recompute_all_portfolio_snapshots has Celery autoretry (max 3,
    exponential backoff with jitter) for whole-task infra errors.
  - Per-user failures inside the loop write a FailedTaskRecompute (DLQ)
    row in addition to logging a WARNING.
  - retry_failed_portfolio_recomputes (beat: every 15 min) picks up
    FAILED rows and retries them, self-healing users within 15-45 min.
"""

import logging
import traceback

from celery import shared_task
from django.db import OperationalError as DjangoDatabaseError
from django.utils import timezone
from kombu.exceptions import OperationalError as BrokerOperationalError

from apps.common.cache import cache_client, widget_cache_key
from apps.funds.models import FailedTaskRecompute, Fund, Portfolio
from apps.funds.services import (
    TOP_MOVERS_TTL,
    TRENDING_FUNDS_TTL,
    _serialize_fund_rows,
    compute_portfolio_snapshot,
)

logger = logging.getLogger(__name__)


@shared_task(ignore_result=True)
def recompute_top_movers() -> dict:
    """Beat: every 5 min (config.settings.CELERY_BEAT_SCHEDULE)."""
    funds = Fund.objects.order_by("-one_day_change_pct")[:10]
    data = _serialize_fund_rows(funds)
    cache_client.set(widget_cache_key("top_movers"), data, ttl=TOP_MOVERS_TTL)
    logger.info("recompute_top_movers: wrote %d rows", len(data))
    return {"rows": len(data)}


@shared_task(ignore_result=True)
def recompute_trending() -> dict:
    """Beat: every 15 min (config.settings.CELERY_BEAT_SCHEDULE)."""
    funds = Fund.objects.filter(is_trending=True)[:10]
    data = _serialize_fund_rows(funds)
    cache_client.set(widget_cache_key("trending_funds"), data, ttl=TRENDING_FUNDS_TTL)
    logger.info("recompute_trending: wrote %d rows", len(data))
    return {"rows": len(data)}


@shared_task(ignore_result=True)
def recompute_portfolio_snapshot(user_id: str) -> dict:
    """
    Triggered on Transaction save (apps.funds.models.on_transaction_saved),
    dispatched via transaction.on_commit so this never runs before the
    triggering Transaction/Holding rows are actually committed.
    """
    snapshot = compute_portfolio_snapshot(user_id)
    return {"user_id": user_id, "created": snapshot is not None}


@shared_task(
    bind=True,
    ignore_result=True,
    # Whole-task autoretry for transient broker / DB infra errors
    # (plan.md Key Decisions §14). Per-user errors are caught inside the
    # loop and written to the DLQ instead of bubbling up here.
    autoretry_for=(DjangoDatabaseError, BrokerOperationalError),
    max_retries=3,
    retry_backoff=True,       # 2 s → 4 s → 8 s
    retry_backoff_max=300,    # cap at 5 min
    retry_jitter=True,        # add randomness to avoid thundering herd
)
def recompute_all_portfolio_snapshots(self) -> dict:
    """
    Beat: daily at 01:30 UTC, standing in for "runs after the daily NAV
    update window" (PRD §9A) -- this project has no real NAV feed, so it
    simply recomputes every portfolio against whatever Fund.nav values
    are in the DB at that time.

    Whole-task failures (e.g. broker drop, DB connection reset) are
    retried automatically up to 3 times with exponential backoff
    (plan.md Key Decisions §14).

    Per-user failures inside the loop are isolated: the exception is
    logged AND written to FailedTaskRecompute (DLQ) so
    retry_failed_portfolio_recomputes can self-heal them within 15-45
    min without any engineer intervention.

    Iterates in-process rather than fanning out N .delay() calls -- at
    seed scale a fan-out only adds broker round-trips for no benefit
    (plan.md Key Decisions §10).
    """
    user_ids = Portfolio.objects.values_list("user_id", flat=True)
    processed = 0
    failed = 0
    for user_id in user_ids:
        try:
            compute_portfolio_snapshot(str(user_id))
            processed += 1
        except Exception as exc:
            failed += 1
            error_text = traceback.format_exc()
            logger.warning(
                "recompute_all_portfolio_snapshots: failed for user_id=%s -- written to DLQ",
                user_id,
                exc_info=True,
            )
            # Persist to the DB DLQ so the retry beat task can self-heal
            # this user without waiting for tomorrow's batch run.
            try:
                FailedTaskRecompute.objects.create(
                    user_id=user_id,
                    error=error_text,
                )
            except Exception:
                # DLQ write must never abort the outer loop.
                logger.error(
                    "recompute_all_portfolio_snapshots: could not write DLQ row for user_id=%s",
                    user_id,
                    exc_info=True,
                )

    logger.info("recompute_all_portfolio_snapshots: processed=%d failed=%d", processed, failed)
    return {"processed": processed, "failed": failed}


@shared_task(ignore_result=True)
def retry_failed_portfolio_recomputes() -> dict:
    """
    Beat: every 15 min (config.settings.CELERY_BEAT_SCHEDULE).

    Picks up FailedTaskRecompute rows with status=FAILED and retries
    compute_portfolio_snapshot for each one. On success the row is
    marked RECOVERED. After MAX_RETRY_ATTEMPTS the row is marked
    EXHAUSTED and left for manual investigation via the Django Admin.

    This self-heals users whose nightly snapshot failed within 15-45
    minutes, without requiring any engineer action for transient failures
    (plan.md Key Decisions §14, PRD §10).
    """
    pending = FailedTaskRecompute.objects.filter(
        status=FailedTaskRecompute.Status.FAILED
    ).order_by("failed_at")

    recovered = 0
    exhausted = 0
    skipped = 0

    for dlq_row in pending:
        dlq_row.attempts += 1

        if dlq_row.attempts > FailedTaskRecompute.MAX_RETRY_ATTEMPTS:
            # Already hit the attempt ceiling -- mark exhausted and move on.
            dlq_row.status = FailedTaskRecompute.Status.EXHAUSTED
            dlq_row.resolved_at = timezone.now()
            dlq_row.save(update_fields=["status", "resolved_at", "attempts"])
            exhausted += 1
            logger.warning(
                "retry_failed_portfolio_recomputes: user_id=%s exhausted after %d attempts",
                dlq_row.user_id,
                dlq_row.attempts,
            )
            continue

        try:
            compute_portfolio_snapshot(str(dlq_row.user_id))
            dlq_row.status = FailedTaskRecompute.Status.RECOVERED
            dlq_row.resolved_at = timezone.now()
            dlq_row.save(update_fields=["status", "resolved_at", "attempts"])
            recovered += 1
            logger.info(
                "retry_failed_portfolio_recomputes: recovered user_id=%s on attempt %d",
                dlq_row.user_id,
                dlq_row.attempts,
            )
        except Exception:
            # Save the incremented attempt count; keep status=FAILED so
            # the next beat run picks it up again.
            dlq_row.save(update_fields=["attempts"])
            skipped += 1
            logger.warning(
                "retry_failed_portfolio_recomputes: still failing for user_id=%s (attempt %d/%d)",
                dlq_row.user_id,
                dlq_row.attempts,
                FailedTaskRecompute.MAX_RETRY_ATTEMPTS,
                exc_info=True,
            )

    logger.info(
        "retry_failed_portfolio_recomputes: recovered=%d exhausted=%d still_failing=%d",
        recovered,
        exhausted,
        skipped,
    )
    return {"recovered": recovered, "exhausted": exhausted, "still_failing": skipped}

