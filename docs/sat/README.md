# México y SAT: investigación y diseño (fase 3)

> **Informativo. No es asesoría fiscal ni de inversión.** Faro ayuda a llevar registros y a preparar papeles para tu contador; no calcula impuestos definitivos ni presenta declaraciones.

Fecha de consulta de todas las fuentes: 2026-10-03.

## Estado de verificación (léelo primero)

Desde el entorno donde se hizo la investigación, el proxy de red **bloqueó la lectura directa** de sat.gob.mx, dof.gob.mx, diputados.gob.mx, inegi.org.mx y banxico.org.mx; solo funcionó el buscador (extractos). Por eso:

- **Ningún parámetro fiscal está marcado como `verificado`** en `config/tax/<año>.yaml`: todos son `no_verificado` (con `confianza: alta|media`) o `ambiguo`.
- En el calendario, `VERIFICADO` significa "el texto aparece en un resultado de un dominio oficial", no "se leyó la página completa".
- Antes de que Faro use un valor en un reporte, alguien debe abrir el `source_url` oficial y cambiar `status` a `verificado`. Hasta entonces la interfaz debe mostrarlo como "no verificado".

## Documentos

| Archivo | Contenido |
|---|---|
| [`inversiones.md`](inversiones.md) | Regímenes de persona física, intereses, dividendos, acciones BMV/SIC (art. 129), ETFs, FIBRAs, fondos, cripto, ingresos del extranjero, tipo de cambio e INPC, deducciones personales, AFORE, **lo ambiguo** y qué pide el contador |
| [`cfdi-e-importadores.md`](cfdi-e-importadores.md) | CFDI 4.0 (estructura, usos D01–D10, pago electrónico, REP, descarga, constancia de situación fiscal) y formatos de exportación de BBVA, Banorte, Santander, HSBC, Nu y Mercado Pago, con diseño de importadores |
| [`calendario.md`](calendario.md) | Obligaciones fiscales 2026 y fuentes de calendarios macro (INEGI, Banxico, FOMC, China) |
| [`modelo-de-datos.md`](modelo-de-datos.md) | Libro de inversiones (lotes, costo promedio, dividendos, FIBRAs, intereses), exportes para el contador |
| `config/tax/2025.yaml`, `config/tax/2026.yaml` | Parámetros por año con enlace, fecha de consulta y estado |
| `config/tax/calendario-2026.yaml` | 44 eventos fiscales y macro con fuente y estado |

## Hallazgos principales

1. **Acciones BMV y SIC (art. 129 LISR):** 10 % definitivo sobre la ganancia neta anual, costo promedio por emisora actualizado; lo calcula cada casa de bolsa. Las pérdidas se aplican en el año y en los **10** ejercicios siguientes según las fuentes encontradas (el encargo decía 5; los 5 años corresponden a la pérdida inflacionaria de intereses, art. 134). Confirmar en el texto oficial.
2. **Intereses:** se grava el interés real; retención provisional sobre el capital de 0.50 % (2025) y 0.90 % (2026, **ambiguo**: varias fuentes citan la iniciativa de la LIF).
3. **FIBRAs:** el resultado fiscal distribuido lleva 30 % de retención; el reembolso de capital no tiene retención y reduce el costo fiscal del CBFI. Por eso el libro distingue ambos conceptos.
4. **Cripto:** sin régimen específico; la práctica la trata como enajenación de bienes con acumulación. Método de costo y exención de 3 UMA: **ambiguos**. Decisión del contador.
5. **Deducciones personales:** tope global de lo menor entre 5 UMA anuales y 15 % del ingreso; AFORE voluntarias con tope propio (10 % / 5 UMA). UMA 2026: 117.31 diaria (fuentes secundarias).
6. **Constancias:** cada intermediario emite CFDI de Retenciones e información de pagos (XML) con intereses nominales/reales, dividendos y ganancia/pérdida; es la mejor fuente importable.
7. **Bancos:** ningún banco publica las columnas de su exportación; Banorte y Mercado Pago exportan CSV; BBVA personas, HSBC y Nu solo PDF/XML. El importador debe usar perfiles de mapeo hechos con un archivo real.

## Pendiente a mano (necesita a una persona con navegador)

- LISR, CFF, LIF 2025 y LIF 2026 (diputados.gob.mx) y la página de la UMA de INEGI: confirmar los valores de `config/tax/*.yaml`.
- `catCFDI.xls` del SAT: generar los catálogos `c_UsoCFDI` y `c_FormaPago`.
- Un XML real de constancia de tu casa de bolsa y un CSV real de cada banco que uses.
- Calendarios 2026 de INEGI (`Cal_Dif-2026.pdf`), Banxico y NBS de China.
