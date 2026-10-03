# Fiscalidad de inversiones, persona física en México (ejercicios 2025 y 2026)

> **Esto es información, no asesoría fiscal.** El objetivo de Faro es llevar registros y preparar papeles para el contador. Faro no debe calcular el impuesto definitivo.
> Fecha de consulta de todas las fuentes: **2026-10-03**.

## Advertencia sobre cómo se verificó

Durante la investigación, el proxy de red **bloqueó la descarga directa** de todos los sitios oficiales (sat.gob.mx, dof.gob.mx, diputados.gob.mx, inegi.org.mx, cefp.gob.mx) y también de varios sitios secundarios (mley.mx, ey.com). Solo funcionó el **buscador**, que devuelve fragmentos de las páginas.

Por eso, **ningún dato está marcado como VERIFICADO** en el sentido estricto de "leí el texto oficial". Las etiquetas significan:

- **[NO VERIFICADO, confianza alta]**: varias fuentes secundarias independientes coinciden, o el fragmento venía de un dominio oficial (por ejemplo, el nombre de un archivo en sat.gob.mx).
- **[NO VERIFICADO, confianza media]**: hay una sola fuente o el fragmento es parcial.
- **[AMBIGUO]**: las fuentes no coinciden, o el dato depende de cómo se interprete la ley.
- **[INFERIDO]**: es una deducción mía a partir de las reglas, no algo que diga la fuente.

**Siguiente paso obligatorio:** abrir a mano la LISR oficial (https://www.diputados.gob.mx/LeyesBiblio/pdf/LISR.pdf), el CFF, la LIF 2025, la LIF 2026 y la página de la UMA de INEGI. Después, cambiar `status` a `verificado` en `config/tax/<año>.yaml`.

---

## 1. Panorama de regímenes de persona física

**Capítulos de la LISR (Título IV).** Los capítulos son: sueldos y salarios (Cap. I, art. 94 y ss.); actividades empresariales y profesionales (Cap. II, Sección I); RESICO (Cap. II, Sección IV, art. 113-E); arrendamiento (Cap. III); enajenación de bienes (Cap. IV, arts. 119-128); intereses (Cap. VI, arts. 133-136); dividendos (Cap. VIII, art. 140); y "demás ingresos", que incluye los dividendos de sociedades extranjeras (Cap. IX, art. 142). La enajenación de acciones en bolsa está en el art. 129 (Cap. IV). [NO VERIFICADO, confianza alta: estructura conocida de la LISR, sin lectura del texto oficial]

**RESICO (art. 113-E).**
- Tope de ingresos: **$3,500,000 al año**.
- Tasas: de 1.00% a 2.50% mensual sobre los ingresos cobrados, sin deducciones.
- Solo cubre actividad empresarial, profesional y arrendamiento. **No cubre ingresos por inversiones.**
- La RMF 2026 exige e.firma y buzón tributario a más tardar el 1-ene-2027.
- Fuentes: https://sdv.com.mx/compendio/ley-isr/articulo-113-e/ (secundaria); https://sdv.com.mx/compendio/resolucion-miscelanea-2026/regla-3-13-1/ (secundaria). [NO VERIFICADO, confianza alta]

**Declaración anual (art. 150 LISR).**
- Se presenta en el **mes de abril** del año siguiente.
- Ejercicio 2024: del 1 al 30 de abril de 2025.
- Ejercicio 2025: del **1 al 30 de abril de 2026**.
- Fuentes: https://expansion.mx/finanzas-personales/2026/04/06/declaracion-anual-sat-fecha-para-presentar-sin-multas ; https://www.rankia.mx/noticias/fiscalidad/7251159-declaracion-anual-2026-sat-confirma-fechas-requisitos-para-personas-fisicas (secundarias). [NO VERIFICADO, confianza alta]
- Ejercicio 2026: se espera del 1 al 30 de abril de 2027. [INFERIDO]

**Cuándo no es obligatorio declarar.**
- Aplica cuando solo hay salarios e intereses, el total **no rebasa $400,000**, los intereses **reales no rebasan $100,000** y hubo retención (arts. 98, 135 y 150).
- Hay obligación de declarar si se trabajó con dos o más patrones al mismo tiempo, o si hay cualquier otro tipo de ingreso: ganancias en bolsa, dividendos, ingresos del extranjero, cripto, etc. [INFERIDO a partir de la lógica del art. 150]
- Fuente: fragmento de https://wwwmat.sat.gob.mx/articulo/83662/articulo-150 (dominio del SAT, visto solo en el buscador). [NO VERIFICADO, confianza alta]

**Pagos provisionales.**
- Los asalariados no los hacen: el patrón retiene.
- Actividad empresarial, profesional, arrendamiento y RESICO: pagos mensuales.
- Inversiones: el impuesto se cubre por **retención** (intermediario, banco, FIBRA o distribuidora de fondos). La excepción son los dividendos extranjeros sin retención: la persona paga el 10% a más tardar el día 17 del mes siguiente (art. 142 fr. V).
- Fuente: https://idconline.mx/fiscal-contable/2023/04/12/declarar-dividendos-del-extranjero-en-anual-basico-para-personas-fisicas (secundaria). [NO VERIFICADO, confianza media]

---

## 2. Inversiones

### 2.1 Intereses: CETES, bonos, pagarés, cuentas (arts. 133-136 LISR)

- **Se grava el interés real**: los intereses nominales menos el ajuste por inflación (art. 134).
  - Ajuste = saldo promedio diario × (INPC del mes más reciente / INPC del primer mes − 1).
  - La institución financiera hace el cálculo y entrega una **constancia (CFDI de retenciones e información de pagos)** con interés nominal, interés real, pérdida y retención.
  - Fuentes: https://sdv.com.mx/compendio/ley-isr/articulo-134/ ; https://www.contadigital.mx/posts/isr-sobre-intereses-personas-fisicas (secundarias). [NO VERIFICADO, confianza alta]
- **Pérdida por inflación** (cuando la inflación supera el interés): se puede restar de otros ingresos del ejercicio o de los **5 ejercicios siguientes**, actualizada. Fuente secundaria: idconline. [NO VERIFICADO, confianza media]
- **Retención provisional**: se aplica sobre el **capital**, no sobre el interés (arts. 54 y 135 LISR, con la tasa que fija la LIF).
  - **2025: 0.50% anual** (art. 21 LIF 2025). Fuentes: https://idconline.mx/fiscal-contable/2024/12/20/cinco-puntos-que-se-deben-conocer-de-la-lif-2025 ; https://www.elcontribuyente.mx/2024/11/inflacion-vs-isr-lo-que-debes-saber-sobre-la-retencion-de-intereses-en-2025/ [NO VERIFICADO, confianza alta]
  - **2026: 0.90% anual** (LIF 2026, publicada en el DOF el 7-nov-2025). Fuentes: https://www.galicia.com.mx/links/files/Actualizaciones/GC.-Actualizacion.-Fiscal.-Paquete-economico-2026-1163366.1.pdf ; https://www.elimparcial.com/dinero/2025/09/11/ahorradores-pagaran-mas-impuestos-en-2026-con-esta-iniciativa-para-la-ley-de-ingresos/ **[AMBIGUO]**: las fuentes no coinciden en el número de artículo (21 o 24), y varias citan la *iniciativa*, no el texto aprobado.
- En la anual, el interés real se **acumula** y la retención se acredita. Si se cumplen los umbrales de la sección 1, la retención puede quedar como pago definitivo.
- **Fondos de inversión en instrumentos de deuda**: el fondo no es contribuyente. La persona acumula los intereses que se le asignan y recibe la constancia de la distribuidora (arts. 87-89). Fuente: https://mley.mx/LISR/articulo/88/ (secundaria). [NO VERIFICADO, confianza media]

### 2.2 Dividendos de emisoras mexicanas (art. 140 LISR)

- **Impuesto adicional del 10%**: lo retiene la emisora o el intermediario. Es pago **definitivo** y aplica a utilidades generadas desde 2014.
- **Acumulación y acreditamiento**: el dividendo puede acumularse en la anual **piramidado** (× 1.4286) y acreditar el ISR corporativo (dividendo × 0.4286). Esto solo procede si viene de CUFIN y se tiene la constancia.
- **Utilidades anteriores a 2014**: llevan una CUFIN separada y no pagan el 10% adicional.
- Fuentes: https://sdv.com.mx/compendio/ley-isr/articulo-140/ ; https://idconline.mx/fiscal-contable/2019/07/23/cuantas-cufin-existen (secundarias). [NO VERIFICADO, confianza alta]
- Que acumular sea **opcional o no** depende de la redacción vigente del art. 140. Por eso queda como **[AMBIGUO]**: decisión del contador.

### 2.3 Venta de acciones en BMV/BIVA y en el SIC (art. 129 LISR)

- **Tasa: 10% sobre la ganancia neta del ejercicio.** Es pago definitivo y no se acumula. Aplica a:
  - acciones de sociedades mexicanas, o títulos que las representen (incluidos índices y ETFs que califiquen);
  - **acciones extranjeras cotizadas en bolsas concesionadas en México (SIC)**.
- Fuentes: https://sdv.com.mx/compendio/ley-isr/articulo-129/ ; fragmento de https://wwwmat.sat.gob.mx/articulo/59621/articulo-129 [NO VERIFICADO, confianza alta]
- **Ganancia por emisora**: precio de venta − comisiones − **costo promedio por acción actualizado** (el costo se actualiza con el INPC). El **intermediario (casa de bolsa)** hace el cálculo y lo informa en su constancia anual. [NO VERIFICADO, confianza media en el detalle de la actualización]
- **Pérdidas**: se compensan contra ganancias del mismo tipo **dentro del ejercicio**, y el remanente contra ganancias de los **10 ejercicios siguientes**.
  - **Ojo**: el encargo decía 5 años, pero las fuentes encontradas dicen **diez**.
  - Fuentes: https://sdv.com.mx/compendio/ley-isr/articulo-129/ ; https://vlex.com.mx/vid/enajenacion-acciones-bolsa-valores-875056555 [NO VERIFICADO, confianza media]. Confirmar en el texto oficial.
- **Varias casas de bolsa**: cada una calcula por separado, y la persona **suma ganancias y pérdidas de todas en la anual**. [INFERIDO]
- **Excepciones con otro tratamiento**: tenencias de 10% o más de la emisora, operaciones fuera de bolsa, o tratamientos de residentes en el extranjero. No aplican al caso típico.

### 2.4 ETFs y FIBRAs (arts. 187-188 LISR)

**FIBRAs (CBFIs).**
- Lo que se distribuye de **resultado fiscal** lleva **retención del 30%** (art. 188).
- Lo que excede al resultado fiscal es **reembolso de capital**: no tiene retención y **disminuye el costo fiscal** del CBFI.
- La emisora publica en BMV, por cada distribución, cuánto corresponde a cada concepto (avisos "eventfid"/"fibderec" en bmv.com.mx).
- Fuentes: https://sdv.com.mx/compendio/ley-isr/articulo-188/ ; https://www.contadigital.mx/posts/fideicomiso-inmobilario-fibras (secundarias); ejemplo de aviso de emisora: https://www.bmv.com.mx/docs-pub/fibderec/fibderec_1068045_1.pdf [NO VERIFICADO, confianza alta]
- Para la persona física, la retención del 30% **no es definitiva**: el ingreso se acumula y la retención se acredita. [INFERIDO, confirmar con el contador]
- **Venta de CBFIs en bolsa**: 10% sobre la ganancia (vía art. 188 en relación con el 129). [NO VERIFICADO, confianza media]

**ETFs.**
- Mexicanos y extranjeros listados en el SIC: la **ganancia en la venta** suele tratarse con el art. 129 (10%).
- Las **distribuciones** de ETFs extranjeros se tratan como **dividendos o intereses del extranjero** (art. 142).
- **[AMBIGUO]**: el tratamiento depende de la naturaleza del ETF (de acciones, de deuda o mixto) y de lo que reporte el intermediario. La constancia de la casa de bolsa es la referencia práctica.

### 2.5 Fondos de inversión (arts. 87-89 LISR)

- **Renta variable**: la ganancia por la parte de acciones que cotizan en bolsa paga el **10% definitivo**, retenido por la distribuidora. Los intereses de la cartera se acumulan.
- **Deuda**: se acumulan los intereses reales.
- La distribuidora entrega una **constancia anual** (las fuentes indican "a más tardar el 15 de febrero").
- Fuente: https://mley.mx/LISR/articulo/88/ (secundaria). [NO VERIFICADO, confianza media]

### 2.6 Criptoactivos

- **No hay un régimen específico** en la LISR, la LIVA ni el CFF. Según las fuentes, la RMF 2026 tampoco agregó reglas. La Ley Fintech (art. 30) los define como "activos virtuales".
- La práctica dominante los trata como **enajenación de bienes (muebles intangibles)**, Cap. IV, arts. 119-126: ganancia = precio de venta − costo comprobado de adquisición.
  - Las fuentes citan el art. 126 (pago provisional del 20% cuando el adquirente no es persona moral, lo que en la práctica no ocurre en exchanges). [AMBIGUO]
  - En la anual, la ganancia se **acumula**, a diferencia de la bolsa, donde la tasa es fija de 10%.
- **Se consideran eventos gravables**: venta a pesos, swap entre criptos, pago con cripto. Las recompensas de staking o minería generan ingreso al valor de mercado.
- **Exención de 3 UMA anuales** (art. 93 fr. XIX inciso b) para bienes muebles: es **[AMBIGUO]** si aplica, porque el inciso excluye acciones, partes sociales, títulos valor e "inversiones del contribuyente".
- **Intercambio de información**: México se adhirió al **CARF de la OCDE**, que obliga a las plataformas a reportar. Las fuentes no coinciden en la fecha (operaciones de 2026 reportadas en 2027, o desde abril de 2026). **[AMBIGUO]**
- Fuentes (todas secundarias):
  - https://www.forvismazars.com/mx/es/insights/forvis-mazars-en-mexico-lideres-de-opinion/tax-alert/tributacion-de-criptoactivos-en-mexico
  - https://www.bdomexico.com/getmedia/3cce628c-786c-490e-8f8d-1cb8a7c4421a/BDO-Articulo-Tratamiento-Fiscal-de-Criptomonedas.pdf?ext=.pdf
  - https://www.veritas.org.mx/Ambito-universitario/Ambito-universitario/impuestos-sobre-las-criptomonedas-segun-analisis-de-la-prodecon (análisis de PRODECON)
- No encontré ningún documento del **SAT** que fije un criterio oficial para personas físicas. [NO VERIFICADO]

### 2.7 Ingresos de fuente extranjera (art. 142 LISR)

- **Dividendos de sociedades extranjeras** (fr. V):
  - Se acumulan en la anual y, además, pagan el **10% adicional definitivo**, a más tardar el día 17 del mes siguiente (si nadie retuvo).
  - Si se cobran vía SIC, el intermediario suele retener y emitir CFDI. GBM, por ejemplo, documenta que el impuesto retenido en el extranjero se puede acreditar.
  - Fuentes: https://idconline.mx/fiscal-contable/2023/04/12/declarar-dividendos-del-extranjero-en-anual-basico-para-personas-fisicas ; https://gbm.com/faqs/como-funcionan-los-impuestos-sobre-los-dividendos-en-trading-mx [NO VERIFICADO, confianza media]
- **Acreditamiento del impuesto extranjero**: art. 5 LISR, con tope del ISR mexicano que corresponde a ese ingreso, y requiere constancia (W-8BEN, 1042-S o estado de cuenta). [INFERIDO, sin fuente leída] **[AMBIGUO]** en el detalle.
- **Cuentas en el extranjero** (broker extranjero, exchange extranjero):
  - Los intereses y ganancias se declaran en la anual.
  - Existen obligaciones informativas para inversiones en regímenes fiscales preferentes (REFIPRE, arts. 176-178 LISR).
  - Además, el art. 90 LISR obliga a informar en la anual préstamos, donativos y premios mayores de $600,000. [NO VERIFICADO: no conseguí el texto, son referencias de memoria a confirmar]

### 2.8 Tipo de cambio e INPC

- **Tipo de cambio** (art. 20 CFF): se usa el tipo de cambio al que se **adquirió** la divisa. Si no hubo adquisición, el FIX que **Banxico publica en el DOF el día anterior** a la causación; si ese día no hubo publicación, el último publicado. Fuente: https://leyes-mx.com/codigo_fiscal_de_la_federacion/20.htm (secundaria). [NO VERIFICADO, confianza alta]
- **Factor de actualización** (art. 17-A CFF): INPC del mes anterior al más reciente del periodo / INPC del mes anterior al más antiguo; **si da menos de 1, se usa 1**. INEGI publica el INPC en el DOF en los primeros 10 días del mes siguiente. Fuente: https://sdv.com.mx/compendio/codigo-fiscal/articulo-17-a/ [NO VERIFICADO, confianza alta]
  - Serie oficial del INPC: https://www.inegi.org.mx/temas/inpc/ (no se pudo abrir).
  - **Cuidado**: algunos artículos (129, 124 y 134) usan **meses distintos** a la regla general. [AMBIGUO]

---

## 3. Deducciones personales (art. 151 LISR)

**Conceptos** (fuentes secundarias: https://sdv.com.mx/compendio/ley-isr/articulo-151/):
1. Honorarios médicos, dentales, psicología y nutrición; gastos hospitalarios; lentes ópticos (con tope).
2. Gastos funerarios (tope de 1 UMA anual).
3. Donativos a donatarias autorizadas (tope propio del 7%).
4. Intereses reales de crédito hipotecario.
5. **Aportaciones complementarias de retiro / voluntarias a la AFORE** (fr. V).
6. Primas de seguro de gastos médicos.
7. Transporte escolar obligatorio.
8. ISR local por salarios.

Además, las **colegiaturas** por decreto. [NO VERIFICADO, confianza alta en la lista general, media en los topes particulares]

**Tope global**: lo **menor** entre **5 UMA anuales** y el **15% de los ingresos totales** (incluidos los exentos). Fuentes: https://idconline.mx/fiscal-contable/2024/04/15/limite-a-deducciones-personales-en-la-anual-de-personas-fisicas ; https://www.elcontribuyente.mx/2026/04/cuanto-puedes-deducir-realmente-en-tu-declaracion-anual/ [NO VERIFICADO, confianza alta]
- Según las fuentes, quedan **fuera del tope global**: aportaciones de la fr. V, donativos, gastos médicos por incapacidad y colegiaturas.

**UMA (INEGI)** [NO VERIFICADO, confianza alta; INEGI bloqueado]:

| Año | Diaria | Mensual | Anual | Vigencia | 5 UMA anuales (cálculo propio) |
|---|---|---|---|---|---|
| 2025 | 113.14 | 3,439.46 | 41,273.52 | 1-feb-2025 a 31-ene-2026 | 206,367.60 |
| 2026 | 117.31 | 3,566.22 | 42,794.64 | 1-feb-2026 a 31-ene-2027 | 213,973.20 |

- 2025: https://www.taxtodaymexico.com/?p=11538 ; https://www.elcontribuyente.mx/2025/01/la-uma-2025-sube-4-21/
- 2026: comunicado INEGI 1/26 https://www.inegi.org.mx/contenidos/saladeprensa/boletines/2026/uma/uma2026.pdf (visto en el buscador, no descargado); https://www.adn40.mx/mexico/2026-01-08/uma-sube-2026-inegi-valor-dia-mes-ano/
- Página oficial: https://www.inegi.org.mx/temas/uma/

**AFORE voluntarias / complementarias (fr. V)**: tope propio de lo **menor entre el 10% de los ingresos acumulables y 5 UMA anuales**. El dinero debe permanecer hasta el retiro; un retiro anticipado se acumula y causa retención. Fuente: https://www.elcontribuyente.mx/2026/04/como-deducir-tu-ahorro-para-el-retiro-ante-el-sat/ [NO VERIFICADO, confianza alta]

**Art. 185 (cuentas especiales de ahorro)**: es un estímulo distinto, con tope fijo de **$152,000 al año**. Al retirar el dinero, se acumula el total. Puede combinarse con la fr. V. Fuente: https://sdv.com.mx/compendio/ley-isr/articulo-185/ [NO VERIFICADO, confianza alta]

**Colegiaturas (decreto)**:
- Topes anuales por alumno: preescolar $14,200; primaria $12,900; secundaria $19,900; profesional técnico $17,100; bachillerato $24,500.
- Las fuentes difieren en si superior/universidad ($35,000) está incluida. **[AMBIGUO]**
- Requisitos: CFDI y pago bancarizado.
- Fuentes: https://www.unotv.com/negocios/colegiaturas-y-transporte-escolar-que-puedes-deducir-ante-el-sat-en-2026/ ; https://www.taxtodaymexico.com/pagos-de-colegiaturas-son-deducibles/ [NO VERIFICADO]

**Requisito general de las deducciones**: CFDI a nombre del contribuyente y pago con medio electrónico (no en efectivo, salvo excepciones).

---

## Lo ambiguo (resolver con el contador)

1. **Tasa de retención de intereses 2026**: las fuentes dicen 0.90%, pero no coinciden en el artículo de la LIF 2026 (21 o 24), y varias citan la iniciativa. Confirmar en el DOF del 7-nov-2025.
2. **Pérdidas en bolsa**: las fuentes dicen 10 ejercicios (art. 129), no 5. Confirmar.
3. **Qué UMA usar en los topes anuales**: la UMA cambia el 1 de febrero, así que enero usa el valor del año anterior. La práctica común usa la UMA vigente al cierre del ejercicio.
4. **Cripto**:
   - ¿Enajenación de bienes (Cap. IV) con acumulación?
   - ¿Aplica la exención de 3 UMA del art. 93 fr. XIX b?
   - ¿Cómo se trata un swap cripto-cripto (permuta = dos enajenaciones)?
   - ¿Qué método de costo usar (identificación específica o promedio)? No hay regla del SAT para personas físicas.
5. **Dividendos mexicanos**: si acumular y acreditar el ISR corporativo es opcional o no, y si conviene. Depende de la CUFIN de origen.
6. **ETFs del SIC**: si la distribución es dividendo, interés o reembolso de capital; y el acreditamiento del impuesto retenido en EE. UU. (art. 5 LISR).
7. **FIBRAs**: si la retención del 30% es definitiva o acreditable para la persona física (inferí que es acreditable).
8. **Fecha de la declaración del ejercicio 2026**: se infiere el 30-abr-2027; puede moverse por día inhábil o por facilidades de la RMF.
9. **CARF**: desde cuándo reportan los exchanges al SAT.

## Qué suele pedir el contador a un inversionista

- **Constancias anuales de cada intermediario** (CFDI de retenciones e información de pagos): casa de bolsa (ganancias y pérdidas por art. 129, dividendos, intereses), banco y CETESdirecto (intereses nominales y reales, retención), distribuidoras de fondos de inversión. Se emiten típicamente en febrero.
- **Estados de cuenta mensuales** de todo el año (enero a diciembre) de cada casa de bolsa, banco, fondo y exchange.
- **Detalle de FIBRAs**: por cada distribución, cuánto fue resultado fiscal y cuánto reembolso de capital, más la retención.
- **Dividendos extranjeros / SIC**: monto bruto, impuesto retenido en el extranjero, retención mexicana, tipo de cambio aplicado; si aplica, formas W-8BEN y 1042-S.
- **Cripto**: historial completo de operaciones por exchange y wallet (fecha, par, cantidad, precio, comisión), costo de adquisición, reporte de ganancias y pérdidas, y recompensas de staking.
- **Pérdidas pendientes** de ejercicios anteriores (bolsa, inflación) con su año de origen.
- **Deducciones personales**: CFDI de médicos, seguros, colegiaturas, intereses hipotecarios, aportaciones voluntarias (constancia de la AFORE) y art. 185.
- **Datos generales**: constancia de sueldos del patrón (si aplica), RFC, e.firma vigente, CLABE para devolución, y declaración anual del año anterior.
- **Cuentas en el extranjero**: estados de cuenta y país, por si hay obligaciones de REFIPRE o informativas.

## Sugerencia para Faro (inferido)

Guardar por cada operación:
- fecha, tipo, instrumento, intermediario y moneda;
- monto bruto, comisión y retención;
- tipo de cambio FIX del día anterior, con su fuente;
- y adjuntar el PDF o XML de la constancia.

Faro solo debe generar **resúmenes por intermediario y por concepto** para el contador, sin calcular el ISR definitivo.
