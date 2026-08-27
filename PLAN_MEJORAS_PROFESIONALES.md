# Plan de Mejoras Profesionales

Revision: 2026-07-11.

Este plan convierte el estado actual de IA Inversiones en una hoja de ruta profesional para aumentar calidad, confiabilidad y capacidad de aprendizaje del sistema. La idea central no es que el modelo "aprenda solo" sin control, sino construir un ciclo MLOps donde cada prediccion guardada se evalua contra el mercado real, alimenta monitoreo, dispara reentrenamiento y solo promueve modelos que demuestran mejora contra el vigente.

## Resumen Ejecutivo

El proyecto ya tiene una base fuerte: PostgreSQL local, FastAPI, React, ingesta de mercado, features, labels, backtesting, paper trading, reentrenamiento controlado y un scheduler local (Programador de Tareas de Windows). La siguiente etapa debe enfocarse en cuatro cosas:

1. Calidad de datos y trazabilidad.
2. Evaluacion y promocion de modelos con guardrails mas estrictos.
3. Monitoreo real de drift, degradacion, costos y comportamiento en paper trading.
4. Operacion segura antes de cualquier broker real.

## Estado Actual

| Area | Estado actual | Nivel |
| --- | --- | --- |
| Datos | Binance, yfinance, Stooq, normalizacion OHLCV, PostgreSQL local. | Bueno para MVP |
| Features y labels | `technical_v2`, triple barrier/fixed horizon, materializacion diaria. | Bueno |
| Modelos | Logistic Regression, Random Forest, Extra Trees, HistGradientBoosting. | Solido, mejorable |
| Evaluacion | Walk-forward, backtesting, baselines, costos, slippage. | Solido |
| Promocion | Candidatos aprobados y comparacion contra incumbent. | Muy buen inicio |
| Paper trading | Persistido en PostgreSQL local con eventos y equity. | Bueno |
| Monitoreo | Health, alerts, feedback, webhook y Telegram opcionales. | Basico |
| Seguridad | Secretos fuera del repo (`.env` local); Postgres solo en `localhost`, sin RLS necesario. | Bueno |
| Frontend | Dashboard operativo con riesgo, feedback, paper trading y sistema. | Bueno |
| Despliegue | Local (PostgreSQL + Programador de Tareas de Windows); ver `PLAN_DESPLIEGUE.md`. | Funcional |

## Principio de Aprendizaje Continuo

El modelo debe mejorar con el tiempo mediante un ciclo supervisado y auditable:

1. Guardar cada prediccion antes de conocer el resultado.
2. Esperar el horizonte configurado.
3. Materializar el resultado real como label.
4. Comparar prediccion vs resultado observado.
5. Medir acierto, retorno neto, drawdown, profit factor, calibracion y drift.
6. Reentrenar candidatos con datos nuevos.
7. Rechazar candidatos que no superen al modelo vigente.
8. Promover solo cuando hay mejora fuera de muestra y sin romper controles de riesgo.

Esto evita una trampa comun: entrenar directamente sobre "si el modelo acerto o fallo" como si esa fuera la verdad principal. El feedback debe servir para monitoreo, ponderacion y criterios de promocion; la verdad de entrenamiento sigue viniendo del mercado observado.

## Investigacion Aplicada

| Tema | Hallazgo | Decision recomendada |
| --- | --- | --- |
| Validacion temporal | `TimeSeriesSplit` de scikit-learn esta pensado para datos ordenados temporalmente y evita evaluar con datos futuros. | Mantener walk-forward, agregar embargo/gap mas visible y reporte de leakage. |
| Drift y monitoreo | Evidently permite evaluar drift de distribucion y monitorear datos/modelos. | Agregar reportes de drift por activo y feature set. |
| Registro de modelos | MLflow Model Registry maneja modelos versionados, aliases, tags y metadata. | Mantener Supabase como registry operativo o integrar MLflow si crece la complejidad. |
| Modelos tabulares | LightGBM y XGBoost son fuertes para datos tabulares y boosting eficiente. | Agregarlos como candidatos opcionales, no reemplazar todo. |
| HPO | Optuna permite optimizacion automatica de hiperparametros con espacios dinamicos. | Agregar HPO acotado por tiempo y presupuesto para candidatos finalistas. |
| Observabilidad | OpenTelemetry estandariza trazas, metricas y logs. | Instrumentar API/jobs cuando el sistema tenga trafico real. |
| Seguridad CI/CD | GitHub recomienda hardening de workflows y minimo privilegio. | Agregar CI completo, ambientes protegidos y reglas para secretos. |
| RLS | Supabase recomienda RLS como defensa en profundidad. | Mantener RLS y auditar politicas con cada nueva tabla. |
| Riesgo IA | NIST AI RMF enfatiza gobernanza, medicion y gestion del riesgo. | Crear politica de promocion, rollback, auditoria y aprobacion humana. |
| Paper trading externo | Alpaca ofrece paper trading por API para simular actividad y balance. | Integrarlo despues de consolidar paper trading interno. |

## Bloques de Implementacion

### Bloque 1 - Higiene Operativa y Documental

Objetivo: cerrar inconsistencias y que el repo se vea listo para revision profesional.

Tareas:

- Actualizar `PLAN_DESPLIEGUE.md` para quitar pendientes ya resueltos.
- Actualizar fecha de `ESTADO_PROYECTO.md`.
- Agregar `CHANGELOG.md`.
- Agregar `CONTRIBUTING.md` con flujo local, tests y seguridad de secretos.
- Agregar `SECURITY.md` con politica de reporte y rotacion.
- Agregar badges en `README.md` para tests/deploy cuando existan workflows.

Criterio de salida:

- Documentacion sin pendientes obsoletos.
- Nuevo colaborador puede entender arquitectura, ejecutar tests y no filtrar secretos.

### Bloque 2 - CI Profesional

Objetivo: que cada push valide backend, frontend, formato y seguridad basica.

Tareas:

- Crear workflow `ci.yml` para `pytest`, schema-free unit tests, frontend lint/build.
- Separar CI de jobs operativos para no depender de Supabase en cada PR.
- Agregar `pip-audit` o `safety` como job informativo.
- Agregar `npm audit` con nivel de severidad definido.
- Agregar Dependabot para Python, npm y GitHub Actions.
- Evaluar pinning de acciones por SHA si el repo se vuelve sensible.

Criterio de salida:

- Pull requests fallan si rompen tests o build.
- Dependencias vulnerables quedan visibles antes de deploy.

### Bloque 3 - Calidad de Datos

Objetivo: evitar entrenar con basura silenciosa.

Tareas:

- Crear tabla `data_quality_checks`.
- Validar duplicados, gaps, volumen nulo, OHLC incoherente, precios cero/negativos.
- Guardar score de calidad por activo, proveedor y fecha.
- Agregar endpoint `/api/data-quality/{ticker}`.
- Mostrar panel de calidad de datos en frontend.
- Implementar fallback de proveedor por activo: Binance, yfinance, Stooq, y futuro proveedor premium.
- Guardar snapshots crudos en formato Parquet o Supabase Storage para auditoria.

Criterio de salida:

- Un entrenamiento puede bloquearse si la calidad de datos cae bajo umbral.
- Cada prediccion puede rastrearse hasta fuente y ventana de datos.

### Bloque 4 - Calendario de Mercado y Corporate Actions

Objetivo: mejorar acciones y ETFs, donde horarios, splits y dividendos importan.

Tareas:

- Agregar calendario de mercado para acciones.
- Registrar dias no operativos y horarios.
- Ajustar ingesta para splits/dividendos cuando el proveedor lo soporte.
- Separar reglas de crypto 24/7 vs acciones con sesiones.
- Agregar validaciones para datos de acciones fuera de horario.

Criterio de salida:

- Backtests de acciones usan datos coherentes con sesiones reales.
- Alertas no marcan como atrasado un activo cerrado por mercado.

### Bloque 5 - Modelos Candidatos Avanzados

Objetivo: aumentar capacidad predictiva sin sacrificar control.

Tareas:

- Agregar LightGBM como candidato opcional.
- Agregar XGBoost como candidato opcional.
- Mantener modelos actuales como baselines.
- Agregar calibracion de probabilidades cuando aplique.
- Agregar ensambles simples: voto ponderado o blend por score out-of-sample.
- Agregar importancia de features por modelo.

Criterio de salida:

- Los modelos nuevos compiten en la misma matriz.
- Ningun modelo nuevo puede promoverse si no mejora al incumbent.

### Bloque 6 - Optimizacion de Hiperparametros

Objetivo: buscar mejores parametros con presupuesto controlado.

Tareas:

- Integrar Optuna para candidatos finalistas.
- Definir presupuesto por activo: numero de trials, tiempo maximo, seed.
- Guardar trials en Supabase o artifact JSON.
- Evitar HPO en cada corrida diaria.
- Ejecutar HPO solo en `full_retrain` semanal o manual.

Criterio de salida:

- Cada modelo promovido registra parametros, trials y razon de seleccion.
- La optimizacion no consume recursos sin limite.

### Bloque 7 - Evaluacion Mas Estricta

Objetivo: medir utilidad financiera, no solo accuracy.

Tareas:

- Agregar metricas: Sharpe, Sortino, Calmar, turnover, exposure, hit rate por regimen.
- Agregar reporte de estabilidad por fold y por periodo.
- Agregar holdout final congelado por activo.
- Agregar prueba contra baselines: no trade, buy and hold, always buy, always sell.
- Agregar slippage variable por asset class.
- Agregar sensibilidad a fees.

Criterio de salida:

- Promocion exige retorno neto, drawdown aceptable, muestra minima y estabilidad.
- Un modelo con alta accuracy pero mal retorno no se promueve.

### Bloque 8 - Drift y Monitoreo de Modelo

Objetivo: detectar cuando el mercado cambia y el modelo deja de ser confiable.

Tareas:

- Integrar Evidently para data drift por features.
- Guardar reportes en `model_monitoring_reports`.
- Crear alertas por drift alto, accuracy bajo, retorno medio negativo y drawdown simulado.
- Mostrar estado de drift en frontend.
- Usar drift como disparador de reentrenamiento o bloqueo de senales.

Criterio de salida:

- El sistema puede decir "modelo degradado" antes de seguir recomendando con confianza falsa.

### Bloque 9 - Registry y Auditoria de Modelos

Objetivo: hacer que cada modelo sea auditable como producto.

Tareas:

- Crear `model_cards` o extender `model_runs`.
- Registrar dataset window, features, labels, parametros, metricas, artifact hash.
- Agregar estado: candidate, shadow, promoted, archived, rejected.
- Agregar razon de promocion/rechazo.
- Agregar rollback al ultimo modelo promovido sano.
- Evaluar MLflow si Supabase se queda corto para lifecycle complejo.

Criterio de salida:

- Cualquier decision del dashboard puede rastrearse al modelo, datos y reglas usados.

### Bloque 10 - Shadow Mode y Canary

Objetivo: probar modelos nuevos sin afectar la decision principal.

Tareas:

- Ejecutar candidatos en modo shadow.
- Guardar predicciones shadow sin mostrarlas como recomendacion final.
- Comparar shadow vs promoted durante N dias.
- Promover solo si shadow gana con significancia operativa.
- Agregar panel de comparacion promoted vs shadow.

Criterio de salida:

- El modelo nuevo demuestra valor con datos vivos antes de reemplazar al vigente.

### Bloque 11 - Producto y Frontend Profesional

Objetivo: convertir el dashboard en consola de decision clara.

Tareas:

- Agregar vista "Modelo": version activa, incumbent, shadow, metricas y fecha.
- Agregar vista "Datos": calidad, proveedor, gaps y ultima ingesta.
- Agregar vista "Operacion": ultimos workflows, estado, artifacts y alertas.
- Agregar export CSV/JSON de paper trading y feedback.
- Agregar tooltips de riesgo y explicaciones por feature.
- Agregar skeleton/loading/error states mas finos.
- Agregar tests de frontend con Playwright o Vitest.

Criterio de salida:

- Un usuario entiende por que la senal es BUY/SELL/HOLD y si debe confiar o esperar.

### Bloque 12 - Observabilidad de Backend y Jobs

Objetivo: resolver fallos rapido en produccion.

Tareas:

- Estandarizar logs JSON.
- Agregar request IDs.
- Instrumentar FastAPI y jobs con OpenTelemetry.
- Medir latencia de endpoints, errores por proveedor, duracion de jobs.
- Guardar resumen de workflows en Supabase.
- Enviar notificaciones reales a Slack, Discord, Teams o endpoint propio.

Criterio de salida:

- Si falla ingesta, inferencia o Supabase, queda claro donde y por que.

### Bloque 13 - Seguridad y Gobierno

Objetivo: reducir riesgo de operar con datos, claves y modelos.

Tareas:

- Auditar RLS cada vez que se agregue tabla.
- Hacer policy tests para tablas sensibles.
- Proteger environments de GitHub para produccion.
- Rotacion documentada de secretos.
- Revisar CORS y headers de API.
- Agregar rate limiting si el frontend se vuelve publico.
- Agregar terminos visibles: no asesoria financiera.

Criterio de salida:

- El proyecto puede estar publico sin exponer claves ni rutas peligrosas.

### Bloque 14 - Integracion de Broker en Papel Externo

Objetivo: acercarse a ejecucion real sin capital real.

Tareas:

- Evaluar Alpaca Paper Trading para acciones/crypto soportadas.
- Crear `broker/` con interfaz abstracta.
- Implementar adaptador paper externo.
- Comparar paper interno vs paper broker.
- Registrar ordenes simuladas, rechazos, fills y balances.
- Mantener modo lectura/aprobacion, sin ordenes reales.

Criterio de salida:

- El sistema puede simular ordenes contra un broker paper sin tocar dinero real.

### Bloque 15 - Broker Real con Guardrails

Objetivo: preparar la ultima etapa, no ejecutarla aun.

Tareas:

- Kill switch global.
- Limites por activo, por dia y por usuario.
- Aprobacion humana para operaciones grandes.
- Modo solo cerrar posiciones.
- Max drawdown diario/semanal.
- Auditoria completa de ordenes.
- Separacion de credenciales paper vs live.

Criterio de salida:

- Solo se considera dinero real despues de paper trading suficiente, drift controlado y revision humana.

## Orden Recomendado

| Fase | Bloques | Horizonte | Motivo |
| --- | --- | --- | --- |
| 1 | 1, 2, 3 | Corto | Profesionaliza repo y evita datos malos. |
| 2 | 7, 8, 9 | Corto/medio | Mejora evaluacion, monitoreo y auditoria. |
| 3 | 5, 6, 10 | Medio | Aumenta capacidad predictiva con control. |
| 4 | 11, 12, 13 | Medio | Mejora producto, observabilidad y seguridad. |
| 5 | 14, 15 | Largo | Prepara broker solo cuando haya evidencia. |

## Roadmap de 30 Dias

Semana 1:

- Limpiar documentacion obsoleta.
- Crear CI profesional.
- Agregar data quality checks.
- Conectar webhook real.

Semana 2:

- Agregar reporte de drift inicial.
- Guardar reportes de monitoreo.
- Agregar metricas financieras avanzadas.
- Mostrar calidad de datos y drift en frontend.

Semana 3:

- Agregar LightGBM/XGBoost como candidatos opcionales.
- Agregar Optuna con presupuesto limitado.
- Registrar trials y parametros.

Semana 4:

- Agregar shadow mode.
- Agregar model cards.
- Crear dashboard de modelos promoted vs shadow.
- Preparar evaluacion de Alpaca Paper Trading.

## Decisiones Clave

| Decision | Recomendacion |
| --- | --- |
| Self-learning | Automatizado, pero con promocion controlada, nunca auto-reemplazo sin pruebas. |
| Base de datos | Mantener Supabase. Ya cubre datos, auth, storage y RLS. |
| Registry | Seguir con Supabase a corto plazo; evaluar MLflow si crece el lifecycle. |
| Modelos | Agregar boosting avanzado, pero conservar baselines. |
| Broker | No live trading hasta validar 6 a 12 meses o muestra suficiente. |
| Drift | Implementar antes de aumentar agresividad de modelos. |
| Frontend | Convertirlo en consola operativa con estado de datos/modelo/sistema. |

## Fuentes Consultadas

- scikit-learn TimeSeriesSplit: https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html
- Evidently data drift: https://docs.evidentlyai.com/metrics/preset_data_drift
- Evidently introduction: https://docs.evidentlyai.com/introduction
- MLflow Model Registry: https://mlflow.org/docs/latest/ml/model-registry/
- LightGBM docs: https://lightgbm.readthedocs.io/
- XGBoost docs: https://xgboost.readthedocs.io/
- Optuna docs: https://optuna.readthedocs.io/
- OpenTelemetry docs: https://opentelemetry.io/docs/
- GitHub Actions secure use: https://docs.github.com/en/actions/reference/security/secure-use
- Supabase RLS: https://supabase.com/docs/guides/database/postgres/row-level-security
- NIST AI Risk Management Framework: https://www.nist.gov/itl/ai-risk-management-framework
- Alpaca Paper Trading: https://docs.alpaca.markets/us/docs/paper-trading
