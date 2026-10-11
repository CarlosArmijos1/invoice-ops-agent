"""Markdown rendering of eval results (for evals/results/*.md and the README)."""

import re
from pathlib import Path
from typing import Any

FIELD_LABEL = {
    "vendor_name": "Proveedor",
    "vendor_tax_id": "RUC",
    "invoice_number": "N.º factura",
    "issue_date": "Fecha",
    "po_number": "Orden de compra",
    "subtotal": "Subtotal",
    "tax": "IVA",
    "total": "Total",
    "line_items": "Líneas",
}
RENDER_LABEL = {
    "pdf_text": "PDF digital",
    "pdf_scan": "PDF escaneado",
    "jpg": "Foto JPG",
    "png": "Imagen PNG",
}
ACTION_LABEL = {
    "auto_approve": "aprobar",
    "human_review": "revisión",
    "request_info": "pedir info",
}
START, END = "<!-- EVALS:START -->", "<!-- EVALS:END -->"


def _p(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f} %"


def _ms(value: int | None) -> str:
    return "—" if value is None else f"{value / 1000:.1f} s"


def render_markdown(report: dict[str, Any]) -> str:
    test, full = report["test"], report["all"]
    ext, dec, cost = test["extraction"], test["decisions"], full["cost"]
    lines = [
        f"Modo `{report['mode']}` · texto `{report['models']['text']}` · visión "
        f"`{report['models']['vision']}` · {full['invoices']} facturas "
        f"({test['invoices']} en el split de test, que es el que se reporta).",
        "",
        "| Métrica (split test) | Resultado |",
        "|---|---|",
        f"| Facturas con datos extraídos | {_p(ext['success_rate'])} |",
        f"| Campos críticos correctos (RUC, número, OC, total) | {_p(ext['critical_fields_ok'])} |",
        f"| Decisión correcta | {_p(dec['accuracy'])} |",
        f"| Precisión de la aprobación automática | {_p(dec['auto_approve_precision'])} |",
        f"| Aprobaciones automáticas incorrectas | **{len(dec['false_approvals'])}** |",
        f"| Recall de hallazgos esperados | {_p(dec['findings_recall'])} |",
        f"| Costo por factura (precio de lista) | ${cost['per_invoice_usd']} |",
        f"| Latencia LLM por factura p50 / p95 | {_ms(cost['latency_p50_ms'])} / "
        f"{_ms(cost['latency_p95_ms'])} |",
        "",
        "**Precisión por campo**",
        "",
        "| " + " | ".join(FIELD_LABEL.values()) + " |",
        "|" + "---|" * len(FIELD_LABEL),
        "| " + " | ".join(_p(ext["field_accuracy"][f]) for f in FIELD_LABEL) + " |",
        "",
        "**Por tipo de documento** (todas las facturas)",
        "",
        "| Tipo | Facturas | Campos críticos OK | Decisión correcta |",
        "|---|---|---|---|",
    ]
    for render, row in full["extraction"]["by_render"].items():
        lines.append(
            f"| {RENDER_LABEL.get(render, render)} | {row['n']} | "
            f"{_p(row['critical_fields_ok'])} | {_p(row['decision_accuracy'])} |"
        )
    lines += [
        "",
        "**Matriz de confusión de decisiones** (filas: esperado, columnas: agente; split test)",
        "",
        "| | " + " | ".join(ACTION_LABEL.values()) + " |",
        "|---|---|---|---|",
    ]
    for expected, row in dec["confusion"].items():
        lines.append(
            f"| {ACTION_LABEL[expected]} | " + " | ".join(str(row[a]) for a in ACTION_LABEL) + " |"
        )
    return "\n".join(lines) + "\n"


def update_readme(readme: Path, markdown: str) -> None:
    text = readme.read_text(encoding="utf-8")
    block = f"{START}\n{markdown}{END}"
    if START in text:
        text = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _: block, text, flags=re.S)
    else:
        text += f"\n{block}\n"
    readme.write_text(text, encoding="utf-8")
