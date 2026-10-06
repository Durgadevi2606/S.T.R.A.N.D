"""
S.T.R.A.N.D — Celery Task Definitions

Wraps the pipeline orchestrator as an async Celery task for
background execution with Redis as the message broker.
"""

from __future__ import annotations

import logging

from celery import Celery

from strand.config import get_settings

logger = logging.getLogger(__name__)

# Initialize Celery app
settings = get_settings()
celery_app = Celery(
    "strand",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour max
    task_soft_time_limit=3300,  # Soft limit at 55 min
    worker_prefetch_multiplier=1,  # One task at a time
    worker_max_tasks_per_child=5,  # Restart worker after 5 tasks
)


@celery_app.task(bind=True, name="strand.run_analysis")
def run_analysis_task(self, request_data: dict, analysis_id: str) -> dict:
    """
    Celery task to run the full analysis pipeline.

    Args:
        request_data: Serialized AnalysisRequest dict.
        analysis_id: Unique analysis identifier.

    Returns:
        Result dict with analysis_id, status, summary.
    """
    from strand.models import AnalysisRequest
    from strand.pipeline.orchestrator import run_pipeline

    logger.info("Celery task started: analysis=%s", analysis_id)

    # Deserialize request
    request = AnalysisRequest(**request_data)

    # Progress callback that updates Celery task state
    def progress_callback(update: dict):
        self.update_state(
            state="PROGRESS",
            meta={
                "phase": update.get("phase"),
                "progress_pct": update.get("progress_pct"),
                "message": update.get("message"),
            },
        )

    try:
        result = run_pipeline(
            request=request,
            analysis_id=analysis_id,
            progress_callback=progress_callback,
        )
        logger.info("Celery task completed: analysis=%s", analysis_id)
        return result

    except Exception as e:
        logger.error("Celery task failed: analysis=%s, error=%s", analysis_id, e)
        raise
