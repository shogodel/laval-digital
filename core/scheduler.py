import logging
import uuid
from datetime import datetime, UTC
from typing import Any

from core import database

logger = logging.getLogger(__name__)

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    HAS_APSCHEDULER = True
except ImportError:
    HAS_APSCHEDULER = False
    logger.info("apscheduler not installed — scheduled tasks disabled. Install: pip install apscheduler")


class SchedulerManager:
    def __init__(self, get_orchestrator_func):
        self._get_orch = get_orchestrator_func
        self._scheduler: Any | None = None

    def _conn(self):
        return database._get_conn()

    @property
    def enabled(self) -> bool:
        return HAS_APSCHEDULER

    def start(self):
        if not HAS_APSCHEDULER or self._scheduler:
            return
        self._scheduler = BackgroundScheduler(daemon=True)
        self._load_schedules()

    def stop(self):
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None

    def _load_schedules(self):
        if not self._scheduler:
            return
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM agent_schedules WHERE enabled = 1"
        ).fetchall()
        for row in rows:
            try:
                self._scheduler.add_job(
                    func=self._run_task,
                    trigger=CronTrigger.from_crontab(row["cron_expr"]),
                    id=row["id"],
                    args=[row["id"], row["user_id"], row["agent_id"],
                          row["task_template"], row["language"]],
                    replace_existing=True,
                )
            except Exception as e:
                logger.warning("Failed to schedule job %s: %s", row["id"], e)

    def _run_task(self, schedule_id: str, user_id: int, agent_id: str,
                  task: str, language: str):
        try:
            orch = self._get_orch()
            orch.process_message(
                user_message=task,
                thread_id=f"sched-{agent_id}-{schedule_id}-{uuid.uuid4().hex[:8]}",
                language=language,
                user_id=user_id,
            )
            now = datetime.now(UTC).isoformat()
            conn = self._conn()
            conn.execute(
                "UPDATE agent_schedules SET last_run = ? WHERE id = ?",
                (now, schedule_id),
            )
            conn.commit()
        except Exception as e:
            logger.error("Scheduled task %s failed: %s", schedule_id, e)

    def create_schedule(self, user_id: int, agent_id: str, task_template: str,
                        cron_expr: str, language: str = "en") -> str:
        schedule_id = uuid.uuid4().hex[:12]
        now = datetime.now(UTC).isoformat()
        conn = self._conn()
        conn.execute(
            """INSERT INTO agent_schedules (id, user_id, agent_id, task_template, cron_expr, enabled, language, created_at)
               VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
            (schedule_id, user_id, agent_id, task_template, cron_expr, language, now),
        )
        conn.commit()
        if self._scheduler:
            try:
                self._scheduler.add_job(
                    func=self._run_task,
                    trigger=CronTrigger.from_crontab(cron_expr),
                    id=schedule_id,
                    args=[schedule_id, user_id, agent_id, task_template, language],
                    replace_existing=True,
                )
            except Exception as e:
                logger.warning("Failed to add job to scheduler: %s", e)
        return schedule_id

    def get_schedules(self, user_id: int | None = None) -> list[dict[str, Any]]:
        conn = self._conn()
        if user_id is not None:
            rows = conn.execute(
                "SELECT * FROM agent_schedules WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM agent_schedules ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]
