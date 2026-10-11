# Servidor MCP

El agente expone sus capacidades como herramientas MCP. Cualquier cliente MCP
(Claude Code, Claude Desktop, otros agentes) puede consultar facturas, investigar
hallazgos, correr el agente y registrar revisiones humanas, **reutilizando los mismos
servicios que la API REST y el scheduler**: no hay una segunda implementación de
ninguna regla de negocio.

## Conectarlo a Claude Code

Con el stack levantado (`docker compose up`), desde la raíz del repo:

```bash
# Opción 1: el repo ya trae .mcp.json (scope de proyecto); Claude Code pide aprobarlo al abrirlo.
claude

# Opción 2: registrarlo a mano
claude mcp add invoice-ops \
  --env DATABASE_URL=postgresql+psycopg://opsagent:opsagent@localhost:5433/opsagent \
  -- uv run --directory backend python -m opsagent.mcp_server
```

Para clientes remotos también puede servirse por HTTP (streamable HTTP):

```bash
uv run --directory backend python -m opsagent.mcp_server --http --port 8765   # http://localhost:8765/mcp
```

## Herramientas

| Herramienta | Tipo | Para qué |
|---|---|---|
| `list_invoices` | lectura | Lista facturas; `needs_review=true` devuelve la cola de revisión |
| `get_invoice` | lectura | Extracción, hallazgos, decisiones y auditoría de una factura |
| `get_stats` | lectura | Volúmenes, tasa de aprobación automática, costo y latencia |
| `get_daily_report` | lectura | Reporte diario en Markdown |
| `search_vendors` | lectura | Proveedores por nombre aproximado o RUC parcial |
| `list_open_purchase_orders` | lectura | Órdenes abiertas de un proveedor |
| `get_purchase_order` | lectura | Orden de compra con sus líneas |
| `find_payments` | lectura | Pagos a un proveedor, por factura o monto |
| `ingest_invoice` | escritura (idempotente) | Registra un archivo de factura |
| `process_invoice` | escritura | Corre el agente sobre una factura |
| `process_pending` | escritura | Corre el agente sobre todo lo pendiente |
| `review_invoice` | escritura | Registra la decisión **humana** sobre una factura marcada |
| `generate_daily_report` | escritura | Genera o actualiza el reporte de un día |

Las de lectura llevan `readOnlyHint=true`, así el cliente puede autorizarlas sin
preguntar. Las de escritura no, y el cliente pide confirmación al usuario. Además,
`review_invoice` registra el actor como `human:<nombre> (via MCP)`: la decisión
queda atribuida a la persona que la tomó, no al modelo.

También expone el recurso `invoice-ops://policy` (umbrales de la política) y el
prompt `triage_review_queue`.

## Ejemplo de sesión

> **Tú:** /mcp__invoice-ops__triage_review_queue
>
> **Claude:** *(llama a `list_invoices` con `needs_review=true`, luego a `get_invoice` y
> `get_purchase_order` para cada una)*. Hay 23 facturas en revisión. INV-031 de
> Ferretería Zamora cobra 2 sacos de cemento más que la OC-2026-0133 (+19,44 USD);
> recomiendo pedir nota de crédito al proveedor…
>
> **Tú:** Rechaza INV-031 con esa nota.
>
> **Claude:** *(pide permiso y llama a `review_invoice`)*. Listo: quedó registrada
> como rechazada por ti.
