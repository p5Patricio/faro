# Roadmap de Faro

Actualizado: 2026-10-03. Fuentes: `docs/audit/01-auditoria.md` (hallazgos), `docs/research/analisis-de-brechas.md` (funciones), `docs/sat/` (fiscal), `odd/tasks/faro-macro-finance-expansion.md` (plan previo, D1-D16).

Cada bloque es **un PR contra `main`** de unas 600 líneas como máximo (pruebas incluidas, nunca más pruebas que código). Valor y riesgo: A (alto), M (medio), B (bajo). Esfuerzo: S / M / L. 🧑 = requiere tu intervención.

## Estado al 2026-10-03

Abiertos para tu revisión: #16 (B1), #17 (informes), #18 (B2), #19 (B3, depende de #18), #20 (B4), #21 (B5 backend), #22 (B10). Migraciones nuevas: `0016` (#18) y `0017` (#21); son independientes entre sí.

## Ahora (bloques de la fase 5)

| # | Bloque | Contenido | Valor | Esf. | Riesgo | Depende de | 🧑 Tu intervención |
|---|---|---|---|---|---|---|---|
| B1 | **Arreglos rápidos de auditoría** ([p5Patricio/faro#16](https://github.com/p5Patricio/faro/pull/16)) | Host permitido (DNS rebinding), `X-Forwarded-For`, cota en `/api/prices`, embargo en walk-forward, voseo, `lang`, AGENTS.md | A | S | B | — | Revisar y hacer merge; reiniciar la app siempre activa |
| B2 | **Libro de inversiones: backend** ([p5Patricio/faro#18](https://github.com/p5Patricio/faro/pull/18)) | Migración `0016` (cuentas y operaciones de inversión con tipo de cambio fechado), analítica pura de costo promedio por cuenta (compras, ventas, splits, reembolsos de capital, dividendos, distribuciones FIBRA, intereses), API `/api/investments/*` (cuentas, operaciones idempotentes, posiciones, papeles de trabajo CSV por año) | A | M | M (dinero) | — | 🧑 Aplicar `0016` con `py -3.14 -m db.migrate` |
| B3 | **Libro de inversiones: interfaz** ([p5Patricio/faro#19](https://github.com/p5Patricio/faro/pull/19)) | Pestaña "Inversiones": posiciones, formulario de operación, resumen de ganancias realizadas y dividendos en MXN, botón de exportar papeles de trabajo, aviso "informativo" | A | M | B | B2 | — |
| B4 | **Respaldo y exportación local** ([p5Patricio/faro#20](https://github.com/p5Patricio/faro/pull/20)) | `ops/backup_db.ps1` (`pg_dump -Fc` a carpeta elegida, retención N) + exportación JSON del libro personal e inversiones | A | S | B | — | 🧑 Elegir carpeta de respaldo; registrar la tarea |

## Siguiente

| # | Bloque | Contenido | Valor | Esf. | Riesgo | Depende de | 🧑 |
|---|---|---|---|---|---|---|---|
| B5 | Importador CFDI 4.0 de gastos ([p5Patricio/faro#21](https://github.com/p5Patricio/faro/pull/21), solo backend; la interfaz queda pendiente) | XML con biblioteca estándar, idempotente por UUID, clasificación por `UsoCFDI`/`FormaPago`, tabla `cfdi_documents` (migración) | A | M | M | — | 🧑 Descargar `catCFDI.xls` y unos XML reales; aplicar migración |
| B6 | Importador CSV bancario con perfiles | Perfiles YAML de mapeo de columnas, vista previa, huella por fila; primero Banorte y Mercado Pago | A | M | M | — | 🧑 Un CSV real de cada banco |
| B7 | Calendario | Cargar `config/tax/calendario-2026.yaml` (+ macro), panel en Macro con estado de verificación; dependencia `PyYAML` | M | S | B | — | 🧑 Confirmar fechas NO VERIFICADAS |
| B8 | Watchlist y alertas en el servidor | Reglas de precio y % de cambio con cooldown y dedupe sobre `ops/notification_rules.py`; reemplaza los pins locales | A | M | B | — | — |
| B9 | Checklist "listo para invertir" | Hechos, no veredictos: meses de fondo de emergencia, pasivos, meses consecutivos con excedente, perfil de riesgo definido | M | S | B | — | — |
| B10 | Validez del modelo (2.ª parte) ([p5Patricio/faro#22](https://github.com/p5Patricio/faro/pull/22): M-3 y M-7) | Pendiente: métricas de calibración (M-4); M-2 mitigado porque los jobs ya pasan el horizonte | A | S-M | B | B1 | — |
| B11 | Tipo de cambio fechado en el libro personal | Migración: `fx_rate_date`, `fx_source` en transacciones (F-1); FIRE sobre activos invertibles (F-2) | M | S | M | — | 🧑 Aplicar migración |
| B12 | Rendimiento TWR / XIRR y comparación contra referencias | S&P 500, IPC, CETES, inflación MX (series ya existen) | A | M | B | B2 | — |
| B13 | Distribuciones FIBRA asistidas | Captura de aviso de derechos (resultado fiscal vs reembolso), sin scraping de BMV | A | S | B | B2 | — |
| B14 | Cripto: posiciones y lotes | Cuentas de exchange como cuentas de inversión; importar/exportar CSV Koinly y CoinTracker; sin llaves en el repo | A | M | M | B2 | — |

## Después

| # | Bloque | Contenido | Valor | Esf. | 🧑 |
|---|---|---|---|---|---|
| B15 | Parámetros fiscales en la app | Loader de `config/tax/<año>.yaml`, mostrar UMA/topes con estado de verificación; tope de deducciones y AFORE voluntarias (informativo) | M | S | 🧑 Verificar valores en fuentes oficiales |
| B16 | CFDI de Retenciones (constancias de brokers) | Importar XML de la casa de bolsa y conciliar contra el libro de inversiones | A | M | 🧑 XML real |
| B17 | China macro | Inflación y LPR con `akshare` opcional (D7), estado "no configurado" sin él | M | M | 🧑 `pip install akshare` |
| B18 | Calculadora de plazos | CETES vs T-bill en MXN con riesgo cambiario, aviso D9 | M | M | — |
| B19 | Más mercados | Europa, Japón, India, Brasil, Hong Kong, China en Panorama y heatmap (HK/CN pendientes de D6) | M | M | — |
| B20 | Reintentos y huecos de datos | Reintento con backoff en yfinance (D-1), `change_pct` nulo con una sola barra (D-2), descarga incremental (D-3) | M | S | — |
| B21 | Operación | Tareas programadas con "ejecutar si se omitió" (O-1) | M | S | 🧑 Re-registrar tareas en Windows |
| B22 | Interfaz y accesibilidad (T0.6) | Axe en Playwright, contraste, foco, tabla responsive, edición de facturas y metas; ECharts por partes (P-1) | M | M | — |
| B23 | Deuda técnica | Separar `api/main.py` en routers y `ui/src/App.tsx` en paneles, sin cambiar comportamiento | M | L | — |
| B24 | X-ray de asignación y rebalanceo | Clase, sector, país, moneda; rebalanceo con PyPortfolioOpt | M | M | — |

## Decisiones que te corresponden

1. **Costo promedio por cuenta** (como lo calcula cada casa de bolsa) en lugar de global por emisora: se eligió para poder conciliar contra cada constancia. Cámbialo si tu contador prefiere otro criterio.
2. **Cripto**: método de costo (promedio, FIFO, identificación específica) y si aplica la exención de 3 UMA: decisión del contador; por ahora el libro usa promedio por cuenta y lo dice.
3. **INPC**: la actualización del costo (art. 129 / 17-A CFF) no se aplica hasta tener la serie verificada (Banxico SIE `SP1` con tu `BANXICO_TOKEN`).
4. **Tokens**: `BANXICO_TOKEN` (macro e INPC), `FINNHUB_API_KEY` (noticias); sin ellos todo funciona en estado "no configurado".
