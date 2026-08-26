# Plan de Despliegue

Este plan describe como llevar IA Inversiones desde el estado actual a una operacion continua con datos reales, predicciones versionadas, paper trading y reentrenamiento controlado.

## 1. Arquitectura Objetivo

| Capa | Servicio recomendado |
| --- | --- |
| Base de datos | Supabase Postgres |
| Storage de modelos | Supabase Storage, bucket `model-artifacts` |
| Backend API | Servicio Python persistente para FastAPI |
| Frontend | Hosting estatico para Vite/React |
| Jobs operativos | GitHub Actions programado |
| Secretos | GitHub Secrets y variables del proveedor de hosting |
| Monitoreo inicial | `/api/health`, `/api/alerts/{ticker}` y artifacts JSON de GitHub Actions |
| Seguridad de datos | RLS en Supabase, backend con clave server-side y frontend solo con anon key |

## 2. Fuentes de Datos

El proyecto ya soporta estos proveedores:

| Proveedor | Uso actual |
| --- | --- |
| Binance | Criptomonedas OHLCV, por ejemplo `BTCUSDT` y `ETHUSDT`. |
| yfinance | Acciones, ETFs, indices y algunos instrumentos crypto. |
| Stooq | Fuente alternativa para acciones e indices. |

El universo operativo inicial vive en `config/assets.core.json`.

## 3. Flujo Continuo

1. GitHub Actions ejecuta el ciclo diario `full`: datos, inferencia y paper trading.
2. El job descarga precios, actualiza Supabase y materializa features/labels.
3. El job de inferencia ejecuta `brain.run_inference_job` con los modelos promovidos.
4. Las predicciones se guardan en Supabase.
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
7. Subir el artefacto `.joblib` a Supabase Storage.
8. Usar la nueva version solo en inferencia posterior.

Las predicciones pasadas sirven como feedback operativo y como criterio de promocion. La etiqueta de entrenamiento debe venir del mercado observado, no de "si el modelo dijo bien o mal" por si sola.

## 5. GitHub Actions

El workflow actual `.github/workflows/operational-jobs.yml` ya cubre:

- `market_data`
- `inference`
- `paper_trading`
- `full`
- `full_retrain` semanal

Secretos necesarios:

```text
SUPABASE_URL
SUPABASE_KEY
OPERATIONAL_WEBHOOK_URL  # opcional
```

El workflow ya soporta reentrenamiento controlado con:

- `retraining`: evalua candidatos, promueve solo aprobados que mejoran al modelo vigente y sube artefactos.
- `full_retrain`: actualiza datos, reentrena, ejecuta inferencia y guarda paper trading.
- Reportes JSON como artifacts.
- Notificacion opcional a webhook externo con resumen de errores, skips y resultados.
- Fallo del workflow solo cuando hay errores tecnicos; si no hay candidato suficientemente bueno, el activo queda como `skipped`.

Bloque pendiente recomendado:

- Conectar `OPERATIONAL_WEBHOOK_URL` a Slack, Discord, Teams o un endpoint propio.

## 6. Seguridad Supabase

La migracion `supabase/migrations/20260708000100_public_market_rls.sql` activa RLS para las tablas publicas de mercado, entrenamiento, predicciones, backtests y paper trading. Los clientes `anon` y `authenticated` solo reciben politicas de lectura; las escrituras operativas quedan reservadas para procesos server-side con `SUPABASE_KEY`.

Despues de aplicarla, validar en Supabase que no queden avisos criticos de tablas publicas sin RLS y ejecutar `python -m collector.schema_check`.

## 7. Variables de Produccion

Backend:

```text
APP_ENV=production
ALLOW_DEMO_FALLBACK=false
API_CORS_ORIGINS=https://frontend-produccion
SUPABASE_URL=...
SUPABASE_KEY=...
```

Frontend:

```text
VITE_API_BASE_URL=https://api-produccion/api
```

## 8. Pasos de Despliegue

1. Confirmar migraciones aplicadas en Supabase.
2. Crear bucket `model-artifacts` en Supabase Storage.
3. Configurar GitHub Secrets.
4. Configurar hosting de backend con variables privadas.
5. Configurar hosting de frontend con variables `VITE_*`.
6. Ejecutar `python -m collector.schema_check` en produccion.
7. Ejecutar workflow `market_data`.
8. Entrenar/promover primer modelo productivo.
9. Ejecutar workflow `inference`.
10. Ejecutar workflow `paper_trading`.
11. Validar `/api/health`, `/api/alerts/BTC-USD` y dashboard.

## 9. Criterios Antes de Dinero Real

- Paper trading suficiente por activo.
- Muestra minima de feedback evaluado.
- Modelo superior a baselines simples.
- Retorno neto positivo despues de fees y slippage.
- Drawdown dentro de limites aceptables.
- Alertas operativas sin fallos criticos.
- Revision humana antes de ejecutar ordenes reales.
