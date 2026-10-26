# Roadmap de Faro

Actualizado: 2026-10-26. Fuentes: `docs/audit/01-auditoria.md` (hallazgos), `docs/research/analisis-de-brechas.md` (funciones), `docs/sat/` (fiscal), `odd/tasks/faro-macro-finance-expansion.md` (plan previo, D1-D16).

Cada bloque es **un PR contra `main`** de unas 600 líneas como máximo (pruebas incluidas, nunca más pruebas que código). Valor y riesgo: A (alto), M (medio), B (bajo). Esfuerzo: S / M / L. 🧑 = requiere tu intervención.

## Estado al 2026-10-26

**Hecho y fusionado en `main`** (✅ en las tablas): B1 (#16), informes (#17), B2 (#18), B3 (#19), B4 (#20), B5 (#21, con interfaz en #28),
B10 primera parte (#22), B16 (#27 backend y #28 interfaz), B21 (#23), y de la verificación fiscal: #24 (checksum de migraciones sin CRLF), #25
(parámetros y calendario verificados) y #26 (catálogo CFDI oficial). Migraciones `0010`–`0018` aplicadas a la base real.

**Abierto**: #29 (corrección del `NaN` en `/api/predictions` y formato de títulos) y los PR de Dependabot #9–#11.

**Lo que sigue, en orden**: importadores de estados de cuenta de los dos bancos del usuario (B6) → valor de mercado y ganancia no
realizada en posiciones (B25) → importador repetible de estados de cuenta de GBM (B26) → fase D (B7, B8, B12, B13, B14, B24) → fase E (B10
segunda parte, B20) → fase F (B22, B23). Detalle y pendientes del usuario en `AGENTS.md`, secciones 9–11.

## Ahora (bloques de la fase 5)

| # | Bloque | Contenido | Valor | Esf. | Riesgo | Depende de | 🧑 Tu intervención |
|---|---|---|---|---|---|---|---|
| B1 ✅ | **Arreglos rápidos de auditoría** ([p5Patricio/faro#16](https://github.com/p5Patricio/faro/pull/16)) | Host permitido (DNS rebinding), `X-Forwarded-For`, cota en `/api/prices`, embargo en walk-forward, voseo, `lang`, AGENTS.md | A | S | B | — | Revisar y hacer merge; reiniciar la app siempre activa |
| B2 ✅ | **Libro de inversiones: backend** ([p5Patricio/faro#18](https://github.com/p5Patricio/faro/pull/18)) | Migración `0016` (cuentas y operaciones de inversión con tipo de cambio fechado), analítica pura de costo promedio por cuenta (compras, ventas, splits, reembolsos de capital, dividendos, distribuciones FIBRA, intereses), API `/api/investments/*` (cuentas, operaciones idempotentes, posiciones, papeles de trabajo CSV por año) | A | M | M (dinero) | — | 🧑 Aplicar `0016` con `py -3.14 -m db.migrate` |
| B3 ✅ | **Libro de inversiones: interfaz** ([p5Patricio/faro#19](https://github.com/p5Patricio/faro/pull/19)) | Pestaña "Inversiones": posiciones, formulario de operación, resumen de ganancias realizadas y dividendos en MXN, botón de exportar papeles de trabajo, aviso "informativo" | A | M | B | B2 | — |
| B4 ✅ | **Respaldo y exportación local** ([p5Patricio/faro#20](https://github.com/p5Patricio/faro/pull/20)) | `ops/backup_db.ps1` (`pg_dump -Fc` a carpeta elegida, retención N) + exportación JSON del libro personal e inversiones | A | S | B | — | 🧑 Elegir carpeta de respaldo; registrar la tarea |

## Siguiente

| # | Bloque | Contenido | Valor | Esf. | Riesgo | Depende de | 🧑 |
|---|---|---|---|---|---|---|---|
| B5 ✅ | Importador CFDI 4.0 de gastos ([#21](https://github.com/p5Patricio/faro/pull/21) backend, [#28](https://github.com/p5Patricio/faro/pull/28) interfaz en Finanzas → Facturas) | XML con biblioteca estándar, idempotente por UUID, clasificación por `UsoCFDI`/`FormaPago`, tabla `cfdi_documents` (migración) | A | M | M | — | 🧑 Descargar `catCFDI.xls` y unos XML reales; aplicar migración |
| B6 | Importador CSV bancario con perfiles | Perfiles YAML de mapeo de columnas, vista previa, huella por fila; primero Banorte y Mercado Pago | A | M | M | — | 🧑 Un CSV real de cada banco |
| B7 | Calendario | Cargar `config/tax/calendario-2026.yaml` (+ macro), panel en Macro con estado de verificación; dependencia `PyYAML` | M | S | B | — | 🧑 Confirmar fechas NO VERIFICADAS |
| B8 | Watchlist y alertas en el servidor | Reglas de precio y % de cambio con cooldown y dedupe sobre `ops/notification_rules.py`; reemplaza los pins locales | A | M | B | — | — |
| B9 | Checklist "listo para invertir" | Hechos, no veredictos: meses de fondo de emergencia, pasivos, meses consecutivos con excedente, perfil de riesgo definido | M | S | B | — | — |
| B10 ✅ parcial | Validez del modelo ([#22](https://github.com/p5Patricio/faro/pull/22): M-3 y M-7 hechos) | Pendiente: reentrenar con el embargo corregido, métricas de calibración (M-4); M-2 mitigado porque los jobs ya pasan el horizonte | A | S-M | B | B1 | — |
| B11 | Tipo de cambio fechado en el libro personal | Migración: `fx_rate_date`, `fx_source` en transacciones (F-1); FIRE sobre activos invertibles (F-2) | M | S | M | — | 🧑 Aplicar migración |
| B12 | Rendimiento TWR / XIRR y comparación contra referencias | S&P 500, IPC, CETES, inflación MX (series ya existen) | A | M | B | B2 | — |
| B13 | Distribuciones FIBRA asistidas | Captura de aviso de derechos (resultado fiscal vs reembolso), sin scraping de BMV | A | S | B | B2 | — |
| B14 | Cripto: posiciones y lotes | Cuentas de exchange como cuentas de inversión; importar/exportar CSV Koinly y CoinTracker; sin llaves en el repo | A | M | M | B2 | — |
| B25 | Valor de mercado y ganancia no realizada en posiciones | **Mezcla** acordada: (A) agregar al recolector de Yahoo los tickers cotizados del usuario (hoy ninguno está en `assets`) y `MXN=X` para USD→MXN; (B) precio manual con fecha y fuente para los fondos sin cotización pública (migración `0019`, API, formulario) | A | M | B | B2 | — |
| B26 | Importador repetible de estados de cuenta de GBM | Parser de `pdftotext -raw` de los PDF mensuales: operaciones, dividendos, ISR y rendimiento de reportos; reemplaza los scripts de captura que no se conservaron | A | M | M | B2 | 🧑 Estados de cuenta faltantes (Smart Cash 2023–2025, octubre en adelante) |
| B27 | Respaldos cifrados | `--encrypt` en `ops/backup_db.py` antes de que lleguen a la carpeta sincronizada con la nube | M | S | B | B4 | — |

## Después

| # | Bloque | Contenido | Valor | Esf. | 🧑 |
|---|---|---|---|---|---|
| B15 | Parámetros fiscales en la app | Loader de `config/tax/<año>.yaml`, mostrar UMA/topes con estado de verificación; tope de deducciones y AFORE voluntarias (informativo) | M | S | 🧑 Verificar valores en fuentes oficiales |
| B16 ✅ | CFDI de Retenciones (constancias de brokers) ([#27](https://github.com/p5Patricio/faro/pull/27), [#28](https://github.com/p5Patricio/faro/pull/28)) | Importar XML de la casa de bolsa y conciliar contra el libro de inversiones; interfaz en Inversiones → Constancias | A | M | 🧑 XML real |
| B17 | China macro | Inflación y LPR con `akshare` opcional (D7), estado "no configurado" sin él | M | M | 🧑 `pip install akshare` |
| B18 | Calculadora de plazos | CETES vs T-bill en MXN con riesgo cambiario, aviso D9 | M | M | — |
| B19 | Más mercados | Europa, Japón, India, Brasil, Hong Kong, China en Panorama y heatmap (HK/CN pendientes de D6) | M | M | — |
| B20 | Reintentos y huecos de datos | Reintento con backoff en yfinance (D-1), `change_pct` nulo con una sola barra (D-2), descarga incremental (D-3) | M | S | — |
| B21 ✅ | Operación | Tareas programadas con "ejecutar si se omitió" (O-1) | M | S | 🧑 Re-registrar tareas en Windows |
| B22 | Interfaz y accesibilidad (T0.6) | Axe en Playwright, contraste, foco, tabla responsive, edición de facturas y metas; ECharts por partes (P-1) | M | M | — |
| B23 | Deuda técnica | Separar `api/main.py` en routers y `ui/src/App.tsx` en paneles, sin cambiar comportamiento | M | L | — |
| B24 | X-ray de asignación y rebalanceo | Clase, sector, país, moneda; rebalanceo con PyPortfolioOpt | M | M | — |

## Decisiones que te corresponden

1. **Costo promedio por cuenta** (como lo calcula cada casa de bolsa) en lugar de global por emisora: se eligió para poder conciliar contra cada constancia. Cámbialo si tu contador prefiere otro criterio.
2. **Cripto**: método de costo (promedio, FIFO, identificación específica) y si aplica la exención de 3 UMA: decisión del contador; por ahora el libro usa promedio por cuenta y lo dice.
3. **INPC**: la actualización del costo (art. 129 / 17-A CFF) no se aplica hasta tener la serie verificada (Banxico SIE `SP1` con tu `BANXICO_TOKEN`).
4. **Tokens**: `BANXICO_TOKEN` (macro e INPC), `FINNHUB_API_KEY` (noticias), `SEC_USER_AGENT` (fundamentales); sin ellos todo funciona en estado "no configurado".
5. **Contador**: las 8 preguntas de `docs/sat/verificacion-2026-10.md` (cripto, dividendos del extranjero vía SIC, tope con dos UMA, etc.).
