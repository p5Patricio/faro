# Brain

El modulo `brain` transforma precios historicos en datasets entrenables, etiquetas supervisadas y modelos de senales.

## Flujo actual

1. Cargar precios historicos con `collector`.
2. Materializar features y labels en Supabase.
3. Entrenar un modelo desde CSV o desde datasets exportados.
4. Comparar resultados con walk-forward validation.

## Materializar features y labels

Despues de cargar precios en Supabase:

```powershell
python -m brain.materialize_dataset --ticker AAPL --label-method triple_barrier --horizon 5
python -m brain.materialize_dataset --ticker BTCUSDT --feature-set technical_v1 --label-method fixed_horizon --horizon 5
```

Este comando:

1. busca el activo en Supabase;
2. descarga sus precios;
3. calcula features tecnicas point-in-time;
4. calcula labels supervisadas;
5. guarda resultados en `features_daily` y `labels_daily`.

## Entrenamiento desde CSV

```powershell
python -m brain.train --prices-csv data/raw/aapl_stooq.csv --model-out models/aapl.joblib --metrics-out reports/aapl_metrics.json --model-name random_forest
```

El entrenamiento usa validacion temporal walk-forward. No usa splits aleatorios.

Modelos disponibles:

- `baseline_hist_gradient_boosting`
- `logistic_regression`
- `random_forest`
- `extra_trees`

Feature sets disponibles:

- `technical_v1`: retornos, volatilidad, medias moviles, RSI, MACD, volumen, ATR y drawdown.
- `technical_v2`: agrega momentum 10/20d, Bollinger Bands, stochastic, OBV, ADX, SMA 50 y ratio de volatilidad.

## Entrenamiento desde Supabase

Despues de materializar features y labels:

```powershell
python -m brain.train_from_supabase --ticker AAPL --feature-set technical_v1 --label-method triple_barrier --horizon 5 --model-name random_forest
```

Este comando:

1. lee `features_daily` y `labels_daily`;
2. reconstruye el dataset supervisado;
3. ejecuta walk-forward validation;
4. entrena el modelo final;
5. guarda el artefacto en `models/`;
6. registra la corrida en `model_runs`.

## Generar predicciones versionadas

Con un `model_run` registrado:

```powershell
python -m brain.predict_from_supabase --ticker AAPL --model-name baseline_hist_gradient_boosting --model-version 20260705120000
```

Este comando:

1. lee el `model_run`;
2. carga el artefacto `.joblib`;
3. toma las features materializadas mas recientes;
4. genera probabilidades por clase;
5. aplica un umbral minimo de confianza;
6. guarda la salida en `predictions`.

Las predicciones quedan preparadas para evaluarse contra labels futuros mediante la vista `prediction_feedback`. Ese feedback debe usarse en reentrenamientos o meta-modelos; no se debe tratar una prediccion pasada como verdad hasta que exista su resultado real.

## Evaluacion walk-forward con backtest

Antes de promover un modelo, ejecuta una evaluacion out-of-sample desde Supabase:

```powershell
python -m brain.evaluate_from_supabase --ticker BTC-USD --feature-set technical_v2 --label-method triple_barrier --horizon 5 --model-name extra_trees --confidence-sweep 0.50,0.55,0.60,0.65,0.70,0.75 --out reports/btc_walk_forward_backtest.json
```

Este comando:

1. reconstruye el dataset materializado;
2. entrena solo con datos pasados en cada fold;
3. predice el tramo futuro de ese fold;
4. aplica embargo y evalua una operacion cada `horizon` filas por defecto para reducir solapamiento;
5. calcula retorno neto, drawdown, win rate y profit factor despues de costos;
6. compara contra baselines `no_trade`, `always_buy` y `always_sell`.
7. opcionalmente ordena los resultados de `--confidence-sweep` por retorno total para encontrar umbrales candidatos.

## Comparar scopes de entrenamiento

Para validar si conviene entrenar por activo, por clase de activo o globalmente:

```powershell
python -m brain.evaluate_training_scopes_from_supabase --ticker BTC-USD --feature-set technical_v2 --label-method triple_barrier --horizon 5 --model-name extra_trees --min-confidence 0.65 --out reports/btc_training_scopes.json
```

Este comando evalua siempre el activo objetivo, pero cambia los datos usados para entrenar cada fold:

- `local`: solo el activo objetivo.
- `asset_class`: activos de la misma clase, por ejemplo crypto.
- `global`: todos los activos con datasets materializados.

La comparacion ayuda a decidir si un modelo individual, por clase o global aporta mejor retorno ajustado por riesgo.

El reporte incluye un `ranking` con `objective_score` y una decision de promocion. Por defecto, un candidato debe tener retorno positivo, `profit_factor >= 1.0`, drawdown no peor que `-25%`, minimo 20 operaciones activas y ventaja contra `no_trade`.

Los criterios pueden endurecerse:

```powershell
python -m brain.evaluate_training_scopes_from_supabase --ticker BTC-USD --feature-set technical_v2 --label-method triple_barrier --horizon 5 --model-name extra_trees --min-confidence 0.65 --min-total-return 0.10 --min-profit-factor 1.3 --max-drawdown-floor -0.15 --min-active-trades 30 --drawdown-penalty 1.5 --out reports/btc_training_scopes.json
```

Este ranking no reemplaza una revision humana: sirve como compuerta automatica para que solo pasen modelos con evidencia suficiente de rentabilidad neta y control de riesgo.

## Buscar candidatos en matriz

Para comparar varios modelos, scopes y umbrales de confianza en una sola corrida:

```powershell
python -m brain.evaluate_candidate_matrix --ticker BTC-USD --feature-set technical_v2 --label-method triple_barrier --horizon 5 --models logistic_regression,random_forest,extra_trees --confidence-thresholds 0.55,0.60,0.65,0.70 --scopes local,asset_class,global --min-total-return 0.05 --min-profit-factor 1.2 --max-drawdown-floor -0.20 --min-active-trades 20 --drawdown-penalty 1.2 --out reports/btc_candidate_matrix.json
```

La salida contiene:

- `results`: resumen de cada combinacion evaluada;
- `ranking`: candidatos ordenados por promocion y `objective_score`;
- `errors`: combinaciones que fallaron sin detener la corrida completa.

Este comando es el punto de partida para decidir que combinacion de modelo, scope y umbral merece entrenarse como artefacto candidato para predicciones reales.

## Promover un candidato

Despues de generar un reporte de matriz, promueve el mejor candidato aprobado a `model_runs`:

```powershell
python -m brain.promote_candidate_from_report --report reports/btc_candidate_matrix.json --out reports/btc_promotion.json
```

Este comando:

1. toma el primer candidato con `promotion.status == pass`;
2. reconstruye el dataset segun su `scope`;
3. entrena el modelo final con todos los labels disponibles;
4. guarda el artefacto `.joblib` en `models/`;
5. registra el `model_run` en la base de datos local con `candidate_id`, metricas y assets usados;
6. genera la prediccion mas reciente para el activo objetivo.

El entrenamiento, la inferencia y el scheduler local comparten el mismo sistema de archivos, asi que el artefacto `.joblib` queda disponible de inmediato bajo `models/` sin ningun paso de carga adicional: `brain.artifacts.store_model_artifact` normaliza cualquier ruta entrenada hacia `models/` y `resolve_model_artifact` la resuelve para inferencia.

Para promover un candidato especifico:

```powershell
python -m brain.promote_candidate_from_report --report reports/btc_candidate_matrix.json --candidate-id BTC-USD::extra_trees::confidence_0.6500::global
```

Usa `--skip-prediction` si solo quieres registrar el modelo sin escribir una senal nueva.

### Risk engine

El comando de prediccion tambien aplica reglas de riesgo:

```powershell
python -m brain.predict_from_supabase --ticker AAPL --model-name baseline_hist_gradient_boosting --model-version 20260705120000 --min-confidence-to-trade 0.65 --max-position-size 0.08 --stop-loss 0.02 --take-profit 0.04
```

Las reglas pueden:

- convertir una senal debil a `HOLD`;
- bloquear shorts con `--no-short`;
- limitar el tamano de posicion;
- guardar `position_size`, `stop_loss`, `take_profit` y razones de bloqueo en `predictions.metadata`.

## Analizar feedback

Cuando ya existan labels para predicciones anteriores:

```powershell
python -m brain.feedback_report --ticker AAPL --model-name baseline_hist_gradient_boosting --model-version 20260705120000
python -m brain.feedback_report --model-name baseline_hist_gradient_boosting --model-version 20260705120000 --out reports/feedback_aapl.json
```

El reporte resume:

- predicciones evaluadas;
- accuracy;
- retorno medio y total;
- desempeno por accion predicha;
- desempeno por bucket de confianza.

Este reporte es la entrada segura para decidir si un modelo debe reentrenarse, ajustar su umbral de confianza o alimentar un meta-modelo.

## Backtesting de predicciones

Para probar si las senales hubieran ganado dinero despues de costos:

```powershell
python -m brain.backtest_predictions --ticker AAPL --model-name baseline_hist_gradient_boosting --model-version 20260705120000
python -m brain.backtest_predictions --ticker AAPL --model-name baseline_hist_gradient_boosting --model-version 20260705120000 --fee-bps 5 --slippage-bps 5 --persist
```

El backtest usa predicciones ya evaluadas desde `prediction_feedback`. Calcula:

- retorno neto;
- equity final;
- max drawdown;
- win rate;
- profit factor;
- exposicion;
- costos estimados.

Con `--persist`, guarda el resumen en `backtests` y las operaciones simuladas en `backtest_trades`.
