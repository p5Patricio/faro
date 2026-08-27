# Plan de Despliegue

> **Nota (post-migracion a Postgres local):** el proyecto paso de una arquitectura
> hospedada (Supabase + GitHub Actions + hosting cloud) a una operacion local de una
> sola maquina (PostgreSQL local + Programador de Tareas de Windows). El despliegue
> hospedado descrito historicamente aqui esta fuera de alcance mientras dure ese
> pivote; el README ("Configuracion", "Scheduler Local") es la fuente de verdad para
> la operacion actual. Este documento se mantiene actualizado en lo que sigue siendo
> aplicable (flujo del modelo, reentrenamiento, criterios antes de dinero real).

Este plan describe como llevar IA Inversiones desde el estado actual a una operacion continua con datos reales, predicciones versionadas, paper trading y reentrenamiento controlado.

## 1. Arquitectura Objetivo

| Capa | Servicio recomendado |
| --- | --- |
| Base de datos | PostgreSQL local (`LOCAL_DATABASE_URL`) |
| Storage de modelos | Sistema de archivos local, directorio `models/` (gitignorado) |
| Backend API | Proceso local persistente para FastAPI (`uvicorn api.main:app`) |
| Frontend | Build estatico local de Vite/React |
| Jobs operativos | Programador de Tareas de Windows (`ops/run_local_scheduler.py`) |
| Secretos | Variables de entorno locales (`.env`, nunca en el repositorio) |
| Monitoreo inicial | `/api/health`, `/api/alerts/{ticker}` y `logs/local_scheduler_*.log` |
| Seguridad de datos | Postgres solo en `localhost`, sin exposicion de red; sin RLS (proceso unico local) |

## 2. Fuentes de Datos

El proyecto ya soporta estos proveedores:

| Proveedor | Uso actual |
| --- | --- |
| Binance | Criptomonedas OHLCV, por ejemplo `BTCUSDT` y `ETHUSDT`. |
| yfinance | Acciones, ETFs, indices y algunos instrumentos crypto. |
| Stooq | Fuente alternativa para acciones e indices. |

El universo operativo inicial vive en `config/assets.core.json`.

## 3. Flujo Continuo

1. El scheduler local (`ops.run_local_scheduler --job full`) ejecuta el ciclo diario: datos, inferencia y paper trading.
2. El job descarga precios, actualiza PostgreSQL local y materializa features/labels.
3. El job de inferencia ejecuta `brain.run_inference_job` con los modelos promovidos.
4. Las predicciones se guardan en PostgreSQL local.
5. Cuando pasa el horizonte de prediccion, el feedback compara prediccion contra resultado observado.
6. El job de paper trading simula la estrategia con predicciones reales guardadas.
7. Las alertas operativas detectan datos atrasados, falta de prediccion, poco feedback o degradacion.
8. Un job semanal `full_retrain` evalua candidatos y promueve solo modelos que mejoren al vigente.

## 4. Reentrenamiento Controlado

El modelo no debe "auto-modificarse" sin control. La version profesional es un ciclo automatizado con guardrails:

1. Entrenar candidatos con historicos actualizados.
2. Validar con walk-forward y out-of-sample.
3. Comparar contra el modelo promovido vigente.
4. Evaluar retorno neto, drawdown, accuracy, profit factor, cobertura y estabilidad.
5. Rechazar modelos con poca muestra, exceso de drawdown o mejora estadisticamente debil.
6. Promover el nuevo modelo creando un `model_run` versionado.
7. Normalizar el artefacto `.joblib` bajo `models/` (`store_model_artifact`).
8. Usar la nueva version solo en inferencia posterior.

Las predicciones pasadas sirven como feedback operativo y como criterio de promocion. La etiqueta de entrenamiento debe venir del mercado observado, no de "si el modelo dijo bien o mal" por si sola.

## 5. Scheduler Local

`ops/run_local_scheduler.py` cubre los mismos modos que el workflow retirado, corridos como procesos locales en vez de un runner hospedado:

- `market_data`
- `inference`
- `paper_trading`
- `retraining`
- `full`
- `full_retrain`

Variables de entorno necesarias (nunca hardcodeadas en un script versionado):

```text
LOCAL_DATABASE_URL
OPERATIONAL_WEBHOOK_URL   # opcional
TELEGRAM_BOT_TOKEN        # opcional
TELEGRAM_CHAT_ID          # opcional
```

El scheduler soporta reentrenamiento controlado con:

- `retraining`: evalua candidatos, promueve solo aprobados que mejoran al modelo vigente y normaliza artefactos en `models/`.
- `full_retrain`: actualiza datos, reentrena, ejecuta inferencia y guarda paper trading.
- Reportes JSON en `reports/*.json` (no versionados).
- Notificacion al final de cada corrida por webhook y/o Telegram con resumen de errores, skips y resultados.
- Codigo de salida distinto de cero cuando hay errores tecnicos; si no hay candidato suficientemente bueno, el activo queda como `skipped` (no cuenta como fallo).

Registro de las tareas programadas (diaria 06:20 `--job full`, semanal domingo 06:40 `--job full_retrain`): `ops/register_local_jobs.ps1`. Ver README, seccion "Scheduler Local".

## 6. Seguridad Local

Postgres corre en `localhost` sin exponerse a la red, por lo que no aplica RLS (row-level security): el unico proceso que se conecta es el propio backend/pipeline local, ejecutado por el mismo usuario del sistema operativo. Protege `LOCAL_DATABASE_URL` (nunca en commits ni en scripts versionados) y, si usas Telegram, `TELEGRAM_BOT_TOKEN`.

Ejecutar `python -m collector.schema_check` despues de cada `py -3.14 -m db.migrate` para validar el esquema.

## 7. Variables de Entorno Local

Backend:

```text
APP_ENV=development
ALLOW_DEMO_FALLBACK=true
API_CORS_ORIGINS=*
LOCAL_DATABASE_URL=postgresql://postgres:tu-password@localhost:5432/ia_inversiones
```

Frontend:

```text
VITE_API_BASE_URL=http://localhost:8000/api
```

## 8. Pasos de Puesta en Marcha

1. Confirmar migraciones aplicadas: `py -3.14 -m db.migrate`.
2. Confirmar el directorio `models/` disponible (se crea solo al primer artefacto).
3. Configurar `.env` local con `LOCAL_DATABASE_URL` y, si aplica, `OPERATIONAL_WEBHOOK_URL`/`TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`.
4. Levantar el backend (`uvicorn api.main:app`) y el frontend (`npm run dev` o `npm run build`).
5. Ejecutar `python -m collector.schema_check`.
6. Ejecutar `py -3.14 -m ops.run_local_scheduler --job market_data`.
7. Entrenar/promover primer modelo (`--job retraining` o `--job full_retrain`).
8. Ejecutar `py -3.14 -m ops.run_local_scheduler --job inference`.
9. Ejecutar `py -3.14 -m ops.run_local_scheduler --job paper_trading`.
10. Validar `/api/health`, `/api/alerts/BTC-USD` y el dashboard.
11. Registrar las tareas programadas con `ops/register_local_jobs.ps1`.

## 9. Criterios Antes de Dinero Real

- Paper trading suficiente por activo.
- Muestra minima de feedback evaluado.
- Modelo superior a baselines simples.
- Retorno neto positivo despues de fees y slippage.
- Drawdown dentro de limites aceptables.
- Alertas operativas sin fallos criticos.
- Revision humana antes de ejecutar ordenes reales.
