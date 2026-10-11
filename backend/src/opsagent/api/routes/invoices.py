import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field

from opsagent.api.deps import ContainerDep, SessionDep, require_operator, upload_limiter
from opsagent.domain.schemas import DecisionAction, InvoiceSource, InvoiceStatus, ReviewOutcome
from opsagent.extraction.documents import (
    MAX_FILE_BYTES,
    UnsupportedDocumentError,
    render_page_png,
)
from opsagent.infra.db.models import Invoice, InvoiceFile
from opsagent.services.ingestion import ingest_bytes
from opsagent.services.reviews import ReviewError, review_invoice
from opsagent.services.views import InvoiceDetail, InvoiceSummary, invoice_detail, list_invoices

router = APIRouter(prefix="/api/invoices", tags=["invoices"])


class InvoicePage(BaseModel):
    items: list[InvoiceSummary]
    total: int


class UploadResponse(BaseModel):
    invoice_id: uuid.UUID
    created: bool
    message: str


class ReviewRequest(BaseModel):
    outcome: ReviewOutcome
    reviewer: str = Field(min_length=1, max_length=60)
    note: str = Field("", max_length=2000)


@router.get("", response_model=InvoicePage)
def list_(
    session: SessionDep,
    status_: Annotated[InvoiceStatus | None, Query(alias="status")] = None,
    action: DecisionAction | None = None,
    needs_review: bool = False,
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> InvoicePage:
    items, total = list_invoices(
        session,
        status=status_,
        action=action,
        needs_review=needs_review,
        query=q,
        limit=limit,
        offset=offset,
    )
    return InvoicePage(items=items, total=total)


@router.get("/{invoice_id}", response_model=InvoiceDetail)
def detail(invoice_id: uuid.UUID, session: SessionDep) -> InvoiceDetail:
    view = invoice_detail(session, invoice_id)
    if view is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Factura no encontrada")
    return view


@router.get("/{invoice_id}/file")
def file(invoice_id: uuid.UUID, session: SessionDep) -> Response:
    invoice = session.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Factura no encontrada")
    stored = session.get_one(InvoiceFile, invoice.file_sha256)
    return Response(
        content=stored.content,
        media_type=stored.media_type,
        headers={
            "Content-Disposition": f'inline; filename="{invoice.original_filename}"',
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.get("/{invoice_id}/pages/{page}")
def page_preview(invoice_id: uuid.UUID, page: int, session: SessionDep) -> Response:
    """PNG preview of one page. Browsers (especially mobile) render PDFs inline unreliably."""
    invoice = session.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Factura no encontrada")
    stored = session.get_one(InvoiceFile, invoice.file_sha256)
    try:
        png = render_page_png(stored.content, page)
    except IndexError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Página inexistente") from exc
    return Response(
        content=png, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"}
    )


@router.post("", response_model=UploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload(
    request: Request,
    file: UploadFile,
    background: BackgroundTasks,
    container: ContainerDep,
) -> UploadResponse:
    client = request.client.host if request.client else "unknown"
    upload_limiter.check(client, container.settings.upload_limit_per_hour)
    content = await file.read(MAX_FILE_BYTES + 1)
    try:
        with container.session_factory() as session, session.begin():
            result = ingest_bytes(
                session, content, file.filename or "factura", InvoiceSource.UPLOAD
            )
    except UnsupportedDocumentError as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc

    if result.created:
        # Process right away instead of waiting for the next scheduler tick.
        background.add_task(container.processor.process_one, result.invoice_id)
        message = "Factura recibida; el agente la está procesando."
    else:
        message = "Este archivo ya había sido recibido; no se procesa dos veces."
    return UploadResponse(invoice_id=result.invoice_id, created=result.created, message=message)


@router.post("/{invoice_id}/review", status_code=status.HTTP_201_CREATED)
def review(invoice_id: uuid.UUID, body: ReviewRequest, session: SessionDep) -> dict[str, str]:
    try:
        decision = review_invoice(
            session, invoice_id, outcome=body.outcome, reviewer=body.reviewer, note=body.note
        )
    except ReviewError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return {"decision_id": str(decision.id), "outcome": body.outcome.value}


@router.post(
    "/{invoice_id}/reprocess",
    dependencies=[Depends(require_operator)],
    status_code=status.HTTP_202_ACCEPTED,
)
def reprocess(
    invoice_id: uuid.UUID, background: BackgroundTasks, container: ContainerDep
) -> dict[str, str]:
    background.add_task(container.processor.process_one, invoice_id)
    return {"status": "queued"}
