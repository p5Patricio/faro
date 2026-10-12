# Calendario 2026: obligaciones fiscales (persona física, México) y publicaciones macro

Fecha de consulta: **2026-10-03**. Los niveles de estado se definen en `cfdi-importadores.md`:
- **VERIFICADO**: el contenido aparece en un resultado de búsqueda de un dominio oficial. No se abrió la página completa, porque el proxy bloquea `WebFetch` hacia sat.gob.mx, banxico.org.mx, federalreserve.gov, inegi.org.mx y stats.gov.cn.
- **REPORTADO**: fuente de terceros.
- **INFERIDO**: aplicación de una regla verificada.
- **NO VERIFICADO**: sin fuente.

Versión legible por máquina: `config/tax/calendario-2026.yaml`.

---

## 1. Obligaciones fiscales de persona física

### 1.1 Declaración anual

| Qué | Fecha 2026 | Estado | Fuente |
|---|---|---|---|
| Declaración Anual **del ejercicio 2025** | **1 al 30 de abril de 2026** | VERIFICADO | https://www.gob.mx/sat/articulos/declaracion-anual-2025-de-personas ; https://www.gob.mx/sat/prensa/inicia-declaracion-anual-2025-de-personas-con-mas-facilidades-para-contribuyentes-24-2026?idiom=es |
| Pago en hasta 6 parcialidades | Hay que presentar la declaración y pagar la primera parcialidad en abril de 2026 | VERIFICADO | https://www.gob.mx/sat/prensa/llama-sat-a-presentar-la-declaracion-anual-2025-de-personas-21-2026?idiom=es |
| Saldo a favor de $10,001 o más | Debe enviarse con e.firma | VERIFICADO | ídem |
| Declaración Anual **del ejercicio 2026** | Abril de **2027** (fuera del año). La fecha exacta es **NO VERIFICADO**; normalmente es abril, pero espera el anuncio del SAT | INFERIDO | — |

Quién está obligado (resumen VERIFICADO, gob.mx):
- asalariados con ingresos anuales mayores a $400,000;
- quien tuvo dos o más patrones a la vez;
- quien tuvo ingresos distintos de salario, salarios del extranjero, indemnizaciones o pensiones por encima del límite;
- quien presta servicios profesionales, entre otros.

Aunque no esté obligado, un asalariado puede declarar para aplicar deducciones personales y pedir saldo a favor. Esto último es INFERIDO; es práctica común.

### 1.2 Pagos provisionales mensuales (día 17)

- **VERIFICADO**. Los pagos provisionales o definitivos mensuales (ISR, IVA e IEPS, propios o retenidos) se presentan **a más tardar el día 17 del mes inmediato posterior**. Aplica a personas físicas con actividad empresarial, servicios profesionales, arrendamiento y RESICO. **Un asalariado puro no los presenta.** Fuente: https://wwwmatnp.sat.gob.mx/declaracion/26984/declaracion-mensual-en-el-servicio-de-declaraciones-y-pagos
- **REPORTADO** (resumen del portal SAT): algunas personas tienen un plazo adicional según el **sexto dígito numérico del RFC**. No verifiqué los días exactos ni el instrumento que lo otorga (decreto o RMF vigente). **NO VERIFICADO** para 2026.
- **INFERIDO** (CFF art. 12, regla general de días inhábiles; no verifiqué hoy el texto vigente): si el 17 cae en sábado, domingo o día inhábil, el plazo se corre al siguiente día hábil.

| Periodo que se paga | Vence (día 17) | Día | Fecha efectiva (INFERIDO) |
|---|---|---|---|
| Dic 2025 | 2026-01-17 | sábado | 2026-01-19 |
| Ene 2026 | 2026-02-17 | martes | 2026-02-17 |
| Feb | 2026-03-17 | martes | 2026-03-17 |
| Mar | 2026-04-17 | viernes | 2026-04-17 |
| Abr | 2026-05-17 | domingo | 2026-05-18 |
| May | 2026-06-17 | miércoles | 2026-06-17 |
| Jun | 2026-07-17 | viernes | 2026-07-17 |
| Jul | 2026-08-17 | lunes | 2026-08-17 |
| Ago | 2026-09-17 | jueves | 2026-09-17 |
| **Sep** | **2026-10-17** | **sábado** | **2026-10-19** |
| Oct | 2026-11-17 | martes | 2026-11-17 |
| Nov | 2026-12-17 | jueves | 2026-12-17 |

No revisé el calendario de días inhábiles del SAT para 2026 (por ejemplo, las vacaciones de diciembre o Semana Santa). Antes de confiar en una fecha efectiva, compárala con la RMF 2026: https://dof.gob.mx/2025/SHCP/SHCP_281225_02.pdf (Anexo 1 RMF 2026, DOF 28-dic-2025, encontrado en la búsqueda pero no abierto).

### 1.3 Declaraciones informativas y constancias de instituciones financieras

| Qué | Fecha | Estado | Fuente |
|---|---|---|---|
| Las instituciones financieras, casas de bolsa y AFOREs presentan al SAT la **declaración informativa de intereses y enajenación de acciones** (también intereses hipotecarios) | **A más tardar el 15 de febrero** de cada año. En 2026 cayó en domingo, así que por regla general el plazo efectivo habría sido el 16-feb (INFERIDO) | VERIFICADO (regla) | https://www.sat.gob.mx/declaracion/14968/declaracion-de-informacion-de-intereses-y-enajenacion-de-acciones-del-sector-financiero |
| Entrega al cliente de la **constancia fiscal anual** (CFDI de retenciones: intereses, ganancia o pérdida por enajenación de acciones, dividendos) | En la práctica, febrero o marzo. **No encontré** la fecha legal límite de entrega al cliente | NO VERIFICADO | Complemento intereses (SAT): https://www.sat.gob.mx/consulta/65043/conoce-como-generar-la-factura-electronica-de-retenciones-e-informacion-de-pagos-por-retenciones |
| Nu México: constancia de ingresos y retenciones de la Cuenta Nu | Existe y se descarga desde la app. No verifiqué la fecha | REPORTADO (blog oficial de Nu) | https://blog.nu.com.mx/productos-nu/cuenta-nu/constancia-ingresos-y-retenciones-cuenta-nu/ |

**Sugerencia para Faro (INFERIDA)**: crear un recordatorio "revisar constancias de bancos y brokers" el **1 de marzo** como fecha de trabajo, no legal, y otro "declaración anual" el **1 de abril**. Las constancias de retenciones son CFDI con otro namespace (Retenciones), así que no las va a leer el parser de CFDI 4.0 de ingresos y egresos; harían falta un parser y un namespace adicionales. Los detalles del estándar de Retenciones son **NO VERIFICADO**.

---

## 2. Publicaciones macro (fuentes y fechas)

### 2.1 INEGI: INPC (inflación)

- **Fuente oficial**: el Calendario de Difusión 2026 de INEGI tiene dos PDF, primer y segundo semestre.
  - https://www.inegi.org.mx/contenidos/saladeprensa/doc/cal_2026.pdf
  - https://www.inegi.org.mx/contenidos/saladeprensa/boletines/2025/especiales/Cal_Dif-2026.pdf (comunicado 147/25, "segundo semestre 2026")
  - Calendario de Información de Interés Nacional (SNIEG): https://www.snieg.mx/calendario_iin_2026/

  Estado: VERIFICADO que existen. **No pude leer las fechas** porque el PDF está bloqueado.
- **Regla**: el INPC es quincenal; el dato mensual es el promedio de las dos quincenas. Se publica en el DOF a más tardar el **día 10** (mensual) y el **día 25** (1ª quincena del mismo mes), o el día hábil anterior. INEGI difunde a las 06:00. Estado: REPORTADO (resumen de búsqueda sobre boletines INEGI). Sirve como límite máximo, no como fecha exacta.
- **Fechas próximas**: REPORTADO, según los avisos de "próxima publicación" en los boletines INPC de INEGI vistos en el resumen de búsqueda. No se leyó el PDF.
  - **2026-10-08**: INPC mensual de septiembre 2026. Fuente: https://www.inegi.org.mx/contenidos/saladeprensa/boletines/2026/inpc/inpc_2q2026_09.pdf
  - **2026-10-22**: INPC de la 1ª quincena de octubre 2026. Fuente: https://www.inegi.org.mx/contenidos/saladeprensa/boletines/2026/inpc/inpc_1q2026_09.pdf
  - Noviembre y diciembre: **NO VERIFICADO**. Hay que tomarlas de `Cal_Dif-2026.pdf`.

### 2.2 Banxico: anuncios de política monetaria 2026 (13:00 hora local)

Hay 8 fechas al año. Banxico se reserva actuar en fechas extraordinarias.
- Página oficial: https://www.banxico.org.mx/publicaciones-y-prensa/anuncios-de-las-decisiones-de-politica-monetaria/anuncios-politica-monetaria-t.html
- Las minutas se publican aparte: https://www.banxico.org.mx/publicaciones-y-prensa/minutas-de-las-decisiones-de-politica-monetaria/minutas-politica-monetaria-ta.html

| Fecha | Estado | Evidencia |
|---|---|---|
| 2026-02-05 | VERIFICADO | Comunicado oficial "5 de febrero de 2026": https://www.banxico.org.mx/canales/%7BE2DEEE54-A582-4F29-42CF-21E75B152275%7D.pdf |
| 2026-03-26 | VERIFICADO | https://www.banxico.org.mx/publicaciones-y-prensa/anuncios-de-las-decisiones-de-politica-monetaria/%7B44EB2DF8-E71A-1553-7322-F60A34382EBA%7D.pdf |
| 2026-05-07 | VERIFICADO | https://www.banxico.org.mx/publicaciones-y-prensa/anuncios-de-las-decisiones-de-politica-monetaria/%7B8A05C722-0A97-4527-2166-0CE802CE6838%7D.pdf |
| 2026-06-25 | VERIFICADO | https://www.banxico.org.mx/publicaciones-y-prensa/anuncios-de-las-decisiones-de-politica-monetaria/%7BF6667DDE-E87D-68A3-0EBB-A4DF9048E403%7D.pdf |
| 2026-08-06 | VERIFICADO | https://www.banxico.org.mx/publicaciones-y-prensa/anuncios-de-las-decisiones-de-politica-monetaria/%7B8DA3F519-341F-480E-1D4E-1AEE71DD08DA%7D.pdf |
| 2026-09-24 | REPORTADO | Una búsqueda limitada a banxico.org.mx describió el comunicado del 24-sep-2026 (tasa en 6.50%), pero no identifiqué la URL exacta del PDF |
| 2026-11-05 | REPORTADO | BBVA Research, Agenda Económica 2026: https://www.bbvaresearch.com/wp-content/uploads/2026/03/AgendaEconomica_2026.pdf |
| 2026-12-17 | REPORTADO | ídem |

El calendario oficial 2026 en PDF existe (Banxico lo publica cada año; ver el de 2023 como patrón: https://www.banxico.org.mx/politica-monetaria/d/%7B3B4BDA5B-E7E8-E414-2066-DA0CB3F7C36F%7D.pdf), pero **no localicé su URL de 2026**. Las fechas de noviembre y diciembre deben confirmarse contra ese PDF.

### 2.3 FOMC (Reserva Federal), reuniones 2026

- Fuente: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
- Calendario tentativo anunciado el 9-ago-2024: https://www.federalreserve.gov/newsevents/pressreleases/monetary20240809a.htm
- Estado de las fechas: VERIFICADO (resumen de búsqueda limitada a federalreserve.gov).
- La decisión se anuncia el segundo día a las 14:00 ET. Esto es REPORTADO; la costumbre no se verificó hoy en la fuente oficial.
- Las reuniones con Resumen de Proyecciones Económicas (SEP) son REPORTADO (fedratecalc.com y otros), porque el resumen oficial no mostró los asteriscos.

| Reunión | Día de decisión | SEP |
|---|---|---|
| 27–28 ene | 2026-01-28 | no |
| 17–18 mar | 2026-03-18 | sí (REPORTADO) |
| 28–29 abr | 2026-04-29 | no |
| 16–17 jun | 2026-06-17 | sí (REPORTADO) |
| 28–29 jul | 2026-07-29 | no |
| 15–16 sep | 2026-09-16 | sí (REPORTADO) |
| **27–28 oct** | **2026-10-28** | no |
| **8–9 dic** | **2026-12-09** | sí (REPORTADO) |

Las minutas se publican 3 semanas después de la decisión (VERIFICADO, mismo resumen oficial).

### 2.4 China: CPI (NBS) y LPR

**CPI y PPI (NBS)**
- Calendario oficial: "Regular Press Release Calendar of NBS in 2026", https://www.stats.gov.cn/english/PressRelease/ReleaseCalendar/202512/t20251226_1962154.html
- VERIFICADO que existe y que la hora es 09:30 hora de Pekín. **No pude leer la tabla de fechas.**
- Patrón: alrededor del día 9 de cada mes, ajustado por fines de semana y feriados. Esto es REPORTADO (financecalendar.com).

| Dato | Fecha de publicación | Estado |
|---|---|---|
| CPI de septiembre 2026 | Octubre 2026. La fecha exacta no se encontró; la Semana Dorada (1–7 oct) suele retrasarla | NO VERIFICADO |
| CPI de octubre 2026 | 2026-11-09 | REPORTADO (https://www.financecalendar.com/?p=2105) |
| CPI de noviembre 2026 | 2026-12-09 | REPORTADO (ídem) |

**LPR (Loan Prime Rate)**
- Regla: la publica el National Interbank Funding Center, por autorización del PBoC, el **día 20 de cada mes, a las 09:00 hora de Pekín**. Se pospone si cae en feriado o fin de semana.
- Estado de la regla: REPORTADO. Fuentes: comunicado del Consejo de Estado de 2019, https://english.www.gov.cn/statecouncil/ministries/201908/17/content_WS5d5795bbc6d0c6695ff7ed8e.html ; https://www.fxempire.com/interest-rates/china
- Fuente primaria sugerida: el sitio del PBoC o de CFETS (chinamoney.com.cn). No se consultó.

| Mes | Fecha | Estado |
|---|---|---|
| Oct 2026 | 2026-10-20 (martes) | INFERIDO |
| Nov 2026 | 2026-11-20 (viernes) | INFERIDO |
| Dic 2026 | El 20 cae en domingo, así que probablemente sea 2026-12-21 | INFERIDO |

---

## 3. Lo que hay que confirmar a mano

Al abrir los PDFs oficiales en un navegador:
1. INEGI `Cal_Dif-2026.pdf`: las fechas del INPC de noviembre y diciembre.
2. El PDF del calendario de Banxico 2026: que las fechas 24-sep, 5-nov y 17-dic sean las correctas.
3. El calendario NBS 2026: la fecha del CPI de octubre (dato de septiembre).
4. Los días inhábiles del SAT en 2026: las fechas efectivas del día 17.
