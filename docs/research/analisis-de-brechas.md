# Análisis de brechas: Faro frente a herramientas parecidas

Fecha de consulta de todas las fuentes: 2026-10-03. Fase 2 del plan de auditoría.

## Cómo leer este documento

- **Límite de verificación.** Desde este entorno solo funcionó el buscador web; la lectura directa de muchos sitios (finviz, koyfin, tradingview, ghostfol.io, wealthfolio.app, koinly, cointracker, bitso, gbm, bmv, rankia) fue bloqueada por el proxy de red. Lo marcado **[V]** se confirmó en la fuente citada o en su extracto de búsqueda; **[T]** / **[V-3º]** viene de terceros; **[I]** es inferencia; **NO VERIFICADO** no se pudo confirmar. Antes de implementar algo que dependa de un formato o término de servicio, abre el enlace.
- **Regla de licencias.** Una *idea* o función (TWR, X-ray, un tipo de reporte) se reimplementa desde cero sin problema. No se copia código AGPL/GPL (Ghostfolio, Wealthfolio, rotki, Beancount) ni se *scrapea* donde los términos lo prohíben (Morningstar, TradingView, BMV, y Yahoo según sus ToS).
- **Corrección a una fuente.** El informe internacional sugiere "conservar el respaldo con Stooq": `stooq_provider` está fuera de servicio desde D5 (404 / reto anti-bots); no es un respaldo real.

## Las 15 funciones de mayor valor para Faro (consolidado)

| # | Función | Inspiración | ¿La tenemos? | Valor | Esf. | Dependencias | Licencia / términos |
|---|---|---|---|---|---|---|---|
| 1 | **Libro de inversiones** por lotes: compras, ventas, comisiones, costo promedio por emisora (art. 129 LISR), dividendos, distribuciones de FIBRA, MXN con tipo de cambio fechado | Ghostfolio, Wealthfolio, Portfolio Performance, Kuspit | no | alto | L | migración 0016 | idea libre (no copiar AGPL) |
| 2 | **Importador de CFDI de Retenciones (XML)**: complementos enajenación de acciones, dividendos, intereses, arrendamiento en fideicomiso | GBM, SAT | no | alto | M | 1 | estándar público del SAT; `python-satcfdi` es MIT |
| 3 | **Papeles de trabajo anuales para el contador** (ganancia/pérdida art. 129, dividendos MX/SIC, intereses reales, retenciones) — conciliación, no cálculo definitivo | Sharesight, CoinTracker, SAT | no | alto | M | 1, 2 | idea libre |
| 4 | **Rendimiento TWR y XIRR** por cuenta y total | Portfolio Performance, Wealthfolio | no | alto | M | 1 | idea libre |
| 5 | **Comparación contra referencias**: S&P 500, IPC, CETES, inflación MX (series ya existen) | Ghostfolio, Finviz | parcial | alto | S | 1 | idea libre |
| 6 | **Distribuciones de FIBRA** separadas en resultado fiscal (retención) y reembolso de capital (reduce costo) | BMV avisos de derechos | no | alto | M | 1 | captura manual; **sin scraping de bmv.com.mx** |
| 7 | **Watchlist y alertas en el servidor** (precio, % de cambio) por el bot de Telegram existente | TradingView, Finviz, Delta | no | alto | S | — | idea libre |
| 8 | **Importador de estados de cuenta bancarios CSV** con perfiles de columnas configurables | Portfolio Performance, YNAB | no | alto | M | — | formatos no documentados (ver `docs/sat/`) |
| 9 | **Cripto: posiciones y lotes** + importar/exportar CSV universal de Koinly y de CoinTracker | Koinly, CoinTracker, rotki | no | alto | S-M | 1 | formatos públicos |
| 10 | **X-ray de asignación**: clase, sector, país, moneda, concentración con umbrales | Ghostfolio, Morningstar | parcial (heatmap) | alto | S | 1 | idea libre |
| 11 | **Calendario** de publicaciones macro y de obligaciones fiscales | Koyfin, Yahoo | no | medio | S | — | fuentes oficiales |
| 12 | **Bóveda fiscal anual**: checklist de constancias por broker/año y archivo local de PDF/XML | GBM, Cetesdirecto | no | medio | S | — | archivos del usuario |
| 13 | **Rebalanceo** contra asignación objetivo (PyPortfolioOpt ya está) | Portfolio Performance, Wealthfolio | no | medio | M | 1, 10 | idea libre |
| 14 | **Respaldo y exportación local** (pg_dump + JSON/CSV) | Kubera (paquete para beneficiario), Wealthfolio | no | medio | S | — | — |
| 15 | **Monte Carlo de retiro / FIRE** sobre activos invertibles reales | Empower, Portfolio Visualizer | parcial (número FIRE) | medio | M | 1 | idea libre |

Siguientes candidatos: score explicable tipo "N checks binarios" sobre los factores fundamentales existentes (Simply Wall St, solo la idea), calendario de dividendos y *earnings*, rollover de presupuesto y "Age of Money" (Monarch, YNAB), analizador de comisiones (Empower), sincronización de solo lectura con la API de Bitso (llaves solo en `.env`).

## Encaje con una app local de un solo usuario

Los referentes más cercanos son **Wealthfolio** (local-first, AGPL-3.0) y **Portfolio Performance** (escritorio, EPL-1.0): demuestran que un libro de inversiones local con TWR/IRR e importadores es viable sin agregadores bancarios. Las funciones de agregación automática (Empower, Monarch) no aplican en México y quedan fuera de alcance (no se conectan bancos con credenciales). Ninguna herramienta revisada genera reportes fiscales específicos para el SAT (Koinly y CoinTracker tratan a México con métodos genéricos), y esa es la brecha donde Faro puede aportar más.

## Riesgo transversal de datos

Faro obtiene precios con `yfinance`. Según el extracto de sus términos citado por un tercero, Yahoo prohíbe el acceso automatizado no provisto por ellos (NO VERIFICADO en el texto oficial). Para uso personal el riesgo práctico es el bloqueo o el cambio de formato, no una reclamación; aun así conviene: (a) reintentos y monitoreo de huecos (auditoría D-1), (b) usar fuentes oficiales donde existan (FRED, Banxico SIE, Treasury), (c) evaluar un proveedor con API y términos claros para precios si se vuelve crítico.

---

# Anexo A — Herramientas internacionales y proyectos de código abierto

---

### A1. Fichas por herramienta

### Ghostfolio (OSS)
- AGPL-3.0 [V] https://github.com/ghostfolio/ghostfolio. Release 3.77.0 del 2026-10-02, según el CHANGELOG [V] https://raw.githubusercontent.com/ghostfolio/ghostfolio/main/CHANGELOG.md. Stack: Angular + NestJS + Postgres + Prisma + Redis [V].
- Hace mejor que Faro: ledger de operaciones multi-cuenta, rendimiento ROAI (que ya incluye dividendos según la 3.75.0) [V], import/export, Zen mode y PWA [V].
- Le falta a Faro: **X-ray** (reglas estáticas de concentración y diversificación con umbrales configurables), **calculadora FIRE**, **comparación contra benchmark** y watchlist de activos fuera del portafolio [T] https://openapps.pro/apps/ghostfolio. La 3.77.0 añade una herramienta MCP de rendimiento [V].
- Encaje: alto como fuente de ideas (mismo stack de BD). Por ser AGPL, conviene reimplementar las ideas y no copiar código [I].

### Wealthfolio (OSS)
- AGPL-3.0 [V] https://github.com/afadil/wealthfolio. v3.9.1 del 2026-09-27; v3.9.0 del 2026-09-26 trajo perfiles, bloqueo de la app, cifrado opcional de la BD y dashboard de insights [V] https://github.com/afadil/wealthfolio/releases.
- Es local-first (escritorio y Docker), con TWR y MWR, import CSV, metas, multi-moneda y sistema de add-ons [V].
- Le falta a Faro: **reporte de ingresos (dividendos e intereses)**, **monitoreo de límites de aportación** a cuentas con beneficio fiscal (en México sería PPR o deducibles [I]), Monte Carlo para retiro y recomendaciones de rebalanceo [T] https://docs.elfhosted.com/app/wealthfolio/.
- Encaje: es el referente más cercano a Faro, local y de un solo usuario [I].

### Portfolio Performance (OSS)
- EPL-1.0 [V] https://github.com/portfolio-performance/portfolio. v0.87.0 del 2026-08-16 (agrupación de operaciones por lote) [V] https://github.com/portfolio-performance/portfolio/releases.
- Hace mejor que Faro: **TTWROR e IRR**, **import de estados de cuenta en PDF** de muchos bancos, rebalanceo con **taxonomías** y dividendos [V]. La v0.86.0 añadió import/export CSV de atributos personalizados [V].
- Le falta a Faro: un modelo de taxonomías libres para clasificar activos (clase, región, estrategia) y un parser de estados de cuenta [I].
- Encaje: es una app Java de escritorio; sirve como referencia metodológica de TTWROR/IRR, no como integración [I].

### Sharesight (propietario, SaaS)
- Importa operaciones de brokers y registra eventos corporativos (dividendos, splits, recompras). Genera reportes de rendimiento y fiscales, incluido el de ganancias de capital [T] https://apps.xero.com/us/app/sharesight.
- Reportes destacados: **Contribution analysis** (qué explica el rendimiento), **Multi-period**, **Future income** (dividendos anunciados más una proyección a 3 años), **Diversity** y **Exposure** (lo que hay dentro de cada ETF) [T, blog oficial] https://www.sharesight.com/blog/7-reasons-to-upgrade-your-sharesight-account , https://www.sharesight.com/blog/multi-period-report/.
- Los reportes fiscales cubren AUS/NZ/UK/CA, no México [T] https://quantroutine.com/tools/sharesight/.
- Términos: NO VERIFICADO. Solo inspiración (ideas de reportes) [I].

### Koyfin (propietario)
- Dashboards personalizables, screener global, estimados de analistas, transcripciones, macro, calendario económico y de resultados [T] https://costbench.com/software/financial-data-terminals/koyfin/free-plan/.
- Le falta a Faro: **dashboards configurables**, **calendario de earnings**, **screener** e historial de estimados.
- Precios: las fuentes de terceros se contradicen, NO VERIFICADO [T] https://www.capterra.com/p/207294/Koyfin/.
- Términos: NO VERIFICADO (dominio bloqueado). Solo inspiración; no scrapear [I].

### Finviz (propietario)
- Screener de 67 filtros, **heatmap**, backtests (en Elite) y alertas de precio, noticias, insiders, ratings y SEC [T] https://www.stockbrokers.com/review/tools/finviz , https://www.liberatedstocktrader.com/finviz-review/.
- Faro ya tiene heatmap y backtests. Le faltan el **screener por filtros** y las **alertas** (incluidas de insiders y de cambios de rating).
- Términos: según terceros, prohíben revender la información extraída [T] https://pypi.org/project/finviz/. El texto oficial no se pudo consultar: NO VERIFICADO. No usar scrapers de Finviz [I].

### TradingView (propietario, con piezas OSS)
- Pine Script, alertas en la nube (también por webhook), screeners de 50+ países, calendarios económico y de earnings, curvas de rendimiento [T] https://www.tradingview.com/gopro/. El plan gratis tiene 1 watchlist, 3 alertas de precio y 1 portafolio de 20 posiciones [T].
- Términos: prohíben recolección automatizada (scripts, scraping, robots) y los datos son *display-only* para uso personal [T, fragmento de https://in.tradingview.com/policies].
- **Lightweight Charts** es Apache-2.0 y exige atribución a TradingView (NOTICE más enlace, o la opción `attributionLogo`) [V] https://github.com/tradingview/lightweight-charts. Faro la puede usar en su gráfica de precios.

### Yahoo Finance (propietario)
- Portafolios, calendario de earnings, screeners, alertas e historial exportable de dividendos, splits y estados financieros en sus planes premium [T] https://finance.yahoo.com/about/plans/select-plan.
- Términos: prohíben robots, scrapers u otros medios automatizados "not provided by us" sin permiso previo [T, fragmento de los ToS de Yahoo] https://geonode.com/blog/how-to-scrape-yahoo.
- **Riesgo para Faro**: Faro usa `yfinance`, que extrae datos del sitio público. Eso choca con los ToS aunque el uso sea personal [I]. Conviene tener un proveedor de respaldo con API oficial; la registry de providers ya lo permite.

### Morningstar (propietario)
- **Portfolio X-Ray / Instant X-Ray**: mezcla acciones/bonos/efectivo, **style box** (valor/mezcla/crecimiento × tamaño), sectores, regiones y las top-10 posiciones subyacentes [T] https://portfolio.morningstar.com/instantxray/datadef.html.
- Términos: licencia de solo lectura para uso personal no comercial; prohíben crawling, scraping y extracción automatizada [V, fragmento de los ToS] https://global.morningstar.com/en-gb/policies/terms-use.
- Encaje: el style box y el X-ray se pueden reimplementar con fundamentales propios. Solo inspiración [I].

### Simply Wall St (propietario)
- **Snowflake**: 5 ejes (valuación, crecimiento futuro, desempeño pasado, salud financiera, dividendo) × 6 checks binarios cada uno [V] https://support.simplywall.st/hc/en-us/articles/360001740916.
- Faro tiene factores fundamentales para el ML, pero no un **score explicable** para la persona [I].
- Términos actualizados el 2026-08-02 [T] https://tostracker.app/document/st. La cláusula de scraping no se confirmó: NO VERIFICADO. La idea de "N checks binarios" no es protegible; replicar su marca o el visual exacto, sí [I].

### Portfolio Visualizer (propietario)
- Backtest de asignaciones, **Monte Carlo**, optimización (media-varianza, CVaR, Black-Litterman), **regresión de factores Fama-French/Carhart**, correlaciones y modelos tácticos [T] https://algotrading101.com/learn/portfolio-visualizer-guide/.
- Plan gratis limitado y planes Basic y Pro; los límites varían según la fuente [T] https://thecollegeinvestor.com/43889/portfolio-visualizer-review/.
- Faro ya usa PyPortfolioOpt. Le faltan **Monte Carlo de retiro**, **regresión de factores** y la **matriz de correlación** de holdings [I]. Términos: NO VERIFICADO.

### Empower, antes Personal Capital (propietario)
- Gratis: patrimonio neto agregado, **Retirement Planner con Monte Carlo**, **Investment Checkup** (asignación contra perfil de riesgo), **Fee Analyzer** y presupuesto [T] https://www.moneycrashers.com/personal-capital-review/.
- Le falta a Faro: un **analizador de comisiones** (TER de ETFs, comisiones del broker) y un **checkup de asignación** [I].
- Encaje: las ideas sí aplican. La agregación bancaria es de EE. UU. y no sirve en México [I]. Términos: NO VERIFICADO.

### Monarch Money (propietario)
- **Flex budgeting** (gastos fijos, flexibles y no mensuales), **rollover** de presupuesto, alertas y pronóstico de gasto, calendario de recurrentes y suscripciones, seguimiento de inversiones [T] https://www.moneycrashers.com/monarch-money-review/.
- Faro ya tiene 50/30/20, recurrentes y pronóstico. Le faltan el **rollover** y la categoría "no mensual" [I].
- Precio según terceros: USD 99.99 al año, sin plan gratis [T]. Términos: NO VERIFICADO.

### Kubera (propietario)
- Patrimonio neto de cualquier activo (inmuebles, vehículos, arte, préstamos a terceros, DeFi) y **Dead Man's Switch**: si no hay login en 45 días y no se responden los recordatorios, se envían los datos al beneficiario [T] https://www.finder.com/stock-trading/kubera-review.
- Le falta a Faro: activos ilíquidos con valuación manual y un **paquete de herencia o contingencia** (exportar a un beneficiario) [I].
- Precio según terceros: Essentials USD 249 al año [T] https://www.mezzi.com/blog/kubera-price-hike-worth-it-alternatives-compared. Términos: NO VERIFICADO.

### YNAB (propietario)
- 4 reglas: dar a cada peso un trabajo (*zero-based*), gastos reales (prorratear anuales), ajustar sobre la marcha, **Age of Money** (meta de 30 días o más) [T] https://www.nerdwallet.com/finance/learn/ynab-app-review.
- Le falta a Faro: el **Age of Money** como KPI y el **prorrateo de gastos anuales** a apartados mensuales [I].
- Precio según terceros: USD 14.99 al mes [T] https://www.thepennyhoarder.com/budgeting/ynab-review/. Términos: NO VERIFICADO. El método es una idea libre de usar [I].

---

### A2. Matriz de funciones

| herramienta | función | ¿la tenemos? | valor | esfuerzo | licencia/términos | enlace |
|---|---|---|---|---|---|---|
| Ghostfolio | Ledger de operaciones multi-cuenta (compras/ventas/dividendos) | no | alto | M | AGPL-3.0 | https://github.com/ghostfolio/ghostfolio |
| Ghostfolio | X-ray: reglas de concentración y diversificación | no | alto | S | AGPL-3.0 (idea) | https://openapps.pro/apps/ghostfolio |
| Ghostfolio | Calculadora FIRE con el portafolio real | no | medio | S | AGPL-3.0 (idea) | https://openapps.pro/apps/ghostfolio |
| Ghostfolio | Comparación contra benchmark | no | alto | S | AGPL-3.0 (idea) | https://openapps.pro/apps/ghostfolio |
| Ghostfolio | Watchlist en servidor | no | medio | S | AGPL-3.0 (idea) | https://openapps.pro/apps/ghostfolio |
| Ghostfolio | Servidor MCP / herramienta para LLM | no | medio | M | AGPL-3.0 | https://raw.githubusercontent.com/ghostfolio/ghostfolio/main/CHANGELOG.md |
| Ghostfolio | Asignación por sector, país y clase | parcial (heatmap) | alto | S | AGPL-3.0 (idea) | https://openapps.pro/apps/ghostfolio |
| Wealthfolio | TWR y MWR | no | alto | M | AGPL-3.0 | https://github.com/afadil/wealthfolio |
| Wealthfolio | Import CSV de actividades del broker | no | alto | M | AGPL-3.0 | https://github.com/afadil/wealthfolio |
| Wealthfolio | Reporte de ingresos (dividendos e intereses) | no | alto | S | AGPL-3.0 (idea) | https://docs.elfhosted.com/app/wealthfolio/ |
| Wealthfolio | Límites de aportación a cuentas fiscales (PPR) | no | medio | S | AGPL-3.0 (idea) | https://docs.elfhosted.com/app/wealthfolio/ |
| Wealthfolio | Monte Carlo para retiro | no | medio | M | AGPL-3.0 (idea) | https://docs.elfhosted.com/app/wealthfolio/ |
| Wealthfolio | Bloqueo de la app y cifrado de BD | no | medio | M | AGPL-3.0 | https://github.com/afadil/wealthfolio/releases |
| Wealthfolio | Add-ons / plugins | no | bajo | L | AGPL-3.0 | https://github.com/afadil/wealthfolio |
| Wealthfolio | Metas con asignación de cuentas | parcial (metas) | medio | S | AGPL-3.0 (idea) | https://github.com/afadil/wealthfolio |
| Portfolio Perf. | TTWROR e IRR (XIRR) | no | alto | M | EPL-1.0 | https://github.com/portfolio-performance/portfolio |
| Portfolio Perf. | Import de estados de cuenta en PDF | no | alto | L | EPL-1.0 | https://github.com/portfolio-performance/portfolio/releases |
| Portfolio Perf. | Rebalanceo contra asignación objetivo | no | alto | M | EPL-1.0 | https://github.com/portfolio-performance/portfolio |
| Portfolio Perf. | Taxonomías libres para clasificar activos | no | medio | M | EPL-1.0 | https://github.com/portfolio-performance/portfolio |
| Portfolio Perf. | Agrupar operaciones por lote | no | alto | M | EPL-1.0 | https://github.com/portfolio-performance/portfolio/releases |
| Sharesight | Reporte de ganancias de capital por año fiscal | no | alto | M | Propietario (idea) | https://apps.xero.com/us/app/sharesight |
| Sharesight | Contribution analysis | no | medio | M | Propietario (idea) | https://www.sharesight.com/blog/explore-your-portfolio-performance-with-the-contribution-analysis-report/ |
| Sharesight | Reporte multi-periodo | no | medio | S | Propietario (idea) | https://www.sharesight.com/blog/multi-period-report/ |
| Sharesight | Future income (dividendos proyectados) | no | medio | M | Propietario (idea) | https://www.sharesight.com/blog/7-reasons-to-upgrade-your-sharesight-account |
| Sharesight | Exposure: contenido de ETFs (look-through) | no | medio | L | Propietario (idea) | https://www.sharesight.com/blog/7-reasons-to-upgrade-your-sharesight-account |
| Sharesight | Eventos corporativos automáticos (splits) | no | alto | M | Propietario (idea) | https://apps.xero.com/us/app/sharesight |
| Koyfin | Dashboards configurables | no | medio | L | Propietario; NO VERIFICADO | https://costbench.com/software/financial-data-terminals/koyfin/free-plan/ |
| Koyfin | Calendario de earnings y económico | no | alto | S | Propietario (idea) | https://costbench.com/software/financial-data-terminals/koyfin/free-plan/ |
| Koyfin | Dashboards macro | sí (Panorama/Macro) | — | — | Propietario | https://costbench.com/software/financial-data-terminals/koyfin/free-plan/ |
| Koyfin | Estimados de analistas | parcial (consenso) | medio | M | Propietario (idea) | https://costbench.com/software/financial-data-terminals/koyfin/free-plan/ |
| Finviz | Screener por filtros | no | alto | M | Propietario; no scrapear | https://www.stockbrokers.com/review/tools/finviz |
| Finviz | Heatmap | sí | — | — | Propietario | https://www.liberatedstocktrader.com/finviz-review/ |
| Finviz | Backtest con benchmark SPY | parcial | medio | S | Propietario (idea) | https://www.liberatedstocktrader.com/finviz-review/ |
| Finviz | Alertas de insiders, ratings y SEC | no | medio | M | Propietario (idea) | https://www.liberatedstocktrader.com/finviz-review/ |
| TradingView | Alertas de precio e indicador (por webhook) | no | alto | S | ToS: sin scraping | https://www.tradingview.com/gopro/ |
| TradingView | Gráficas financieras (Lightweight Charts) | parcial | medio | S | Apache-2.0 + atribución | https://github.com/tradingview/lightweight-charts |
| TradingView | Curva de rendimientos | parcial (Macro) | bajo | S | Propietario (idea) | https://www.tradingview.com/gopro/ |
| Yahoo Finance | Historial de dividendos y splits | parcial (vía yfinance) | alto | S | ToS: sin automatización | https://finance.yahoo.com/about/plans/select-plan |
| Yahoo Finance | Calendario de earnings | no | alto | S | ToS: sin automatización | https://finance.yahoo.com/about/plans/select-plan |
| Morningstar | X-Ray de portafolio (mezcla, sectores, regiones) | no | alto | M | ToS: sin scraping | https://portfolio.morningstar.com/instantxray/datadef.html |
| Morningstar | Style box (valor/crecimiento × tamaño) | no | medio | S | Propietario (idea) | https://portfolio.morningstar.com/instantxray/datadef.html |
| Simply Wall St | Score explicable de 5 ejes × 6 checks | no | alto | M | Propietario (idea); ToS NO VERIFICADO | https://support.simplywall.st/hc/en-us/articles/360001740916 |
| Portfolio Vis. | Monte Carlo de supervivencia del portafolio | no | medio | M | Propietario (idea) | https://algotrading101.com/learn/portfolio-visualizer-guide/ |
| Portfolio Vis. | Regresión de factores Fama-French | no | medio | M | Propietario (idea) | https://algotrading101.com/learn/portfolio-visualizer-guide/ |
| Portfolio Vis. | Optimización CVaR y Black-Litterman | parcial (PyPortfolioOpt) | bajo | S | Propietario (idea) | https://algotrading101.com/learn/portfolio-visualizer-guide/ |
| Portfolio Vis. | Matriz de correlación de activos | no | medio | S | Propietario (idea) | https://algotrading101.com/learn/portfolio-visualizer-guide/ |
| Empower | Analizador de comisiones (TER y comisiones) | no | medio | S | Propietario (idea) | https://www.moneycrashers.com/personal-capital-review/ |
| Empower | Checkup de asignación contra perfil de riesgo | no | medio | S | Propietario (idea) | https://www.moneycrashers.com/personal-capital-review/ |
| Empower | Patrimonio neto agregado | sí | — | — | Propietario | https://www.moneycrashers.com/personal-capital-review/ |
| Monarch | Rollover de presupuesto | no | medio | S | Propietario (idea) | https://www.moneycrashers.com/monarch-money-review/ |
| Monarch | Calendario de recurrentes y suscripciones | parcial | medio | S | Propietario (idea) | https://www.moneycrashers.com/monarch-money-review/ |
| Monarch | Bucket de gastos "no mensuales" | no | medio | S | Propietario (idea) | https://www.moneycrashers.com/monarch-money-review/ |
| Kubera | Activos ilíquidos con valuación manual | parcial | medio | S | Propietario (idea) | https://www.finder.com/stock-trading/kubera-review |
| Kubera | Dead man's switch / paquete para beneficiario | no | medio | M | Propietario (idea) | https://www.finder.com/stock-trading/kubera-review |
| YNAB | Presupuesto zero-based | parcial (50/30/20) | medio | M | Método (idea libre) | https://www.nerdwallet.com/finance/learn/ynab-app-review |
| YNAB | Age of Money como KPI | no | medio | S | Método (idea libre) | https://www.nerdwallet.com/finance/learn/ynab-app-review |
| YNAB | Prorrateo de gastos anuales | no | medio | S | Método (idea libre) | https://www.nerdwallet.com/finance/learn/ynab-app-review |
| rotki | Reporte PnL fiscal con reglas contables configurables | no | medio | L | AGPL-3.0 | https://github.com/rotki/rotki |
| satcfdi | Importar y parsear CFDI (XML del SAT) | no | alto | M | MIT | https://github.com/SAT-CFDI/python-satcfdi |
| Finlynq | Costo por lote y ganancias realizadas por año fiscal | no | alto | M | AGPL-3.0 [T] | https://www.libhunt.com/r/finlynq |
| QuantStats | Tearsheet HTML (Sharpe, drawdown, rolling) | parcial (backtest) | medio | S | Apache-2.0 | https://github.com/ranaroussi/quantstats |
| (México) | Ganancia por venta de acciones extranjeras: costo promedio actualizado por INPC, ISR 10% | no | alto | M | Ley ISR (confirmar con contador) | https://expansion.mx/finanzas-personales/2026/03/09/ganancias-bolsa-de-valores-impuestos-asi-se-calcula-isr |

(63 filas; "—" significa que no aplica porque ya la tenemos.)

---

### A3. Proyectos OSS activos (2025-10 a 2026-10)

| proyecto | qué hace | licencia | última actividad comprobada | fuente |
|---|---|---|---|---|
| Ghostfolio | Tracker de patrimonio e inversiones | AGPL-3.0 [V] | 3.77.0, 2026-10-02 [V] | https://raw.githubusercontent.com/ghostfolio/ghostfolio/main/CHANGELOG.md |
| Wealthfolio | Tracker local-first (escritorio y Docker) | AGPL-3.0 [V] | v3.9.1, 2026-09-27 [V] | https://github.com/afadil/wealthfolio/releases |
| Portfolio Performance | App Java de escritorio: TTWROR/IRR e import de PDF | EPL-1.0 [V] | 0.87.0, 2026-08-16 [V] | https://github.com/portfolio-performance/portfolio/releases |
| rotki | Portafolio cripto y contabilidad fiscal, local | AGPL-3.0 (también hay licencia comercial) [V] | v1.44.1, 2026-10-02 [V] | https://github.com/rotki/rotki/releases |
| OpenBB | Plataforma de datos de mercado en Python | Apache-2.0 desde la V5; antes AGPL-3.0, según las notas de la release [V] | openbb-v5.0.0, 2026-09-30 [V] | https://github.com/OpenBB-finance/OpenBB/releases |
| Beancount | Contabilidad de doble entrada en texto | GPL-2.0-only [V] | 3.2.3, 2026-05-05 [V] | https://pypi.org/project/beancount/ |
| Fava | Interfaz web de Beancount | NO VERIFICADO (PyPI no cargó) | tag v1.30.16, 2026-08-18 [V] | https://github.com/beancount/fava/tags |
| Investbrain | Tracker multi-broker con chat LLM (Laravel + Vue) | CC-BY-NC-4.0 [V]; no es OSI y prohíbe uso comercial | commit del 2026-08-24 [V] | https://github.com/investbrainapp/investbrain |
| python-satcfdi | Genera y parsea CFDI, descarga masiva del SAT, DIOT | MIT [V] | commit del 2026-09-28 (bump de dependabot) [V] | https://github.com/SAT-CFDI/python-satcfdi |
| Riskfolio-Lib | Optimización de portafolio sobre CVXPY | BSD-3-Clause [V] | v7.3, "2026" (sin día) [T] | https://github.com/dcajasn/Riskfolio-Lib |
| QuantStats | Métricas y tearsheets de rendimiento | Apache-2.0 [V] | NO VERIFICADO: la página de releases mostró v0.0.86 con fecha 2024-09-27, posiblemente mal leída | https://github.com/ranaroussi/quantstats/releases |
| Lightweight Charts | Gráficas financieras en HTML5 | Apache-2.0 + atribución a TradingView [V] | NO VERIFICADO | https://github.com/tradingview/lightweight-charts |
| Finlynq | Finanzas personales con costo por lote, ganancias por año fiscal y servidor MCP | AGPL-3.0 [T] | NO VERIFICADO | https://www.libhunt.com/r/finlynq |
| LibreFolio | Tracker self-hosted multi-broker con FX | NO VERIFICADO | NO VERIFICADO | https://gitblind.noratr.app/Librefolio/LibreFolio |
| Wealth Manager (ptbsare) | Tracker en Python con calendario de dividendos | GPL-3.0 [T] | NO VERIFICADO | https://awesome.ecosyste.ms/projects/github.com%2Fptbsare%2Fwealth-manager |

---

### A4. Top 10 propuesto para Faro

1. **Ledger de inversiones**: posiciones, lotes, costo base, dividendos, splits y multi-moneda en MXN/USD. Es la base de casi todo lo demás. *Ideas*: Ghostfolio, Wealthfolio, Portfolio Performance. Esfuerzo M, valor alto.
2. **Rendimiento TWR + XIRR/MWR** por cuenta y total, con varios periodos. *Ideas*: Portfolio Performance (TTWROR/IRR), Sharesight (multi-period). Esfuerzo M.
3. **Comparación contra benchmark** (S&P 500, IPC, CETES, inflación MX). Faro ya tiene esas series en Panorama y Macro. Esfuerzo S.
4. **Reporte fiscal México**: ganancia por venta de acciones extranjeras con costo promedio actualizado por INPC y referencia al ISR del 10%, más dividendos y retenciones del año. Las reglas se deben validar con un contador [I]. Esfuerzo M, valor alto.
5. **Importadores**: CSV de brokers (GBM, IBKR, etc.) y **CFDI XML** con `satcfdi` (MIT) para alimentar el ledger personal. Esfuerzo M.
6. **X-ray y asignación**: sector, país, clase y concentración, con reglas configurables tipo Ghostfolio y style box tipo Morningstar. Esfuerzo S-M.
7. **Rebalanceo** contra asignación objetivo, aprovechando PyPortfolioOpt que ya existe. *Ideas*: Portfolio Performance, Wealthfolio. Esfuerzo M.
8. **Watchlist y alertas en servidor** (precio, cambio de rating de consenso, señal del modelo) enviadas por el bot de Telegram que ya existe. *Ideas*: TradingView, Finviz. Esfuerzo S.
9. **Calendario de dividendos y earnings** más **proyección de ingresos pasivos**. *Ideas*: Sharesight Future income, Yahoo y Koyfin. Esfuerzo S-M.
10. **Monte Carlo de retiro/FIRE** sobre el patrimonio real, con PPR y límites de aportación. *Ideas*: Empower, Wealthfolio, Ghostfolio, Portfolio Visualizer. Esfuerzo M.

Siguientes en la lista: un score explicable tipo Snowflake sobre los factores fundamentales que ya existen, rollover de presupuesto y Age of Money (Monarch, YNAB), analizador de comisiones (Empower) y un paquete para beneficiario (Kubera).

**Riesgo transversal [I]**: Faro depende de `yfinance`, que choca con los ToS de Yahoo, que prohíben medios automatizados (fuente citada arriba). Conviene conservar el respaldo con Stooq y Binance y valorar un proveedor con API oficial.

---

# Anexo B — Cripto y México


### Koinly (cripto, impuestos)
- **Formato CSV "universal" [V]:** columnas `Date, Sent Amount, Sent Currency, Received Amount, Received Currency, Fee Amount, Fee Currency, Net Worth Amount, Net Worth Currency, Label, Description, TxHash`. La fecha va en UTC con el formato `YYYY-MM-DD HH:mm:ss`. Sirve para depósitos, retiros y trades en el mismo archivo. Fuente: https://support.koinly.io/hc/en-us/articles/9914912005916-How-to-create-a-custom-CSV-file-with-your-data
- **¿Reporte para México? Parcial.** Koinly dice cubrir más de 100 países. México aparece como "soportado", pero solo los países con reglas propias (por ejemplo EE. UU., Canadá, Reino Unido, Francia e Irlanda) tienen formularios específicos. Para los demás, como México, se aplica FIFO, LIFO o HIFO genérico [V]. Fuentes: https://support.koinly.io/en/articles/9489962-which-countries-does-koinly-calculate-taxes-for y https://koinly.io/tax/
  - Un tercero afirma que Koinly genera un "reporte específico para México compatible con el SAT" [V-3º] (https://www.guiadetrader.com/blog/impuestos-crypto-mexico). Esto contradice lo anterior: **NO VERIFICADO**.
- **Términos de servicio:** están en https://koinly.io/legal/terms/, pero el texto sobre scraping no se pudo leer (**NO VERIFICADO**).
- **Qué hace mejor que Faro:** importa de cientos de exchanges, empareja transferencias entre cuentas propias y calcula el costo base.
- **Qué podemos reutilizar:** el CSV universal es un esquema simple de envío/recepción/comisión. Podemos adoptarlo como **formato de importación y exportación** de Faro para cripto, lo cual es interoperable y no copia código. El motor de Koinly queda solo como inspiración.

### CoinTracker
- **Países [V]:** genera reportes para más de 100 países, pero solo EE. UU., Canadá, Reino Unido, Alemania, Australia, España, Italia, Brasil y Portugal tienen formularios específicos. Para el resto, incluido México, entrega reportes de transacciones y ganancias de capital sin formulario local. Fuente: https://support.cointracker.io/hc/en-us/articles/5293978329873-Countries-Covered-by-CoinTracker-s-Tax-Reports
- **Formato CSV [V]:** 8 columnas en este orden: `Date, Received Quantity, Received Currency, Sent Quantity, Sent Currency, Fee Amount, Fee Currency, Tag`. La fecha va como `MM/DD/YYYY HH:MM:SS` y los encabezados deben coincidir exactamente. Fuente: https://support.cointracker.io/hc/en-us/articles/4413071299729-Convert-your-transaction-history-to-CoinTracker-CSV
- **Qué podemos reutilizar:** un segundo formato de exportación (mapeo trivial). Sus funciones de producto solo sirven como inspiración.

### Delta (de eToro)
- **Qué hace [V-3º]:** registra acciones, ETFs, cripto, fondos, forex y materias primas en una sola app, con sincronización de solo lectura a brokers y exchanges, captura manual e importación y exportación CSV. Fuentes: https://delta.app/en/features/link y https://support.delta.app/en/articles/9788147-how-to-import-and-export-your-data-to-csv (el formato del CSV no se pudo leer: **NO VERIFICADO**).
- **Planes:** las fuentes se contradicen (2 cuentas gratis frente a 10 activos gratis). Por eso los límites quedan como **NO VERIFICADOS**: https://benzinga.com/money/delta-crypto-tracker-by-etoro-review
- **Comparado con trackers de dividendos [V-3º]:** Delta se enfoca en portafolio, watchlist y alertas, no en un calendario de dividendos. Fuente: https://www.findmymoat.com/vs/delta-by-etoro-vs-divtracker
- **Encaje con Faro:** inspiración para una vista unificada de posiciones con P&L por activo. Faro ya tiene precios.

### Bitso
- **API [V]:** tiene endpoints privados `user_trades` y `ledger`, además de `ledger/trades`, `/fees`, `/fundings` y `/withdrawals`, con paginación por `marker`/`limit`/`sort`. Fuentes: https://docs.ccxt.com/docs/exchanges/bitso/implicit-api y https://docs.bitso.com/
- **Límites de uso [V]:** 60 solicitudes por minuto por IP en la API pública y 300 por minuto por cuenta en la privada (requiere KYC completo). Si se excede, hay un bloqueo de 1 minuto, y los bloqueos repetidos pueden llevar a uno de 24 h. Fuente: https://docs.bitso.com/bitso-api/docs/general-concepts
- **Exportación:** el historial está en bitso.com, en la sección de historial. CoinLedger y CoinTracking importan el CSV de Bitso [V] (https://support.bitso.com/hc/en-us/articles/4414985580436-How-to-see-my-transaction-history, https://coinledger.io/integrations/bitso). Las columnas del CSV no están documentadas en lo que encontré: **NO VERIFICADO**.
- **¿Emite documento fiscal?** Solo hay fuentes de terceros [V-3º], https://finantres.mx/bitso-informa-al-sat/:
  - Bitso reporta al SAT operaciones, saldos e ingresos por staking.
  - **No retiene impuestos** y entrega el historial como base para que el usuario determine sus obligaciones.
  - Para acciones, no reporta al SAT ni emite constancias.
  - **No encontré una "constancia fiscal anual" oficial de Bitso: NO VERIFICADO.**
  - Otro resultado menciona una retención del 20% en ventas de cripto; contradice lo anterior y **NO es confiable (NO VERIFICADO)**.
- **Reutilizable:** un cliente propio de la API de solo lectura, con llaves del propio usuario, para uso personal y local. Hay que revisar los términos completos antes de implementarlo.

### GBM+ (GBM)
- **Estados de cuenta y constancias [V-3º]:** se descargan desde la app en "Estados de cuenta y constancias", en PDF mensual por año. Fuente: https://finantres.mx/estado-de-cuenta-gbm/
- **Dividendos, según la FAQ de GBM [V]:**
  - Mercado mexicano: retención del 10% no acreditable sobre utilidades generadas desde 2014. Además se acredita el 30% que pagó la empresa en la declaración anual. Fuente: https://gbm.com/faqs/como-funcionan-los-impuestos-sobre-los-dividendos-en-trading-mx
  - SIC: retención en el extranjero (en EE. UU. 30%, o 10% con W-8BEN vigente) y después un 10% en México sobre el monto neto. GBM emite CFDI de sus inversiones en el SIC. Fuente: https://gbm.com/faqs/como-funcionan-los-impuestos-por-las-acciones-de-empresas-extranjeras-en-el-sic
- **Formato:** los documentos son PDF y CFDI (XML). No encontré un CSV público documentado: **NO VERIFICADO**.

### Kuspit
- **Qué ofrece [V-3º]:** acciones, CETES, ETFs, FIBRAs, fondos y SIC desde $100 MXN, con simulador. Comisiones de 0.20% por operación y 0.99% anual (cifras de un tercero; validar con Kuspit). Fuentes: https://www.rankia.mx/blog/casas-de-bolsa-de-mexico/7057514-analisis-kuspit-productos-comisiones-como-abrir-cuenta-alternativas y https://ahorraseguros.mx/blog/kuspit
- **Constancia fiscal o exportación:** no encontré información pública (**NO VERIFICADO**).

### Cetesdirecto
- **Constancia anual de retenciones [V-3º]:** se consulta en la web de Cetesdirecto de febrero al 31 de diciembre y corresponde al ejercicio anterior. Una impresa se pide al CAT con al menos 20 días hábiles de anticipación. Fuente: https://www.rankia.mx/foros/bancos-cajas/temas/3283864-donde-puedo-descargar-constancia-cetesdirecto
- **Formato:** PDF. No hay API pública de cuenta (**NO VERIFICADO**).

### Fintual México
- No encontré documentación pública sobre su constancia fiscal: **NO VERIFICADO**.
- **Contexto general de fondos [V-3º]:**
  - En fondos de deuda se retiene provisionalmente 0.90% anual sobre el capital en 2026.
  - En renta variable se paga 10% sobre la ganancia en la declaración anual.
  - La constancia de rendimientos y retenciones se entrega a más tardar el 15 de febrero.
  - Fuente: https://www.rankia.mx/blog/fondos-de-inversion-mexico/6442949-impuestos-fondos-inversion

### Actinver (e-Actinver)
- **Qué ofrece la app [V]:** token digital, transferencias, fondos de inversión, consulta de estados de cuenta y pago de servicios. Fuente: https://apps.apple.com/mx/app/e-actinver/id1022985486
- **Constancias o exportación:** no encontré información pública (**NO VERIFICADO**).

### FIBRAs: AMEFIBRA, BMV y BIVA
- **Avisos de derechos en la BMV [V]:** son PDFs públicos (`bmv.com.mx/docs-pub/fibderec/...`) con la distribución por CBFI y la separación entre **resultado fiscal** y **reembolso de capital**. Ejemplo: https://www.bmv.com.mx/docs-pub/fibderec/fibderec_1528565_1.pdf (un aviso de FUNO con pago el 9 de febrero de 2026, según el extracto).
- **Tratamiento fiscal:**
  - Los reembolsos de capital no se consideran distribución de resultado fiscal (art. 188 LISR) y no tienen retención [V]. Fuente: https://www.bmv.com.mx/docs-pub/fibderec/fibderec_992150_1.pdf
  - Se retiene 30% sobre el resultado fiscal distribuido a personas físicas residentes [V-3º]. Fuente: https://www.contadigital.mx/posts/fideicomiso-inmobilario-fibras
- **Términos de uso de la BMV [V]:** "Queda expresamente prohibido copiar, enmarcar, analizar (parsing)… o cualquier otra acción que reproduzca total o parcialmente el contenido del Sitio", salvo autorización por escrito. Fuente: https://www.bmv.com.mx/es/aviso-legal
  - **Consecuencia: no hacer scraping automático.** Lo seguro es capturar manualmente o subir el PDF que el usuario descargó (inferencia, NO VERIFICADO legalmente).
  - La BMV vende web services con datos con 20 minutos de retraso [V]: https://www.bmv.com.mx/es/productos-de-informacion/web-services
- **AMEFIBRA y BIVA:** la búsqueda no devolvió información sobre datos públicos o API (**NO VERIFICADO**).

### SIC y documentos fiscales de los brokers
- **Art. 129 LISR [V-3º]:**
  - Se paga 10% definitivo sobre la ganancia anual por vender acciones en bolsa, incluidas las extranjeras del SIC.
  - El costo promedio se calcula por emisora.
  - Las pérdidas solo se compensan contra ganancias del mismo tipo en los 10 ejercicios siguientes.
  - Fuentes: https://sdv.com.mx/compendio/ley-isr/articulo-129/ y https://idconline.mx/fiscal-contable/2025/04/25/anual-2024-declaracion-por-venta-de-acciones-en-bolsa
- **CFDI de Retenciones e Información de Pagos [V-3º]:** sus complementos incluyen **Enajenación de acciones, Dividendos, Intereses, Arrendamiento en fideicomiso (FIBRAs) y Sector Financiero**. Fuente: https://www.edifact.com.mx/masinfo/cfdi-de-retenciones-e-informacion-de-pagos
  - **Inferencia (NO VERIFICADO):** la "constancia fiscal anual" de cada broker equivale a estos CFDI de retenciones (XML) más un PDF, con intereses nominales y reales, ISR retenido, dividendos y la ganancia o pérdida del art. 129.
  - **El XML es la fuente parseable y estándar**, la mejor candidata para un importador en Faro.
- **Intereses reales [V-3º]:** las instituciones informan intereses nominales, reales y retenciones; en la declaración anual se acumula el interés real. Fuente: https://contadormx.com/inversiones-en-la-declaracion-anual-de-personas-fisicas-aspectos-a-considerar/
- **INPC [V]:** la API SIE de Banxico, con token gratuito, ofrece la serie `SP1` (INPC mensual), necesaria para la actualización de costos y el interés real. Fuente: https://cran.r-project.org/web/packages/siebanxicor/refman/siebanxicor.html

---

### B2. Matriz

| herramienta | función | ¿la tenemos? | valor | esfuerzo | licencia/términos | enlace |
|---|---|---|---|---|---|---|
| Koinly | Importar CSV universal de cripto | no | alto | S | formato público; reutilizar el esquema | support.koinly.io/hc/en-us/articles/9914912005916 |
| Koinly | Exportar a CSV universal (para el contador o Koinly) | no | medio | S | idem | idem |
| Koinly | Costo base FIFO/LIFO/HIFO por lote | no | alto | M | solo inspiración | support.koinly.io/en/articles/9489962 |
| Koinly | Emparejar transferencias entre cuentas propias | no | medio | M | solo inspiración | idem |
| Koinly | Reporte fiscal específico de México | no (y en Koinly no está claro) | — | — | NO VERIFICADO | guiadetrader.com/blog/impuestos-crypto-mexico |
| CoinTracker | Importar y exportar su CSV de 8 columnas | no | medio | S | formato público | support.cointracker.io/hc/en-us/articles/4413071299729 |
| CoinTracker | Reporte de ganancias de capital para países sin formulario | no | alto | M | inspiración | support.cointracker.io/hc/en-us/articles/5293978329873 |
| Delta | Portafolio unificado acciones + cripto con P&L | parcial (precios sí, posiciones no) | alto | M | inspiración | delta.app/en/features/link |
| Delta | Alertas de precio | NO VERIFICADO en Faro | medio | S | inspiración | benzinga.com/money/delta-crypto-tracker-by-etoro-review |
| Delta | Importar y exportar CSV como respaldo | no | medio | S | formato no leído | support.delta.app/en/articles/9788147 |
| Bitso | Sincronizar `user_trades` y `ledger` por API de solo lectura | no | alto | M | API pública documentada; límite de 300 RPM; revisar términos | docs.bitso.com |
| Bitso | Importar CSV del historial | no | alto | S | columnas NO VERIFICADO | support.bitso.com/hc/en-us/articles/4414985580436 |
| Bitso | Reporte anual propio de cripto (Bitso no retiene) | no | alto | M | — | finantres.mx/bitso-informa-al-sat/ |
| GBM | Importar CFDI de retenciones XML (SIC y dividendos) | no | alto | M | estándar SAT | gbm.com/faqs/como-funcionan-los-impuestos-por-las-acciones-de-empresas-extranjeras-en-el-sic |
| GBM | Dividendos MX con 10% de retención y acreditamiento del 30% | no | alto | M | regla pública | gbm.com/faqs/como-funcionan-los-impuestos-sobre-los-dividendos-en-trading-mx |
| GBM | Dividendos SIC con retención extranjera (W-8BEN) + 10% en MX | no | alto | M | regla pública | idem SIC |
| GBM | Repositorio de estados de cuenta y constancias en PDF | no | medio | S | archivos del usuario | finantres.mx/estado-de-cuenta-gbm/ |
| Kuspit | Ledger multi-instrumento (acciones, CETES, ETF, FIBRA, SIC) | no | alto | L | inspiración | rankia.mx/blog/casas-de-bolsa-de-mexico/7057514-... |
| Kuspit | Simulador de inversión | parcial (paper trading) | bajo | — | — | idem |
| Cetesdirecto | Posiciones de CETES/BONDDIA con vencimientos | parcial (solo tasa CETES en Macro) | alto | M | captura manual | rankia.mx/foros/.../3283864-... |
| Cetesdirecto | Archivar constancia anual y registrar ISR retenido | no | medio | S | — | idem |
| Fintual | Fondos con retención de 0.90% sobre capital y 10% en renta variable | no | medio | M | regla pública (fuente de tercero) | rankia.mx/blog/fondos-de-inversion-mexico/6442949-... |
| Actinver | Estados de cuenta multi-producto | no | bajo | — | inspiración | apps.apple.com/mx/app/e-actinver/id1022985486 |
| BMV | Distribuciones FIBRA: resultado fiscal vs reembolso de capital | no | alto | M | **prohibido el scraping**; captura manual o PDF del usuario | bmv.com.mx/es/aviso-legal |
| BMV | Calendario de pagos de FIBRAs | no | medio | M | idem | bmv.com.mx/docs-pub/fibderec/fibderec_1528565_1.pdf |
| BMV | Ajuste del costo de CBFIs por reembolsos de capital | no | alto | M | regla art. 188 LISR | bmv.com.mx/docs-pub/fibderec/fibderec_992150_1.pdf |
| BMV | Web services de mercado | parcial (Faro usa yfinance) | bajo | L | de pago o por licencia | bmv.com.mx/es/productos-de-informacion/web-services |
| SAT/LISR | Ganancia anual art. 129 con costo promedio, 10% y arrastre de pérdidas 10 años | no | alto | M | ley pública | sdv.com.mx/compendio/ley-isr/articulo-129/ |
| SAT | Parser genérico de CFDI de Retenciones (intereses, dividendos, enajenación, arrendamiento en fideicomiso) | no | alto | M | estándar público SAT | edifact.com.mx/masinfo/cfdi-de-retenciones-e-informacion-de-pagos |
| SAT | Resumen de "interés real" anual | no | medio | M | ley pública | contadormx.com/inversiones-en-la-declaracion-anual-... |
| Banxico | Serie INPC SP1 para actualizar costos | parcial (Macro tiene inflación; fuente NO VERIFICADA) | alto | S | API con token gratuito | cran.r-project.org/web/packages/siebanxicor |

---

### B3. Top 8 funciones propuestas para Faro

1. **Ledger de inversiones por lotes** (acciones BMV y SIC, ETFs, FIBRAs, cripto): compras, ventas, comisiones, costo promedio por emisora (lo que exige el art. 129) y FIFO opcional para cripto. Es la base de todo lo demás. Esfuerzo **L**.
2. **Importador de CFDI de Retenciones (XML)** con los complementos Enajenación de acciones, Dividendos, Intereses y Arrendamiento en fideicomiso. Es estándar, parseable localmente y lo emiten todos los brokers. Esfuerzo **M**.
3. **Reporte anual estilo SAT**: ganancia o pérdida del art. 129 al 10%, dividendos MX y SIC con retenciones acreditables o definitivas, intereses reales e ISR retenido, para conciliar contra la constancia del broker. Esfuerzo **M**.
4. **Cripto: importar y exportar CSV** en formatos Koinly universal y CoinTracker, más el CSV de Bitso. Esfuerzo **S**.
5. **Sincronización opcional de solo lectura con la API de Bitso** (`ledger`, `user_trades`), con las llaves guardadas en `.env` y respetando los 300 RPM. Esfuerzo **M**.
6. **Distribuciones de FIBRAs** separadas en resultado fiscal (retención del 30%) y reembolso de capital (reduce el costo del CBFI), con captura manual o parseo del PDF que el usuario descarga. Sin scraping de bmv.com.mx por su aviso legal. Esfuerzo **M**.
7. **Dividendos y calendario de ingresos pasivos** (acciones, SIC, FIBRAs, CETES), integrado al ledger personal en MXN con tipo de cambio. Esfuerzo **M**.
8. **Bóveda fiscal anual**: guardar PDF y XML de constancias y estados de cuenta por broker y año (GBM, Cetesdirecto, Kuspit, Actinver, Fintual), con checklist de "¿ya llegó la constancia?" (fecha límite del 15 de febrero según una fuente de tercero). Agregar el INPC de Banxico SIE (`SP1`) para la actualización de costos. Esfuerzo **S**.

**Advertencia general:** ningún cálculo fiscal de Faro debe presentarse como asesoría. Las reglas (tasas, acreditamiento, arrastre de pérdidas) vienen de fuentes de terceros y deben validarse con la LISR vigente y con un contador.
