"""Structured logging: JSON lines in production, readable console output locally.

Every log line carries the context bound with `structlog.contextvars`
(e.g. `invoice_id`, `run_id`), so one invoice can be traced end to end.
"""

import logging
import sys

import structlog


def configure_logging(level: str = "INFO", *, json: bool = False, stream: str = "stdout") -> None:
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        logger_factory=structlog.PrintLoggerFactory(
            file=sys.stderr if stream == "stderr" else sys.stdout
        ),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]
