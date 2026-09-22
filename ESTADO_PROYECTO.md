# Estado del Proyecto

Ultima revision operativa: 2026-09-02.

Faro ya cuenta con una base funcional para investigar, entrenar, evaluar y monitorear modelos de decision de inversion. El sistema no promete precision perfecta ni debe operar capital real sin una etapa prolongada de validacion; esta construido para maximizar evidencia, trazabilidad y control de riesgo antes de tomar decisiones.

## Capacidades Implementadas

| Bloque | Estado |
| --- | --- |
| Persistencia | PostgreSQL local como unica fuente (Supabase eliminado por completo: base, auth y storage). Modelos `.joblib` en `models/` local. |
| Ingestion de mercado | Jobs para descargar OHLCV, normalizar precios y cargar PostgreSQL local. Universo ampliado al S&P 100 (101 tickers) con snapshot fechado y disclosure de sesgo de supervivencia. |
| Datasets ML | Materializacion de features tecnicos y labels por activo. |
| Entrenamiento | Modelos candidatos, evaluacion walk-forward, scopes global / por clase / por ticker, con topes medidos (`max_auto_targets`, `max_global_scope_assets`). |
| Promocion | Seleccion de candidatos y registro de `model_runs` versionados; no promueve por inercia ni sin mejorar al incumbente. |
| Reentrenamiento | Job operativo para evaluar candidatos, promover modelos aprobados y normalizar el artefacto en `models/`. |
| Inferencia | Job operativo para generar predicciones latest desde modelos promovidos. |
| Riesgo | Motor de riesgo con perfiles default, por clase de activo y por ticker (por scope, sin usuarios). |
| Feedback | Evaluacion de predicciones previas contra retornos observados. |
| Backtesting | Backtests persistidos y comparables por instrumento/modelo. |
| Paper trading | Simulaciones persistidas con curva de equity, eventos y comparativo. |
| Salud operativa | Endpoint y panel para verificar API, base de datos, esquema requerido y alertas por activo. |
| Endurecimiento API | CORS acotado (origenes explicitos, credenciales solo con lista explicita), rate limiting per-IP en `/api/*`, logging estructurado de fallos que caen a modo demo. |
| Notificaciones | Bot de Telegram (long-polling) para fallo de job, cambio de senal, degradacion de modelo y datos vencidos, con cooldown y dedupe. Webhook generico opcional. |
| Scheduler | `ops/run_local_scheduler` orquestado por el Programador de Tareas de Windows (reemplaza el GitHub Actions que corria contra Supabase). |
| Analisis fundamental | Feature set opcional `fundamental_v1` (Piotroski F-Score, Altman Z-Score, Novy-Marx gross profitability) sobre hechos XBRL de SEC EDGAR, calculado punto-en-el-tiempo por `filed_date` (nunca `period_end`). Solo acciones; ingestion standalone y apagada por defecto (no enganchada al job diario). Ver [Analisis Fundamental](README.md#analisis-fundamental) en el README. |
| SDD | OpenSpec para planificar mejoras profesionales por bloques; base compartida de inteligencia financiera archivada. |
| Frontend | Consola React decision-first: switcher de activos con command palette, tabs de evidencia, gauge de confianza con umbral, distribucion de probabilidad, sparkline de senales, drawer de perfil de riesgo, tablas unificadas, estados vacios que ensenan, pasada de accesibilidad (WCAG 2.2), auto-refresh. |
| Calidad | Suite backend contra PostgreSQL real (~350 tests). Frontend con vitest + testing-library sobre los primitivos nuevos. |

## Flujo Operativo Recomendado

1. Aplicar migraciones pendientes: `py -3.14 -m db.migrate`.
2. Verificar el esquema con `py -3.14 -m collector.schema_check`.
3. Cargar o actualizar historicos con `py -3.14 -m collector.run_market_data_job`.
4. Entrenar y evaluar candidatos con validacion walk-forward.
5. Promover solo modelos con evidencia out-of-sample superior a baselines.
6. Ejecutar `py -3.14 -m brain.run_inference_job` para guardar predicciones.
7. Ejecutar `py -3.14 -m brain.run_paper_trading_job` para medir comportamiento simulado.
8. Revisar `/api/feedback/{ticker}`, `/api/paper-trading-runs/{ticker}` y `/api/health`.
9. Reentrenar cuando el feedback muestre degradacion, bajo acierto o cambios de regimen.

En vez de correr los pasos sueltos, el ciclo diario/semanal se ejecuta con
`py -3.14 -m ops.run_local_scheduler --job {full|full_retrain}` (registrado como
tarea de Windows via `ops/register_local_jobs.ps1`).

## Criterios Antes de Produccion Real

- Mantener paper trading activo durante varios ciclos de mercado, idealmente 6 a 12 meses segun frecuencia operativa.
- Comparar modelos globales, por clase de activo y por ticker antes de fijar una estrategia.
- Medir retorno neto con fees, slippage, drawdown, exposicion y estabilidad, no solo accuracy.
- Confirmar el circuito de alertas de Telegram de punta a punta (fallo de job, datos vencidos, degradacion).
- Fijar `ALLOW_DEMO_FALLBACK=false` y `API_CORS_ORIGINS` explicitos en produccion.
- Integrar broker solo despues de validar controles de riesgo, limites y revision humana.
- Mantener secretos fuera del repositorio (`.env` gitignoreado) y rotar credenciales si alguna vez fueron expuestas.

## Comandos de Verificacion

```bash
py -3.14 -m collector.schema_check
py -3.14 -m pytest -q
cd ui && npm run lint && npm run build && npm test && npm audit
```

## Riesgos Conocidos

- El rendimiento historico no garantiza rendimiento futuro.
- La individualizacion por activo puede mejorar especializacion, pero tambien aumenta riesgo de overfitting si hay pocos datos.
- Aplicar la membresia actual del S&P 100 a historia 2020-2026 introduce sesgo de supervivencia; esta anotado en el snapshot y expuesto en `/api/universe`.
- Criptomonedas y acciones tienen microestructuras distintas; deben evaluarse con costos, horarios, liquidez y volatilidad propios.
- El sistema todavia no ejecuta ordenes reales. Esa ausencia es intencional hasta cerrar validacion, monitoreo y gobierno de riesgo.
- `fundamental_v1`: un hueco en el historico de `prices` alrededor de una fecha de filing SEC ensancha el lag efectivo (nunca lo acorta) y el primer ano XBRL de un filer no produce F-Score de Piotroski (falta el ano fiscal previo) hasta el segundo `FY` filed. Ambos son comportamiento esperado y documentado, no un defecto. Una comparacion formal `fundamental_v1` vs `technical_v2` (walk-forward, mismo subconjunto de acciones) queda como seguimiento, no como bloqueo.
- `fundamental_v1` cubre ~66 de las 101 acciones del S&P 100. Los ~35 restantes quedan sin filas por diferencias estructurales de reporte: financieras (bancos sin balance clasificado: no existen `AssetsCurrent`/`LiabilitiesCurrent`), empresas que solo etiquetan el costo de ventas por trimestre (no `fp='FY'`), y utilities sin tag de COGS. No se arregla ampliando las cadenas de tags; requiere variantes de factor por sector o agregacion TTM. Detalle y seguimientos en `openspec/changes/archive/2026-09-04-fundamental-analysis/coverage-reconciliation.md`. Aparte: el mapeo oficial de SEC apunta `XOM` a un CIK post-reorganizacion sin historial; necesita una lista manual de overrides ticker->CIK.
