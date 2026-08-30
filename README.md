# Faro

![Faro](ui/public/brand/faro-logo.png)

Plataforma experimental para investigacion, entrenamiento y evaluacion de modelos de decision de inversion. El objetivo es convertir datos historicos de mercado en senales auditables de **comprar**, **vender** o **mantener**, siempre acompanadas por confianza, riesgo, probabilidades y trazabilidad del modelo.

> Este proyecto no es asesoria financiera. Las senales deben validarse con backtesting, gestion de riesgo y supervision humana antes de cualquier uso real.

## Estado Actual

| Area | Estado |
| --- | --- |
| Frontend | Dashboard React con activos, grafico, senal, riesgo, probabilidades, backtests e historial de predicciones. |
| API | FastAPI con endpoints para activos, precios, analisis, backtests e historial de predicciones. |
| Datos | PostgreSQL local como unica fuente; modo demo local cuando la base de datos no esta disponible; universo ampliado a S&P 100 (101 tickers) con snapshot fechado y disclosure de sesgo de supervivencia. |
| ML | Pipeline base para features, labels, entrenamiento, inferencia, feedback y backtesting. |
| Calidad | Suite de pruebas para API, collector, repositorio Postgres local y pipeline de modelo. |

## Experiencia

La interfaz esta pensada como una consola operativa, no como landing page. El usuario ve primero:

- Activo seleccionado y clase de activo.
- Senal actual: `BUY`, `SELL` o `HOLD`.
- Confianza y horizonte.
- Grafico historico de precio.
- Gestion de riesgo: posicion, stop, objetivo y bloqueos.
- Probabilidades por accion.
- Backtests persistidos por instrumento y version de modelo.
- Metadatos del modelo o indicador que genero la lectura.
- Historial reciente para auditar predicciones y feedback.

Cuando la API no puede conectarse a la base de datos local, la aplicacion muestra `Datos demo` para evitar confundir datos sinteticos con datos reales.

## Arquitectura

```mermaid
flowchart LR
  sources["Market data providers"] --> collector["collector"]
  collector --> postgres[("PostgreSQL local")]
  postgres --> brain["brain: features, labels, training"]
  brain --> predictions["predictions + feedback"]
  predictions --> api["FastAPI"]
  postgres --> api
  api --> ui["React dashboard"]
```

## Estructura

| Ruta | Proposito |
| --- | --- |
| `api/` | API HTTP con FastAPI. |
| `brain/` | Features, labeling, entrenamiento, inferencia, feedback y backtesting. |
| `collector/` | Descarga y carga de historicos hacia PostgreSQL local. |
| `db/migrations/` | Esquema SQL para datos, modelos, predicciones y feedback. |
| `ui/` | Frontend React + Vite + Tailwind. |
| `tests/` | Pruebas automatizadas del sistema. |
| `openspec/` | SDD/OpenSpec para cambios profesionales y requisitos activos. |
| `CONTRIBUTING.md` | Guia para contribuir, verificar y trabajar sin filtrar secretos. |
| `SECURITY.md` | Politica de seguridad, reporte privado y rotacion de credenciales. |
| `CHANGELOG.md` | Historial de cambios relevantes. |
| `INVESTIGACION_MODELO_PREDICTIVO.md` | Guia de investigacion y hoja de ruta tecnica. |
| `PLAN_MEJORAS_PROFESIONALES.md` | Roadmap profesional por bloques. |

## Configuracion

1. Crea una copia local de variables:

```bash
cp .env.example .env
```

2. Completa tus credenciales:

```env
APP_ENV=development
ALLOW_DEMO_FALLBACK=true
API_CORS_ORIGINS=*
LOCAL_DATABASE_URL=postgresql://postgres:tu-password@localhost:5432/ia_inversiones
VITE_API_BASE_URL=http://localhost:8000/api
```

`LOCAL_DATABASE_URL` apunta a tu instancia local de PostgreSQL (backend, ingestion, entrenamiento, inferencia y el scheduler local la usan por igual). Nunca la subas al repositorio ni la escribas en scripts versionados; para pruebas usa una base separada via `TEST_DATABASE_URL` (ver `tests/conftest.py`).

El frontend esta configurado para leer las variables `VITE_*` desde este `.env` de la raiz del repositorio.

Variables de entorno principales:

| Variable | Uso |
| --- | --- |
| `APP_ENV` | Entorno de ejecucion: `development`, `staging`, `production` o `test`. |
| `ALLOW_DEMO_FALLBACK` | Permite servir datos demo si la base de datos no esta disponible. Por defecto es `true` fuera de produccion y `false` en `production`. |
| `API_CORS_ORIGINS` | Lista separada por comas de origenes permitidos por la API. |
| `LOCAL_DATABASE_URL` | DSN de PostgreSQL local usado por la API, el collector, `brain/` y `ops/run_local_scheduler`. |
| `TEST_DATABASE_URL` | DSN de una base Postgres separada para pruebas (`pytest`); nunca la misma base que `LOCAL_DATABASE_URL`. |
| `VITE_API_BASE_URL` | URL base que usa el frontend para llamar a la API. |
| `TELEGRAM_BOT_TOKEN` | Opcional. Token del bot de Telegram que usa `ops/notify_operational_job` para alertas operativas (fallo de job, cambio de senal, degradacion de modelo, datos vencidos). Ver [Notificaciones por Telegram](#notificaciones-por-telegram). |
| `TELEGRAM_CHAT_ID` | Opcional. ID del chat o canal de Telegram donde se publican esas alertas. Requiere `TELEGRAM_BOT_TOKEN` para tener efecto. |

3. Instala dependencias:

```bash
pip install -r requirements.txt
cd ui
npm install
```

## Ejecucion Local

API:

```bash
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Frontend:

```bash
cd ui
npm run dev -- --host 127.0.0.1 --port 5173
```

Abre [http://127.0.0.1:5173](http://127.0.0.1:5173).

## Verificacion

Backend y pipeline:

```bash
pytest tests
```

Frontend:

```bash
cd ui
npm run lint
npm run build
```

Conexion con la base de datos local:

```bash
python -c "from collector.local_repository import LocalPostgresConfig, LocalPostgresRepository; import psycopg; c=psycopg.connect(LocalPostgresConfig.from_env().dsn); r=LocalPostgresRepository(connection=c); print(len(r.get_assets()))"
```

Esquema ML local:

```bash
python -m collector.schema_check
```

Si falta alguna relacion, aplica las migraciones pendientes con `py -3.14 -m db.migrate` y vuelve a ejecutar el chequeo.

Si falla DNS o red en desarrollo, la API activa el modo demo local para que el dashboard siga siendo navegable. En produccion, deja `ALLOW_DEMO_FALLBACK=false` para que los fallos de datos se reporten como errores reales en lugar de mostrarse como lecturas sinteticas.

## Contribucion y Seguridad

Antes de abrir cambios revisa:

- `CONTRIBUTING.md` para flujo local, comandos de verificacion y SDD.
- `SECURITY.md` para manejo de secretos, RLS y rotacion de credenciales.
- `CHANGELOG.md` para registrar cambios relevantes.

## Flujo de Trabajo del Modelo

1. Descargar historicos de mercado por instrumento.
2. Cargar precios normalizados a PostgreSQL local.
3. Materializar features tecnicos y labels.
4. Entrenar modelos candidatos con validacion walk-forward.
5. Evaluar out-of-sample con backtesting, baselines y barrido de umbrales.
6. Guardar `model_runs`, predicciones y metadata.
7. Evaluar feedback de predicciones previas.
8. Servir la decision en la API con riesgo y trazabilidad.

## Paper Trading

La API puede simular una cuenta de paper trading con las predicciones ya guardadas y precios observados:

```bash
curl "http://127.0.0.1:8000/api/paper-trading/BTC-USD?initial_capital=10000&fee_bps=5&slippage_bps=5"
```

La simulacion mantiene posicion con `HOLD`, abre/ajusta long con `BUY`, abre/ajusta short con `SELL` cuando esta permitido, y aplica costos solo cuando cambia la exposicion. Devuelve metricas como equity final, retorno total, drawdown, operaciones ejecutadas, exposicion promedio y posicion abierta. El dashboard muestra estas metricas junto con la curva de equity, marcadores de operaciones y ultimas senales simuladas para revisar rapidamente como se habria comportado la estrategia.

Para guardar una simulacion y compararla despues, aplica las migraciones locales (`py -3.14 -m db.migrate`) y ejecuta:

```bash
curl "http://127.0.0.1:8000/api/paper-trading/BTC-USD?persist=true&initial_capital=10000&fee_bps=5&slippage_bps=5"
curl "http://127.0.0.1:8000/api/paper-trading-runs/BTC-USD?limit=10"
```

En el dashboard, el panel de paper trading permite guardar la corrida actual y comparar las corridas persistidas por retorno, drawdown, trades, equity y modelo.

Para persistir corridas periodicas por ticker desde un scheduler:

```bash
python -m brain.run_paper_trading_job --tickers BTC-USD,AAPL --out reports/paper_trading_job.json
```

## Monitoreo de Predicciones

La API expone calidad historica por activo con accuracy, confianza media y retorno realizado:

```bash
curl "http://127.0.0.1:8000/api/feedback/BTC-USD?limit=250"
```

El dashboard muestra este resumen en `Calidad del modelo` para detectar degradacion, sesgos por accion y necesidad de reentrenamiento.

## Salud Operativa

Para revisar API, base de datos y esquema requerido:

```bash
curl "http://127.0.0.1:8000/api/health"
```

El dashboard muestra el estado en el panel `Sistema`.

## Alertas Operativas

Para revisar frescura de datos, existencia de prediccion versionada y calidad minima del feedback:

```bash
curl "http://127.0.0.1:8000/api/alerts/BTC-USD"
```

El endpoint acepta umbrales operativos como `max_price_age_hours`, `min_feedback_samples`, `min_accuracy` y `min_mean_outcome_return`. El dashboard muestra estas alertas junto al estado del sistema para separar lecturas saludables, datos demo, precios atrasados, falta de predicciones y degradacion del modelo.

## Universo de Activos

`GET /api/universe` expone el disclosure de sesgo de supervivencia del snapshot S&P 100 usado por el collector y por `run_retraining_job` (deliberadamente separado de `GET /api/assets`, que sigue devolviendo una lista plana):

```bash
curl "http://127.0.0.1:8000/api/universe"
```

El snapshot vive en `config/universe.sp100.json` (101 tickers; membresia al 2025-09-22 segun el articulo "S&P 100" de Wikipedia, consultado 2026-08-28). Un ticker del listado fuente (`HONA`) resulto ser un artefacto de scraping: se verifico via SEC EDGAR (CIK 0000773840) y cotizaciones independientes (Nasdaq, Bloomberg, Investing.com) que Honeywell International cotiza como `HON`; el snapshot usa `HON`.

Ampliar el universo de ingesta no amplia automaticamente los targets de reentrenamiento por defecto: `run_retraining_job` sigue acotado por `config/targets.core.json` (4 tickers) mas `--max-auto-targets`/`--max-global-scope-assets`, que fallan explicitamente en vez de truncar en silencio si se supera el limite.

**Pendiente**: requiere un backfill real (`collector.run_market_data_job --assets-file config/universe.sp100.json`) seguido de una comparacion completa de reentrenamiento antes/despues para medir el tiempo de ejecucion real entre el baseline de ~4 activos y el universo ampliado (~101 activos). Se dejo deliberadamente fuera de esta iteracion -- `financial-intelligence-expansion` no reentrena sobre el universo ampliado en la misma tanda en que lo agrega -- como paso operativo separado.

## Jobs Operativos

Para actualizar precios y materializar datasets:

```bash
python -m collector.run_market_data_job --assets-file config/assets.core.json --feature-sets technical_v2 --out reports/market_data_job.json
```

Para materializar un activo ya cargado en la base de datos local sin descargar precios:

```bash
python -m collector.run_market_data_job --skip-collection --tickers BTC-USD --feature-sets technical_v2 --out reports/market_data_job_btc.json
```

El job de datos:

- descarga precios para los activos configurados;
- guarda OHLCV normalizado en PostgreSQL local;
- materializa features y labels;
- reporta errores por activo sin detener todo el proceso, salvo que uses `--fail-fast`.

Para generar predicciones latest desde los modelos promovidos:

```bash
python -m brain.run_inference_job --out reports/inference_job.json
```

El job:

- busca `model_runs` creados por promocion de candidatos;
- identifica su `target_ticker`;
- carga el artefacto `.joblib`;
- genera la prediccion mas reciente desde features materializadas;
- aplica reglas de riesgo;
- guarda la prediccion en PostgreSQL local.

El job de paper trading persiste simulaciones de las predicciones guardadas en `paper_trading_runs` y `paper_trading_events`, y alimenta el comparativo del dashboard.

Para evaluar candidatos, promover el mejor modelo aprobado, normalizar su artefacto en `models/` y guardar una prediccion latest:

```bash
python -m brain.run_retraining_job --tickers BTC-USD --models logistic_regression,random_forest,extra_trees --confidence-thresholds 0.55,0.60,0.65,0.70 --scopes local,asset_class,global --out reports/retraining_job.json
```

El job de reentrenamiento no promueve por inercia. Si ningun candidato supera los criterios de retorno, profit factor, drawdown, numero minimo de operaciones y ventaja contra no operar, el ticker queda como `skipped` con razon `no_promotable_candidate`.

Cuando ya existe un modelo promovido para el mismo ticker, `feature_set`, `label_method` y horizonte, el candidato tambien debe mejorar su `objective_score`. Si no lo supera, el ticker queda como `skipped` con razon `candidate_not_better_than_incumbent`. Para experimentos controlados puedes usar `--no-require-incumbent-improvement`; para exigir margen adicional, usa `--min-objective-improvement 0.01`.

Entrenamiento, inferencia y el scheduler local comparten un mismo sistema de archivos (`models/`, gitignorado), por lo que no existe un paso de subida por separado: `store_model_artifact` deja el `.joblib` bajo `models/` y `model_runs.artifact_uri` guarda esa ruta relativa directamente.

Puede filtrarse por version:

```bash
python -m brain.run_inference_job --model-name extra_trees --model-version promoted_smoke_20260706
```

### Scheduler Local

Los jobs operativos ya no corren en GitHub Actions (un runner hospedado no tiene ruta de red hacia un Postgres que escucha en `localhost`). En su lugar, `ops/run_local_scheduler.py` ejecuta el mismo ciclo como procesos locales, orquestados por el Programador de Tareas de Windows:

```bash
py -3.14 -m ops.run_local_scheduler --job {market_data|inference|paper_trading|retraining|full|full_retrain}
    [--tickers BTC-USD,AAPL] [--feature-sets technical_v2] [--skip-collection]
    [--model-name ...] [--model-version ...]
    [--models logistic_regression,random_forest,extra_trees]
    [--confidence-thresholds 0.55,0.60,0.65,0.70] [--scopes local,asset_class,global]
    [--no-require-incumbent-improvement] [--min-objective-improvement 0.0]
    [--reports-dir reports] [--no-notify]
```

- `market_data` / `inference` / `paper_trading` / `retraining`: corre un unico paso.
- `full`: actualiza datos, ejecuta inferencia y persiste paper trading (equivalente al ciclo diario anterior).
- `full_retrain`: agrega el paso de reentrenamiento/promocion al ciclo `full` (equivalente al ciclo semanal anterior).
- Cada paso corre con un argv fijo (`subprocess.run([sys.executable, "-m", modulo, *args])`, nunca `shell=True`), falla si el proceso termina con codigo distinto de cero o si su reporte JSON trae `failed > 0`, y el resultado se escribe en `logs/local_scheduler_{job}_{YYYYMMDD}.log`.
- El ultimo paso siempre invoca `ops.notify_operational_job` (salvo `--no-notify`), que reporta el resultado por el webhook configurado y por Telegram si `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` estan definidos.

Antes de programar los jobs, asegurate de tener en tu entorno (o en `.env`, nunca hardcodeado en un script):

```text
LOCAL_DATABASE_URL
OPERATIONAL_WEBHOOK_URL   # opcional, para notificaciones externas
TELEGRAM_BOT_TOKEN        # opcional, para notificaciones por Telegram
TELEGRAM_CHAT_ID          # opcional, para notificaciones por Telegram
```

#### Notificaciones por Telegram

`ops/notification_dispatch.py` evalua cuatro alertas (fallo de job, cambio de senal BUY/SELL, degradacion de modelo, datos vencidos) y las envia por Telegram con dedupe y cooldown por regla; sin `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` el envio es un no-op silencioso (el resto del job sigue igual).

1. **Crear el bot.** En Telegram, hablar con [@BotFather](https://t.me/BotFather), enviar `/newbot` y seguir las instrucciones. BotFather entrega un token con forma `123456789:AA...` — ese es `TELEGRAM_BOT_TOKEN`.
2. **Obtener el `chat_id`.** Agregar el bot al chat o canal donde quieres recibir las alertas y enviar cualquier mensaje ahi. Luego, con el token del paso anterior:

   ```bash
   curl "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getUpdates"
   ```

   El campo `result[].message.chat.id` (o `channel_post.chat.id` en un canal) es tu `TELEGRAM_CHAT_ID`.
3. **Configurar `.env`.** Agrega ambas variables a tu `.env` local (nunca las subas al repositorio ni las escribas en un script versionado):

   ```env
   TELEGRAM_BOT_TOKEN=123456789:AA...
   TELEGRAM_CHAT_ID=-1009876543210
   ```
4. **Verificar que funciona.** Forzar una notificacion de prueba sin depender de un job real:

   ```bash
   py -3.14 -m ops.notify_operational_job --reports-dir reports --status failure
   ```

   Con ambas variables definidas deberia llegar un mensaje al chat configurado; la salida JSON en consola tambien muestra `notification.telegram.sent: true`. Si no llega nada, revisa que el bot siga en el chat/canal y que el `chat_id` sea correcto.
5. **Revocar un token filtrado.** Si el token se expuso (por ejemplo en un log o commit), hablar de nuevo con BotFather y enviar `/revoke` sobre ese bot para invalidarlo, luego actualizar `TELEGRAM_BOT_TOKEN` en tu `.env` con el nuevo valor.
6. **Desactivar Telegram (rollback).** Quitar ambas variables del entorno/`.env` (o dejarlas vacias): `ops/notify_operational_job` vuelve a ser un no-op para ese transporte, sin tocar el webhook generico ni el resto del scheduler.

Para registrar las dos tareas programadas (diaria 06:20 con `--job full`, semanal domingo 06:40 con `--job full_retrain`), revisa y ejecuta `ops/register_local_jobs.ps1`:

```powershell
./ops/register_local_jobs.ps1
```

El script solo llama a `schtasks /Create`; no guarda ninguna credencial. Verificar, probar y eliminar las tareas:

```bat
schtasks /Query /TN "Faro\DailyOperationalCycle" /V /FO LIST
schtasks /Run /TN "Faro\DailyOperationalCycle"
schtasks /Delete /TN "Faro\DailyOperationalCycle" /F
```

Los reportes JSON quedan en `reports/*.json` (gitignorado) y el log de cada corrida en `logs/*.log` (gitignorado).

## Perfiles de Riesgo

Los endpoints de perfil de riesgo no requieren autenticacion; el alcance (`scope_type`/`scope_value`) reemplaza al usuario:

```bash
curl "http://127.0.0.1:8000/api/risk-profile?scope_type=default"
```

Para guardar el perfil por defecto:

```bash
curl -X PUT http://127.0.0.1:8000/api/risk-profile \
  -H "Content-Type: application/json" \
  -d '{"scope_type":"default","max_position_size":0.05,"min_confidence_to_trade":0.7,"max_expected_risk":0.03,"stop_loss":0.02,"take_profit":0.05,"allow_short":false}'
```

Tambien puedes guardar perfiles por clase de activo o ticker. La prioridad al analizar un activo es `ticker > asset_class > default`:

```bash
curl -X PUT http://127.0.0.1:8000/api/risk-profile \
  -H "Content-Type: application/json" \
  -d '{"scope_type":"asset_class","scope_value":"crypto","max_position_size":0.03,"min_confidence_to_trade":0.75,"max_expected_risk":0.04,"stop_loss":0.02,"take_profit":0.06,"allow_short":false}'
```

Sin perfiles guardados, `GET /api/risk-profile` devuelve la politica conservadora por defecto (tabla `risk_profiles` vacia tras una instalacion nueva). Ejecuta `py -3.14 -m db.migrate` para crear el esquema.

El frontend no requiere autenticacion para editar el perfil de riesgo. Desde el panel `Perfil`, el usuario puede alternar entre editar el perfil global, el de la clase del activo seleccionado o el del ticker seleccionado.

`GET /api/analysis/{ticker}` conserva la prediccion versionada del modelo pero recalcula la accion final, el tamano de posicion, stop, objetivo y bloqueos con el perfil de riesgo resuelto para ese activo (`ticker > asset_class > default`).

La interfaz muestra esa transparencia como `Modelo base -> decision final`, junto con el perfil aplicado y las razones de bloqueo cuando el motor de riesgo cambia o condiciona la senal.

## Seguridad Para Repos Publicos

- No publiques `.env`.
- Usa `.env.example` para documentar variables.
- Usa claves server-side solo en procesos privados de backend/pipeline, nunca en el frontend.
- Revisa que `LOCAL_DATABASE_URL` y el token de Telegram no queden en commits.
- Rota cualquier credencial que haya sido expuesta previamente.

## Roadmap

- Aplicar perfiles de riesgo de usuario durante inferencia personalizada.
