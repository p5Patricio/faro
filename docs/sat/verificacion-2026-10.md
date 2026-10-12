# Verificación fiscal contra fuentes oficiales (fase B)

> **Informativo. No es asesoría fiscal ni de inversión.** Faro lleva registros y prepara papeles para tu contador; no calcula impuestos definitivos.

Fecha de lectura de todas las fuentes: **2026-10-12**. A diferencia de la fase 3 (solo extractos de buscador), aquí se leyó el texto oficial completo.

## Fuentes leídas

| Fuente | URL | Versión |
|---|---|---|
| LISR | https://www.diputados.gob.mx/LeyesBiblio/pdf/LISR.pdf | Última reforma DOF 01-04-2024 (sin reformas en 2025 ni 2026) |
| CFF | https://www.diputados.gob.mx/LeyesBiblio/pdf/CFF.pdf | Última reforma DOF 09-04-2026 |
| LIF 2026 | https://www.diputados.gob.mx/LeyesBiblio/pdf/LIF_2026.pdf | DOF 07-11-2025 |
| LIF 2025 | https://www.diputados.gob.mx/LeyesBiblio/abro/lif_2025/Ley_de_Ingresos_2025-Abro.pdf | Abrogada a partir del 01-01-2026 |
| Ley de la UMA | https://www.diputados.gob.mx/LeyesBiblio/pdf/LDVUMA_301216.pdf | DOF 30-12-2016, sin reformas |
| UMA (INEGI) | https://www.inegi.org.mx/temas/uma/ | Tabla de valores 2016-2026 |
| INPC (INEGI) | https://www.inegi.org.mx/temas/inpc/ | Última y próxima actualización |
| Banxico | Listado de anuncios de política monetaria y calendario 2026 (PDF) | — |
| Fed | https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm | Calendario 2026 |
| NBS China | https://www.stats.gov.cn/english/PressRelease/ReleaseCalendar/202512/t20251226_1962154.html | Calendario 2026 |

## Resultado

| Archivo | Antes | Ahora |
|---|---|---|
| `config/tax/2025.yaml` (24 parámetros) | 0 verificados | 21 verificados, 2 ambiguos, 1 no verificado |
| `config/tax/2026.yaml` (24 parámetros) | 0 verificados | 19 verificados, 3 ambiguos, 2 no verificados |
| `config/tax/calendario-2026.yaml` (44 eventos) | 26 "verificados" por extracto | 35 verificados con la fuente completa, 1 reportado, 3 inferidos, 5 sin fecha |

Cada parámetro verificado trae `evidence` (artículo y frase textual) y `verified_on`.

### Los puntos que ya sabías ambiguos

| Punto | Resultado | Fundamento |
|---|---|---|
| Retención de intereses 2026 | **0.90 %**, verificado | LIF 2026 **art. 24** (las fuentes secundarias decían 21 o 24) |
| Pérdidas en bolsa: ¿10 o 5 años? | **10 ejercicios**, verificado | LISR art. 129: "en el ejercicio o en los diez siguientes", sólo contra ganancias del mismo artículo |
| Exención de 3 UMA para cripto | **Sigue ambiguo** | LISR art. 93 fr. XIX b) excluye "las inversiones del contribuyente"; además el texto dice salario mínimo, no UMA |
| Acreditamiento de la retención de FIBRAs | **Sí es acreditable**, verificado | LISR art. 188 fr. V: acumulas "sin deducir el impuesto retenido" y "podrán acreditar el impuesto que se les retenga" |

### Correcciones a lo que decía la fase 3

1. **Factor de actualización (CFF art. 17-A):** es el INPC *del mes anterior al más reciente* entre el INPC *del mes anterior al más antiguo*, mínimo 1. El YAML 2026 decía "INPC reciente / INPC antiguo" (desfase de un mes).
2. **Tipo de cambio (CFF art. 20):** primero el tipo **al que adquiriste la divisa**; sólo sin adquisición, el que Banxico publique en el DOF el día anterior.
3. **Tope global de deducciones (LISR art. 151):** el artículo sólo excluye la **fracción V** (aportaciones para el retiro). Las otras exclusiones que citaban fuentes secundarias no están en este artículo.
4. **Plazos en viernes (CFF art. 12):** el pago de contribuciones ante bancos se recorre al siguiente día hábil cuando el último día es **viernes**, no sólo cuando es inhábil. En 2026 afecta al 17 de abril y al 17 de julio.
5. **LPR de China:** el aviso oficial de 2019 dice 9:30, no 9:00.
6. **IPC de China de septiembre:** sale el **14 de octubre** (estaba sin fecha).

### Hallazgos nuevos

- **Dividendos de sociedades extranjeras (LISR art. 142 fr. V):** además de acumularlos, pagas un 10 % **definitivo** sobre el dividendo efectivamente distribuido (sin incluir la retención extranjera), **a más tardar el día 17 del mes siguiente** al cobro. Es una obligación mensual, no sólo de la anual.
- **Costo por intermediario (LISR art. 129):** la ganancia se determina "por cada sociedad emisora" y por operaciones "a través de cada uno de los intermediarios". Respalda que el libro de inversiones lleve el costo promedio por cuenta.
- **Pérdida no aplicada (LISR art. 129):** si no la disminuyes en un ejercicio pudiendo hacerlo, pierdes ese derecho hasta por ese monto.
- **Saldo a favor de $10,001 o más:** el SAT pide e.firma para la anual (gob.mx, 06-04-2026).

## Para tu contador

1. **Cripto y la exención del art. 93 fr. XIX b):** ¿la cripto es "inversión del contribuyente" (excluida) o un bien mueble exento hasta 3 salarios mínimos anuales de ganancia? ¿Y se mide en salario mínimo (como dice el texto) o en UMA?
2. **Método de costo para cripto:** promedio, FIFO o identificación específica. La ley no lo fija para este caso.
3. **Dividendos del extranjero vía SIC:** ¿el intermediario retiene el 10 % del art. 142 fr. V o lo entero yo el día 17? ¿Cómo acredito el impuesto retenido en el extranjero?
4. **Tope de deducciones con dos UMA en el año:** en enero todavía rige la UMA del año anterior (LDVUMA art. 5). ¿Qué UMA anual se usa para el tope?
5. **Exclusiones del tope global:** el art. 151 sólo excluye la fracción V. ¿De dónde vienen las exclusiones de colegiaturas, donativos y gastos por discapacidad que citan las guías?
6. **Viernes 30 de abril de 2027:** el CFF art. 12 recorre el *pago ante bancos* al lunes 3 de mayo. ¿Aplica también a la presentación de la anual?
7. **Tope de aportaciones voluntarias:** la ley dice "cinco salarios mínimos ... elevados al año"; la conversión a UMA viene del decreto de 2016. ¿Se usan 5 UMA anuales?
8. **Costo promedio por cuenta:** el art. 129 calcula por emisora y por intermediario. ¿Te sirve el criterio por cuenta de Faro o prefieres otro?

## Lo que sigue sin verificar

| Dato | Por qué |
|---|---|
| Fecha DOF de la RMF 2026 (28-12-2025) | dof.gob.mx rechazó la conexión desde el navegador; sólo la respalda el nombre de un archivo en sat.gob.mx |
| INPC de octubre a diciembre (sin fecha) | El PDF `Cal_Dif-2026.pdf` resultó ser un comunicado sin esas fechas; la página del INPC sólo muestra la próxima publicación |
| Hora actual de la LPR y regla de días inhábiles | Sólo está el aviso de 2019 |
| Informativa de intereses del 15 de febrero | No se volvió a revisar (queda como reportado) |
| `catCFDI_V_4_20261001.xls` | Descargado del Anexo 20 (versión del 1 de octubre de 2026); falta leerlo para generar `c_UsoCFDI` y `c_FormaPago` |
