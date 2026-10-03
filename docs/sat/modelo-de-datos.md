# Modelo de datos propuesto: libro de inversiones y papeles de trabajo

Diseño (fase 3) para que Faro guarde lo necesario para **conciliar contra las constancias de los intermediarios** y llegar al contador con los papeles listos. **Faro no calcula el impuesto definitivo ni presenta declaraciones.** Toda cifra derivada se etiqueta como "estimación informativa".

## Principios

1. **Dinero exacto.** Montos en centavos `bigint` en la moneda nativa de la operación; cantidades y precios unitarios en `numeric` (las acciones fraccionarias y la cripto necesitan decimales). En Python, `Decimal`; nunca `float`.
2. **Moneda base MXN con tipo de cambio explícito y fechado.** Cada operación en otra moneda guarda `fx_rate_to_mxn`, `fx_rate_date` y `fx_source` (`manual`, `banxico_fix`, `broker`). La regla del art. 20 CFF (FIX publicado en el DOF el día anterior) se documenta pero **no se aplica automáticamente**: el usuario o el importador dicen qué tipo usaron.
3. **Idempotencia.** `client_id uuid` único por operación (la UI lo genera; un importador lo deriva de forma determinista: UUID del CFDI, o hash de fila del CSV), así reimportar no duplica.
4. **Nada se sobrescribe en silencio.** Borrado lógico (`deleted_at`) y corrección = editar con el mismo `client_id`.
5. **Degradación.** Mientras la migración no esté aplicada, el API responde 503 con un mensaje claro ("falta aplicar la migración 0016"), igual que el libro personal.

## Tablas (migración `0016_investment_ledger.sql`)

### `investment_accounts`
| columna | tipo | nota |
|---|---|---|
| `id` | `uuid` PK | |
| `name` | `text` único | "GBM — trading", "Bitso", "Cetesdirecto" |
| `broker` | `text` | intermediario que emite la constancia |
| `currency` | `char(3)` | moneda de la cuenta (informativa; cada operación trae la suya) |
| `is_active` | `boolean` | |

### `investment_transactions`
| columna | tipo | nota |
|---|---|---|
| `id` | `uuid` PK | |
| `client_id` | `uuid` único | idempotencia |
| `account_id` | `uuid` FK | |
| `trade_date` | `date` | fecha de la operación (no de liquidación) |
| `kind` | `text` | `buy`, `sell`, `dividend`, `fibra_distribution` (resultado fiscal), `capital_return` (reembolso de capital), `interest`, `fee`, `split` |
| `symbol` | `text` | `FUNO11`, `AAPL`, `VOO`, `BTC`, `CETES28`… |
| `instrument_type` | `text` | `accion_mx`, `accion_sic`, `etf`, `fibra`, `fondo`, `deuda`, `cripto`, `otro` |
| `quantity` | `numeric(28,10)` | títulos (compra/venta), factor (split: 10 = 10 por 1) |
| `price` | `numeric(28,10)` | precio unitario en moneda nativa (compra/venta) |
| `amount_cents` | `bigint` | monto bruto en moneda nativa (para compra/venta = cantidad × precio, redondeado half-up) |
| `fee_cents` | `bigint` | comisión + IVA de la comisión |
| `tax_withheld_cents` | `bigint` | retención en moneda nativa (ISR MX o impuesto extranjero) |
| `currency` | `char(3)` | |
| `fx_rate_to_mxn` | `numeric(18,8)` | 1 para MXN |
| `fx_rate_date` | `date` | fecha del tipo de cambio usado |
| `fx_source` | `text` | `manual`, `banxico_fix`, `broker` |
| `source` | `text` | `manual`, `cfdi`, `csv` |
| `source_ref` | `text` | UUID del CFDI, nombre del archivo, etc. |
| `notes` | `text` | |
| `deleted_at` | `timestamptz` | borrado lógico |

Restricciones: `quantity > 0` en compra/venta/split; `amount_cents >= 0`; `fee_cents >= 0`; `tax_withheld_cents >= 0`; moneda distinta de MXN exige `fx_rate_to_mxn`.

## Analítica pura (`brain/investments/ledger.py`)

Por cada `(cuenta, símbolo)`, en orden de `trade_date` y luego de creación:

- **Compra**: `cantidad += q`; `costo_mxn += (monto + comisión) × fx`.
- **Venta**: `costo_promedio = costo_mxn / cantidad`; `costo_vendido = costo_promedio × q`; `ingreso_mxn = (monto − comisión) × fx`; `ganancia_mxn = ingreso_mxn − costo_vendido`; `cantidad -= q`; `costo_mxn -= costo_vendido`. Vender más de lo que se tiene se rechaza.
- **Split**: `cantidad × factor`, el costo total no cambia.
- **Reembolso de capital (FIBRA)**: reduce `costo_mxn` (sin bajar de 0; el excedente se reporta aparte), no cambia la cantidad.
- **Dividendo / distribución de resultado fiscal / interés**: ingreso del año, bruto y retención en MXN; no toca el costo.

Todo en centavos enteros MXN con redondeo half-up en cada conversión. **No** se aplica actualización por INPC (art. 129 y 17-A CFF): el reporte lo dice explícitamente y deja la columna "costo actualizado" para el contador o para una versión futura con la serie INPC verificada.

Costo promedio por cuenta (como lo calcula cada casa de bolsa), no global: así el resultado es conciliable contra la constancia de cada intermediario. Para cripto el mismo promedio por cuenta es una simplificación; el método aplicable no está definido por el SAT (ver `inversiones.md`, "lo ambiguo").

## Papeles de trabajo para el contador (exportes)

`GET /api/investments/worksheet?year=2026&format=csv|json`, una sección por concepto, todas con el aviso "Informativo; no es un cálculo de impuestos. Concilia contra tus constancias.":

1. **Ventas** (una fila por venta): fecha, cuenta/intermediario, símbolo, tipo, cantidad, ingreso MXN, costo promedio MXN, ganancia/pérdida MXN, tipo de cambio y su fecha.
2. **Dividendos y distribuciones**: fecha, intermediario, símbolo, concepto (dividendo, resultado fiscal FIBRA, reembolso de capital), bruto MXN, retención MXN, moneda original.
3. **Intereses**: fecha, intermediario, bruto MXN, retención MXN (el interés real lo informa la institución; Faro no lo recalcula).
4. **Resumen por intermediario y concepto**: totales del año para comparar renglón por renglón contra cada constancia.

PDF: fuera del primer bloque (el CSV se abre en cualquier hoja de cálculo y se imprime desde ahí).

## Importadores (bloques posteriores)

- **CFDI 4.0 de gastos** (XML, solo biblioteca estándar): idempotencia por UUID del timbre, clasificación por `UsoCFDI` (serie D = deducciones personales) y `FormaPago` (efectivo no deducible). Detalle en `cfdi-e-importadores.md`.
- **CFDI de Retenciones e información de pagos** (constancias de brokers): pendiente de obtener un XML real para fijar el mapeo de complementos (enajenación de acciones, dividendos, intereses, fideicomisos).
- **CSV bancarios**: ningún banco publica sus columnas; se propone un importador con **perfiles de mapeo** creados a partir de un archivo real del usuario (Banorte y Mercado Pago sí exportan CSV; BBVA personas, HSBC y Nu solo PDF/XML).
- **Cripto**: CSV universal de Koinly y CSV de CoinTracker como formatos de importación/exportación (formatos públicos, ver `docs/research/analisis-de-brechas.md`).

## Calendario de obligaciones

`config/tax/calendario-2026.yaml` (44 eventos con fuente y estado). Una vista de calendario puede leerlo tal cual y mostrar el estado de verificación de cada fecha.
