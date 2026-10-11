Modo `oracle` · texto `openai/gpt-oss-120b` · visión `qwen/qwen3.8-27b` · 60 facturas (40 en el split de test, que es el que se reporta).

| Métrica (split test) | Resultado |
|---|---|
| Facturas con datos extraídos | 100.0 % |
| Campos críticos correctos (RUC, número, OC, total) | 100.0 % |
| Decisión correcta | 100.0 % |
| Precisión de la aprobación automática | 100.0 % |
| Aprobaciones automáticas incorrectas | **0** |
| Recall de hallazgos esperados | 100.0 % |
| Costo por factura (precio de lista) | $0.000000 |
| Latencia LLM por factura p50 / p95 | — / — |

**Precisión por campo**

| Proveedor | RUC | N.º factura | Fecha | Orden de compra | Subtotal | IVA | Total | Líneas |
|---|---|---|---|---|---|---|---|---|
| 100.0 % | 100.0 % | 100.0 % | 100.0 % | 100.0 % | 100.0 % | 100.0 % | 100.0 % | 100.0 % |

**Por tipo de documento** (todas las facturas)

| Tipo | Facturas | Campos críticos OK | Decisión correcta |
|---|---|---|---|
| Foto JPG | 19 | 100.0 % | 100.0 % |
| PDF escaneado | 12 | 100.0 % | 100.0 % |
| PDF digital | 25 | 100.0 % | 100.0 % |
| Imagen PNG | 4 | 100.0 % | 100.0 % |

**Matriz de confusión de decisiones** (filas: esperado, columnas: agente; split test)

| | aprobar | revisión | pedir info |
|---|---|---|---|
| aprobar | 19 | 0 | 0 |
| revisión | 0 | 16 | 0 |
| pedir info | 0 | 0 | 5 |
