# CFDI 4.0 e importadores bancarios para Faro

Fecha de consulta de todas las fuentes: **2026-10-03**.

## Cómo se verificó (leer primero)

Desde este entorno, `WebFetch` está **bloqueado por el proxy de salida** para sat.gob.mx, omawww.sat.gob.mx, banxico.org.mx, federalreserve.gov, inegi.org.mx y stats.gov.cn. Por eso **ninguna página se leyó completa**. Todo sale de resultados de `WebSearch`, la mayoría con filtro `allowed_domains` restringido al dominio oficial. Los niveles de estado son:

| Estado | Significado |
|---|---|
| **VERIFICADO** | El contenido aparece en un resultado de búsqueda cuya URL es del sitio oficial (SAT, banco, etc.). No se pudo abrir la página completa. Conviene que una persona lo revise antes de usarlo en producción. |
| **REPORTADO** | Viene de un tercero (blog, foro, proveedor de facturación, agregador de calendarios). |
| **INFERIDO** | Es una deducción mía a partir de una regla verificada. No es un dato publicado. |
| **NO VERIFICADO** | No encontré una fuente. No lo uses como dato. |

---

## 1. CFDI 4.0: lo esencial del XML

### 1.1 Estándar, XSD y namespaces

| Elemento | Valor | Estado | Fuente |
|---|---|---|---|
| Namespace del comprobante | `http://www.sat.gob.mx/cfd/4` (prefijo habitual `cfdi`) | VERIFICADO (se infiere del schemaLocation oficial; coincide con la petición) | Anexo 20 Guía de llenado, SAT: http://omawww.sat.gob.mx/tramitesyservicios/Paginas/documentos/Anexo_20_Guia_de_llenado_CFDI.pdf |
| XSD del comprobante | `http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd` | VERIFICADO | Documentación técnica SAT: http://omawww.sat.gob.mx/tramitesyservicios/Paginas/documentos/Documentacion_tecnica.pdf ; Anexo 20 RMF 2022: http://omawww.sat.gob.mx/tramitesyservicios/Paginas/documentos/Anexo20_2022.pdf |
| XSD de catálogos | `http://www.sat.gob.mx/sitio_internet/cfd/catalogos/catCFDI.xsd` (tipo `catCFDI:c_UsoCFDI`, etc.) | VERIFICADO | mismas fuentes |
| Timbre Fiscal Digital | namespace `http://www.sat.gob.mx/TimbreFiscalDigital` (prefijo `tfd`), `Version="1.1"`, atributos `UUID` y `FechaTimbrado`, entre otros. XSD: `http://www.sat.gob.mx/sitio_internet/cfd/timbrefiscaldigital/TimbreFiscalDigitalv11.xsd` | REPORTADO (fuentes no SAT que citan el estándar) | https://cryptosys.net/firmasat/FirmaSATManual.html.md ; https://www.gncys.com/anexo20/docs/Anexo20_2022.pdf (copia del Anexo 20) |
| Complemento de pagos 2.0 | namespace `http://www.sat.gob.mx/Pagos20` (prefijo `pago20`). XSD: `http://www.sat.gob.mx/sitio_internet/cfd/Pagos/Pagos20.xsd`. Entró en vigor el 1-ene-2022 y es obligatorio desde el 1-abr-2023 | VERIFICADO | Estándar Pagos 2.0, SAT: http://omawww.sat.gob.mx/tramitesyservicios/Paginas/documentos/Pagos20.pdf ; Guía de llenado de pagos: http://omawww.sat.gob.mx/tramitesyservicios/Paginas/documentos/Guia_llenado_pagos.pdf |
| Página índice del Anexo 20 | http://omawww.sat.gob.mx/tramitesyservicios/Paginas/anexo_20.htm | NO VERIFICADO (la URL existe en el patrón de SAT, pero la conexión fue bloqueada y no se confirmó su contenido) | — |

### 1.2 Estructura que Faro necesita leer

Lo siguiente es la estructura que pidió la tarea. La existencia de los atributos en CFDI 4.0 es conocimiento estándar del Anexo 20. De las fuentes consultadas solo confirmé explícitamente `UsoCFDI`, `RegimenFiscalReceptor`, `DomicilioFiscalReceptor` y los nodos nuevos de la 4.0 (`Exportacion`, `ObjetoImp`, `InformacionGlobal`, `ACuentaTerceros`). Antes de cerrar el parser, valida contra `cfdv40.xsd`.

```
cfdi:Comprobante  Version="4.0" Fecha SubTotal Total Moneda TipoCambio? TipoDeComprobante
                  FormaPago? MetodoPago? Exportacion LugarExpedicion Serie? Folio?
  cfdi:InformacionGlobal?            (solo facturas globales)
  cfdi:CfdiRelacionados*
  cfdi:Emisor     Rfc Nombre RegimenFiscal
  cfdi:Receptor   Rfc Nombre DomicilioFiscalReceptor RegimenFiscalReceptor UsoCFDI
  cfdi:Conceptos
    cfdi:Concepto ClaveProdServ Cantidad ClaveUnidad Descripcion ValorUnitario Importe ObjetoImp Descuento?
      cfdi:Impuestos/Traslados/Traslado  Base Impuesto TipoFactor TasaOCuota? Importe?
  cfdi:Impuestos? TotalImpuestosTrasladados? TotalImpuestosRetenidos?
  cfdi:Complemento
    tfd:TimbreFiscalDigital  Version="1.1" UUID FechaTimbrado RfcProvCertif SelloCFD NoCertificadoSAT SelloSAT
    pago20:Pagos?            (solo si TipoDeComprobante="P")
```

Valores que el clasificador va a usar:

- **TipoDeComprobante**: `I` ingreso, `E` egreso (nota de crédito), `T` traslado, `N` nómina, `P` pago. Estado: conocimiento estándar del catálogo `c_TipoDeComprobante`. No lo encontré en una fuente consultada hoy, así que va como **NO VERIFICADO hoy**.
- **MetodoPago**: `PUE` (pago en una sola exhibición) o `PPD` (pago en parcialidades o diferido). `PPD` está VERIFICADO en Pagos20.pdf. `PUE` es estándar pero no lo confirmé hoy.
- **FormaPago** (`c_FormaPago`): sirve para saber si la deducción se pagó por medio electrónico. Conocidos de memoria: `01` efectivo, `02` cheque nominativo, `03` transferencia, `04` tarjeta de crédito, `28` tarjeta de débito, `99` por definir. **NO VERIFICADO hoy**: confírmalo contra `catCFDI.xls` antes de codificarlo.

### 1.3 Usos de CFDI para deducciones personales (catálogo `c_UsoCFDI`, serie D)

| Clave | Descripción | Estado | Fuente |
|---|---|---|---|
| D01 | Honorarios médicos, dentales y gastos hospitalarios | VERIFICADO (SAT, minisitio Deducciones personales) | https://www.sat.gob.mx/minisitio/DeduccionesPersonales/gastos_medicos.html |
| D02 | Gastos médicos por incapacidad o discapacidad | REPORTADO | https://www.edifact.com.mx/masinfo/catalogo-uso-cfdi-sat ; https://facturama.mx/blog/que-significa/uso-de-cfdi/ |
| D03 | Gastos funerales | REPORTADO | ídem |
| D04 | Donativos | REPORTADO | ídem |
| D05 | Intereses reales efectivamente pagados por créditos hipotecarios (casa habitación) | REPORTADO | ídem |
| D06 | Aportaciones voluntarias al SAR | REPORTADO | ídem |
| D07 | Primas por seguros de gastos médicos | REPORTADO | ídem |
| D08 | Gastos de transportación escolar obligatoria | REPORTADO | ídem |
| D09 | Depósitos en cuentas para el ahorro, primas que tengan como base planes de pensiones | REPORTADO | ídem |
| D10 | Pagos por servicios educativos (colegiaturas) | VERIFICADO (SAT, minisitio Colegiaturas) | https://www.sat.gob.mx/minisitio/DeduccionesPersonales/colegiaturas.html |

Varias fuentes coinciden en estas descripciones, pero para D02 a D09 no leí el catálogo oficial (`catCFDI.xls`) porque el acceso estaba bloqueado. **Acción**: descarga `catCFDI.xls` del SAT y genera la tabla desde ahí, con su columna "Régimen Fiscal Receptor". No la escribas a mano. Otros usos frecuentes: `G03` gastos en general, `S01` sin efectos fiscales, `CP01` pagos. Están **NO VERIFICADOS hoy**.

### 1.4 Requisito de pago por medios electrónicos

- **VERIFICADO**. Para las deducciones personales, el pago debe hacerse con **cheque nominativo del contribuyente, transferencia electrónica de fondos desde cuentas a su nombre en instituciones del sistema financiero, tarjeta de crédito, débito o de servicios**. **Si se paga en efectivo, no es deducible.** La autoridad puede liberar esta obligación cuando el pago se hace en poblaciones o zonas rurales sin servicios financieros.
  - LISR art. 151 en el portal SAT: https://wwwmatnp.sat.gob.mx/articulo/82615/articulo-151
  - Ficha SAT: http://m.sat.gob.mx/fichas_tematicas/reforma_fiscal/Documents/deduccionespersonales.pdf
  - Trámite de excepción rural: https://www.sat.gob.mx/tramites/19266/autorizacion-para-deducir-erogaciones-en-efectivo-en-zonas-rurales-o-sin-servicios-financieros
- **REPORTADO**. Un resultado del portal SAT menciona un umbral de **$2,000** para gastos en general (art. 27 LISR). Es una regla de **deducciones de actividad empresarial**, no de deducciones personales. No la mezcles. https://wwwmat.sat.gob.mx/articulo/05481/articulo-27
- Colegiaturas (D10) y transporte escolar tienen reglas propias, que vienen de un decreto de estímulo. No revisé sus límites. **NO VERIFICADO**.
- Límite global de las deducciones personales: **NO VERIFICADO hoy**. No lo codifiques sin leer el art. 151 vigente.

**Regla para Faro (INFERIDA)**: marca un CFDI como "candidato deducible" solo si se cumplen tres condiciones:
1. `UsoCFDI` empieza con `D`.
2. `Receptor/@Rfc` es el RFC del usuario.
3. `FormaPago` es distinto de `01`. Si es `PPD`, el medio real está en el complemento de pago (§1.5).

Además, cruza con un movimiento bancario (§3) por monto y fecha, porque sirve como evidencia.

### 1.5 Complemento de pagos (REP)

- **VERIFICADO**. Cuando la factura original tiene `MetodoPago="PPD"`, el proveedor emite después un CFDI tipo `P` con `pago20:Pagos`. Cada documento relacionado trae `NumParcialidad`, `ImpSaldoAnt` e `ImpSaldoInsoluto`, que son obligatorios cuando `MetodoDePagoDR="PPD"`.
  - http://omawww.sat.gob.mx/tramitesyservicios/Paginas/documentos/Pagos20.pdf
  - http://omawww.sat.gob.mx/tramitesyservicios/Paginas/recepcion_de_pagos.htm
- **INFERIDO para Faro**. Un CFDI `PPD` se marca como "pagado" cuando llega su REP y `ImpSaldoInsoluto` es 0. El vínculo es `DoctoRelacionado/@IdDocumento`, que contiene el UUID de la factura original.

### 1.6 Dónde bajar los CFDI

- **VERIFICADO**. El servicio del SAT "Consulta y recuperación de comprobantes" permite, como emisor o receptor:
  - recuperar **hasta 2,000 XML por día** y hasta un millón de registros de metadatos;
  - ver en el portal solo los primeros 500 resultados por consulta;
  - las solicitudes se procesan en máximo 48 h y quedan disponibles 3 días;
  - recuperar versiones 3.0, 3.2, 3.3 y 4.0, más CFDI de retenciones.

  Con e.firma existe un **web service de descarga masiva** de hasta 200,000 registros por solicitud.
  - Portal: https://wwwmat.sat.gob.mx/consultas/42968/consulta-y-recuperacion-de-comprobantes-(nuevo)
  - Aplicación: https://www.sat.gob.mx/aplicacion/82471/consulta,-cancela-y-recupera-tus-facturas-electronicas
  - Documentación del web service: https://www.sat.gob.mx/cs/Satellite?blobcol=urldata&blobkey=id&blobtable=MungoBlobs&blobwhere=1461174995026&ssbinary=true
- **Recomendación para Faro (INFERIDA)**: empieza con un flujo manual. El usuario descarga un ZIP del portal y lo suelta en una carpeta, y Faro lo importa. No conviene integrar el web service en la v1, porque exige manejar la e.firma (.cer/.key) localmente, y ese riesgo hay que evaluarlo antes.

### 1.7 Constancia de Situación Fiscal (CSF)

- **VERIFICADO**. Es un documento que incluye la **Cédula de Identificación Fiscal (CIF)**, los datos de identificación, los datos de ubicación (domicilio fiscal), las actividades económicas, los regímenes fiscales, las obligaciones fiscales y, en su caso, el representante legal. Se genera en línea con contraseña o e.firma (botón "Generar Constancia"). Personas físicas también pueden obtenerla con SAT ID.
  - https://wwwmat.sat.gob.mx/aplicacion/53027/genera-tu-constancia-de-situacion-fiscal.
  - https://www.sat.gob.mx/tramites/19543/solicitud-de-generacion-de-constancia-de-situacion-fiscal-con-cif-para-personas-fisicas-a-traves-de-sat-id
- **Uso en Faro (INFERIDO)**: de la CSF se capturan a mano RFC, código postal fiscal y régimen. Sirven para validar que en cada CFDI `Receptor/@DomicilioFiscalReceptor` y `@RegimenFiscalReceptor` coincidan, porque si no coinciden la factura está mal emitida y conviene pedir que la corrijan.

---

## 2. Formatos de exportación bancaria (México)

**Conclusión general**: ningún banco documenta públicamente los nombres de columna de su CSV para personas. **No escribí ningún nombre de columna** que no viniera de una fuente.

| Institución | ¿Exporta movimientos? | Formatos | Columnas | Estado | Fuente |
|---|---|---|---|---|---|
| **Banorte** (banca en línea personas) | Sí. Menú Consultas → Movimientos → elegir alias → botón **"Exportar"** | **Texto (.txt)** o **Excel (csv)**. Cubre el mes actual y los 2 meses anteriores | No documentadas | VERIFICADO (formatos) / NO VERIFICADO (columnas) | https://www.banorte.com/dam/jcr:6ec65099-6bf8-418c-80e0-64a2b9dc0eb6/Consulta_de_movimientos.pdf |
| **BBVA México** (bbva.mx / app, personas) | Consulta de movimientos de hasta 2 meses atrás y estado de cuenta en **PDF**. No encontré una exportación CSV para personas | PDF (estado de cuenta). La exportación **PDF, CSV, TXT, C43 y CAMT.053** existe en **BBVA Net Cash (empresas)**, no en la banca de personas | No documentadas | VERIFICADO (PDF personas; Net Cash empresas) / NO VERIFICADO (CSV personas) | https://www.bbva.mx/personas/banca-por-internet.html ; https://www.bbva.mx/empresas/banca-electronica-y-canales.html ; https://www.bbva.mx/personas/servicios-digitales/consulta-estado-de-cuenta.html |
| **Santander México** | El centro de ayuda describe la consulta de movimientos en la app (Todos / Pagos / Gastos) y la descarga del estado de cuenta. No encontré exportación CSV/XLS | Desconocido | Desconocidas | NO VERIFICADO | https://www.santander.com.mx/personas/santander-digital/centro-de-ayuda/consulta-de-saldos-y-movimientos.html |
| **HSBC México** | Banca por Internet → Administrar → Estados de cuenta electrónicos → Consultar | **PDF o XML** (estado de cuenta). No encontré CSV de movimientos | Desconocidas | VERIFICADO (PDF/XML) / NO VERIFICADO (CSV) | https://www.hsbc.com.mx/content/dam/hsbc/mx/documents/digital/estados-de-cuenta/descarga_estados_cuenta.pdf |
| **Nu México** | Estados de cuenta en la app (Tarjeta de crédito → Estados de cuenta) y PDF por correo en la fecha de corte. No encontré exportación CSV | PDF | — | VERIFICADO (PDF, blog oficial de Nu) / NO VERIFICADO (CSV) | https://blog.nu.com.mx/productos-nu/tarjeta-de-credito/consultar-tu-estado-de-cuenta-en-la-app-nu/ ; https://comunidad.nu.com.mx/t/estado-de-cuenta-con-informacion-mas-completa/16664 (foro: usuarios piden más detalle) |
| **Mercado Pago** | Sí. Reportes de cuenta ("Dinero en cuenta", "Liberaciones", "Dinero disponible"), manuales o programados (diario, semanal o mensual), hasta 1 año por solicitud | **.csv y .xlsx** | Documentadas en "Campos del reporte". Confirmé estas: `SOURCE_ID` (ID de operación), `DATE` (fecha de liquidación) y `NET_CREDIT_AMOUNT` (monto neto acreditado). El glosario tiene más; léelo completo | VERIFICADO (formatos y esas 3 columnas) | https://www.mercadopago.com.mx/blog/descargar-reportes-de-cuenta-para-contador ; https://www.mercadopago.com.mx/developers/es/docs/checkout-api-payments/additional-content/reports/account-money/report-fields ; https://www.mercadopago.com.mx/developers/es/docs/reports/activities-reports/generate |

Notas:
- El reporte de Mercado Pago está pensado para **vendedores e integradores**. Por inferencia, `NET_DEBIT_AMOUNT` debería existir como contraparte de `NET_CREDIT_AMOUNT`, pero **NO lo verifiqué**. Confírmalo en el glosario.
- Para bancos que solo dan PDF (BBVA, HSBC y Nu en personas), la vía realista es una de estas dos:
  - captura vía bot de Telegram (ya existe en Faro);
  - parser de PDF. **No recomendado en v1**: los layouts no están documentados y son frágiles.
- El XML del estado de cuenta de HSBC podría ser un CFDI (los bancos timbran sus estados de cuenta). **NO VERIFICADO**. Si lo es, se reutiliza el parser del §4.1.

---


## 4. Diseño recomendado de importadores (INFERIDO, propuesta de arquitectura)

### 4.1 Importador CFDI (solo stdlib)

```python
import xml.etree.ElementTree as ET   # stdlib; no se necesita lxml
NS = {
    "cfdi": "http://www.sat.gob.mx/cfd/4",
    "tfd":  "http://www.sat.gob.mx/TimbreFiscalDigital",
    "pago20": "http://www.sat.gob.mx/Pagos20",
}
def parse_cfdi(path):
    root = ET.parse(path).getroot()
    if root.tag != "{http://www.sat.gob.mx/cfd/4}Comprobante":
        raise ValueError("no es CFDI 4.0")   # 3.3 usa http://www.sat.gob.mx/cfd/3: decidir si se soporta
    tfd = root.find("cfdi:Complemento/tfd:TimbreFiscalDigital", NS)
    em, rc = root.find("cfdi:Emisor", NS), root.find("cfdi:Receptor", NS)
    return {
        "uuid": tfd.get("UUID").upper(),
        "fecha": root.get("Fecha"), "fecha_timbrado": tfd.get("FechaTimbrado"),
        "tipo": root.get("TipoDeComprobante"),
        "subtotal": Decimal(root.get("SubTotal")), "total": Decimal(root.get("Total")),
        "moneda": root.get("Moneda"), "tipo_cambio": root.get("TipoCambio"),
        "forma_pago": root.get("FormaPago"), "metodo_pago": root.get("MetodoPago"),
        "emisor_rfc": em.get("Rfc"), "emisor_nombre": em.get("Nombre"),
        "emisor_regimen": em.get("RegimenFiscal"),
        "receptor_rfc": rc.get("Rfc"), "uso_cfdi": rc.get("UsoCFDI"),
        "receptor_cp": rc.get("DomicilioFiscalReceptor"),
        "receptor_regimen": rc.get("RegimenFiscalReceptor"),
        "conceptos": [c.attrib for c in root.iterfind("cfdi:Conceptos/cfdi:Concepto", NS)],
    }
```

- **Seguridad**: `xml.etree` de la stdlib no resuelve entidades externas por defecto, pero su documentación advierte sobre "billion laughs". Si los XML vienen solo del SAT o del usuario, el riesgo es bajo. Si quieres blindarlo, `defusedxml` es una dependencia mínima.
- **Montos**: siempre `Decimal`, nunca `float`. Si `Moneda != "MXN"`, guarda `TipoCambio` y calcula el equivalente en MXN.
- **Idempotencia**: usa `UUID` como **clave natural única** (`UNIQUE (uuid)`) e inserta con `INSERT ... ON CONFLICT (uuid) DO NOTHING`. Así se puede reimportar el mismo ZIP del SAT sin duplicar.
  - Esto respeta la filosofía del repo ("restatement-is-a-new-row") sin chocar con ella: un CFDI timbrado es inmutable. Una cancelación es un evento aparte, que conviene guardar como fila de estado (`cfdi_status(uuid, status, checked_at)`).
- **Guarda el XML crudo** (texto, o su hash más la ruta) para auditoría.
- **Clasificación**:
  - `uso_cfdi` en D01–D10 → categoría "deducción personal".
  - `receptor_rfc` distinto del RFC del usuario → advertencia.
  - `forma_pago == "01"` → "no deducible: efectivo".
  - `metodo_pago == "PPD"` → pendiente hasta que llegue su REP.
- **Migración**: Faro no tiene un runner de migraciones (ver AGENTS.md), así que se crea un nuevo `db/migrations/NNN_cfdi.sql` y se aplica a mano.
- **Ruta API**: va en `api/routers/finance.py`. Esta parte **no tiene demo fallback**: si no hay BD, responde 503.

### 4.2 Importador CSV/XLSX bancario con perfiles de mapeo

Como no hay columnas documentadas (excepto Mercado Pago), el importador debe ser **configurable**. No pongas columnas fijas en el código.

```yaml
# config/bank_profiles/banorte_csv.yaml  — EJEMPLO; los nombres de columna se llenan
# a partir de un archivo real exportado por el usuario, NO de esta investigación.
id: banorte_csv
match: { header_contains: ["<col fecha real>", "<col monto real>"] }
encoding: [utf-8-sig, cp1252, latin-1]   # bancos MX suelen exportar en cp1252
delimiter: auto            # csv.Sniffer
skip_rows: 0
date: { column: "<col fecha>", formats: ["%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"] }
amount:
  mode: split              # split = columnas cargo/abono separadas | signed = una columna con signo
  debit: "<col cargo>"
  credit: "<col abono>"
  decimal: "."             # o ","
  thousands: ","
description: ["<col descripcion>", "<col referencia>"]
external_id: null          # si el banco da folio/referencia única, mapearla aquí
```

- **Detección de perfil**: busca la cabecera entre las primeras N filas, porque muchos bancos meten filas de metadatos (titular, cuenta) antes de la tabla. Elige el perfil cuyo `header_contains` coincida.
- **Idempotencia sin ID del banco**: `fingerprint = sha256(account_id | fecha | monto | descripcion_normalizada | ordinal_dia)`. El `ordinal_dia` es el índice de esa combinación repetida dentro del mismo día, y evita colapsar dos cargos idénticos legítimos (por ejemplo, dos cafés iguales). Hay `UNIQUE (account_id, fingerprint)`.
  - Si el perfil da un `external_id` (Mercado Pago tiene `SOURCE_ID`), úsalo en lugar del fingerprint.
- **Ventanas que se traslapan**: Banorte solo da el mes actual más 2 meses, así que las importaciones repetidas se van a traslapar. El fingerprint absorbe ese traslape.
- **XLSX**: `openpyxl` es una dependencia. Si quieres solo stdlib, pide al usuario CSV, o lee el .xlsx como ZIP más XML. No vale la pena.
- **Flujo de UI**: subir archivo → vista previa de las primeras 20 filas → elegir o crear perfil (mapear columnas con dropdowns) → guardar el perfil → importar. Así el usuario captura las columnas reales una sola vez.
- **Conciliación con CFDI**: candidatos = `|monto_banco| == cfdi.total` (con ±1 MXN de tolerancia por redondeo) y `fecha_banco` dentro de ±5 días de `cfdi.fecha`. Para `PPD`, se compara contra el `Monto` del REP. La confirmación queda en manos del usuario.

### 4.3 Siguientes pasos que requieren a una persona

1. Descargar `catCFDI.xls` del SAT y generar las tablas `c_UsoCFDI` y `c_FormaPago` desde ahí.
2. Exportar un archivo real de cada banco que use Patricio y crear su perfil YAML con las cabeceras reales.
3. Leer el glosario completo de "Campos del reporte" de Mercado Pago.
