"""Scheduled agent tasks — run agents on a timer.

Uses APScheduler for in-process scheduling. Stores schedules in the
platform DB. Tasks run in background threads and use the orchestrator
to process messages on behalf of the tenant.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    HAS_APSCHEDULER = True
except ImportError:
    HAS_APSCHEDULER = False
    logger.info("apscheduler not installed — scheduled tasks disabled. Install: pip install apscheduler")


SCHEDULES_TABLE_DDL = """CREATE TABLE IF NOT EXISTS agent_schedules (
    id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, agent_id TEXT NOT NULL,
    task_template TEXT NOT NULL, cron_expr TEXT NOT NULL,
    enabled INTEGER DEFAULT 1, language TEXT DEFAULT 'en',
    created_at TEXT NOT NULL, last_run TEXT
)"""


class SchedulerManager:
    def __init__(self, tenant_manager, get_orchestrator_func):
        self._tm = tenant_manager
        self._get_orch = get_orchestrator_func
        self._scheduler: Optional[Any] = None
        self._ensure_db()

    def _ensure_db(self):
        try:
            self._tm.create_tenant_database("_scheduler", "direct")
        except Exception:
            pass
        conn = self._tm.get_connection("_scheduler")
        conn.execute(SCHEDULES_TABLE_DDL)
        conn.commit()

    def _conn(self):
        return self._tm.get_connection("_scheduler")

    @property
    def enabled(self) -> bool:
        return HAS_APSCHEDULER

    def start(self):
        if not HAS_APSCHEDULER or self._scheduler:
            return
        self._scheduler = BackgroundScheduler(daemon=True)
        self._load_schedules()
        self._scheduler.start()
        logger.info("Scheduler started")

    def stop(self):
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None

    def _load_schedules(self):
        for s in self.get_schedules():
            if s.get("enabled"):
                self._add_job(s)

    def _add_job(self, s: Dict[str, Any]):
        if not self._scheduler:
            return
        try:
            self._scheduler.add_job(
                func=self._run_task,
                trigger=CronTrigger.from_crontab(s["cron_expr"]),
                args=[s["id"], s["tenant_id"], s["agent_id"], s["task_template"], s.get("language", "en")],
                id=s["id"],
                replace_existing=True,
                misfire_grace_time=300,
            )
        except Exception as e:
            logger.warning("Failed to schedule job %s: %s", s["id"], e)

    def _run_task(self, schedule_id: str, tenant_id: str, agent_id: str, task: str, language: str):
        try:
            orch = self._get_orch()
            result = orch.process_message_with_autonomy(
                user_message=task,
                thread_id=f"sched-{agent_id}-{schedule_id}-{uuid.uuid4().hex[:8]}",
                language=language,
                tenant_id=tenant_id,
            )
            now = datetime.now(timezone.utc).isoformat()
            conn = self._conn()
            conn.execute("UPDATE agent_schedules SET last_run = ? WHERE id = ?", (now, schedule_id))
            conn.commit()
            logger.info("Scheduled task %s completed: %s", schedule_id, result.get("status"))
        except Exception as e:
            logger.error("Scheduled task %s failed: %s", schedule_id, e)

    def create_schedule(self, tenant_id: str, agent_id: str, task_template: str, cron_expr: str, language: str = "en") -> str:
        sid = uuid.uuid4().hex[:12]
        conn = self._conn()
        conn.execute(
            "INSERT INTO agent_schedules (id, tenant_id, agent_id, task_template, cron_expr, enabled, language, created_at) "
            "VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
            (sid, tenant_id, agent_id, task_template, cron_expr, language, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        s = {"id": sid, "tenant_id": tenant_id, "agent_id": agent_id, "task_template": task_template,
             "cron_expr": cron_expr, "language": language, "enabled": True}
        self._add_job(s)
        return sid

    def delete_schedule(self, schedule_id: str) -> bool:
        if self._scheduler:
            try:
                self._scheduler.remove_job(schedule_id)
            except Exception:
                pass
        conn = self._conn()
        conn.execute("DELETE FROM agent_schedules WHERE id = ?", (schedule_id,))
        conn.commit()
        return conn.total_changes > 0

    def toggle_schedule(self, schedule_id: str, enabled: bool) -> bool:
        conn = self._conn()
        conn.execute("UPDATE agent_schedules SET enabled = ? WHERE id = ?", (int(enabled), schedule_id))
        conn.commit()
        s = self.get_schedule(schedule_id)
        if s:
            if enabled:
                self._add_job(s)
            elif self._scheduler:
                try:
                    self._scheduler.remove_job(schedule_id)
                except Exception:
                    pass
        return True

    def get_schedule(self, schedule_id: str) -> Optional[Dict[str, Any]]:
        conn = self._conn()
        row = conn.execute(
            "SELECT id, tenant_id, agent_id, task_template, cron_expr, enabled, language, created_at, last_run "
            "FROM agent_schedules WHERE id = ?", (schedule_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_schedules(self, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
        conn = self._conn()
        if tenant_id:
            rows = conn.execute(
                "SELECT id, tenant_id, agent_id, task_template, cron_expr, enabled, language, created_at, last_run "
                "FROM agent_schedules WHERE tenant_id = ? ORDER BY created_at DESC", (tenant_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, tenant_id, agent_id, task_template, cron_expr, enabled, language, created_at, last_run "
                "FROM agent_schedules ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]
