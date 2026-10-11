"""FastAPI dependencies: container, DB session, operator auth and a small rate limiter."""

import secrets
import threading
import time
from collections import defaultdict, deque
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from opsagent.container import Container


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


ContainerDep = Annotated[Container, Depends(get_container)]


def get_session(container: ContainerDep) -> Iterator[Session]:
    with container.session_factory() as session, session.begin():
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


def require_operator(
    container: ContainerDep, x_admin_token: Annotated[str | None, Header()] = None
) -> None:
    """Operator-only endpoints. Open when no ADMIN_TOKEN is configured (local development)."""
    expected = container.settings.admin_token
    if expected is None:
        return
    if not x_admin_token or not secrets.compare_digest(x_admin_token, expected.get_secret_value()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Operator token required")


class RateLimiter:
    """Sliding-window limit per client. In memory: fine for one instance, not for a fleet."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window_s: float = 3600) -> None:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > window_s:
                hits.popleft()
            if len(hits) >= limit:
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    "Límite de subidas alcanzado para esta demo; intenta más tarde.",
                )
            hits.append(now)


upload_limiter = RateLimiter()
