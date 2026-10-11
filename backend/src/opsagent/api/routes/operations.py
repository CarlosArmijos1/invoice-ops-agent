"""Agent runs, metrics and daily reports."""

from datetime import date
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select

from opsagent.api.deps import ContainerDep, SessionDep, require_operator
from opsagent.infra.db.models import DailyReport
from opsagent.scheduler.jobs import process_tick
from opsagent.services.demo import DemoResetNotAllowedError, reset_demo
from opsagent.services.reporting import generate_daily_report
from opsagent.services.views import AgentRunView, Stats, recent_runs, stats

router = APIRouter(prefix="/api", tags=["operations"])


@router.get("/stats", response_model=Stats)
def get_stats(session: SessionDep) -> Stats:
    return stats(session)


@router.get("/agent/runs", response_model=list[AgentRunView])
def runs(session: SessionDep) -> list[AgentRunView]:
    return recent_runs(session)


@router.post(
    "/agent/run", dependencies=[Depends(require_operator)], status_code=status.HTTP_202_ACCEPTED
)
def trigger_run(background: BackgroundTasks, container: ContainerDep) -> dict[str, str]:
    """Wake the agent now (also used by the GitHub Actions cron that keeps the demo alive)."""
    background.add_task(process_tick, container, "api")
    return {"status": "started"}


@router.get("/reports")
def list_reports(session: SessionDep) -> list[dict[str, Any]]:
    rows = session.scalars(select(DailyReport).order_by(DailyReport.report_date.desc()).limit(60))
    return [
        {"date": r.report_date.isoformat(), "processed": r.summary.get("processed")} for r in rows
    ]


@router.get("/reports/{day}")
def get_report(day: date, session: SessionDep) -> dict[str, Any]:
    report = session.scalar(select(DailyReport).where(DailyReport.report_date == day))
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No hay reporte para esa fecha")
    return {"date": day.isoformat(), "summary": report.summary, "markdown": report.markdown}


@router.post(
    "/admin/reset-demo",
    dependencies=[Depends(require_operator)],
    status_code=status.HTTP_202_ACCEPTED,
)
def reset_demo_data(background: BackgroundTasks, container: ContainerDep) -> dict[str, str]:
    """Back to the initial demo state, then let the agent process everything again."""
    try:
        reset_demo(container)
    except DemoResetNotAllowedError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    background.add_task(process_tick, container, "api")
    return {"status": "reset"}


@router.post("/reports/daily", dependencies=[Depends(require_operator)])
def build_report(session: SessionDep, day: date | None = None) -> dict[str, Any]:
    report = generate_daily_report(session, day)
    return {"date": report.report_date.isoformat(), "markdown": report.markdown}
