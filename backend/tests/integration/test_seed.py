from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from opsagent.infra.db.models import Payment, PurchaseOrder, Vendor
from opsagent.infra.seed import load_catalog, seed_catalog

pytestmark = pytest.mark.integration

CATALOG = Path(__file__).resolve().parents[3] / "data" / "synthetic" / "catalog.json"


def test_seeding_is_idempotent(db_session: Session) -> None:
    catalog = load_catalog(CATALOG)

    first = seed_catalog(db_session, catalog)
    second = seed_catalog(db_session, catalog)

    assert first == {
        "vendors": len(catalog.vendors),
        "purchase_orders": len(catalog.purchase_orders),
        "payments": len(catalog.payments),
    }
    assert second == {"vendors": 0, "purchase_orders": 0, "payments": 0}
    assert db_session.scalar(select(func.count()).select_from(Vendor)) == len(catalog.vendors)
    assert db_session.scalar(select(func.count()).select_from(Payment)) == len(catalog.payments)
    po = db_session.scalars(select(PurchaseOrder).limit(1)).one()
    assert po.lines
    assert po.vendor.tax_id
