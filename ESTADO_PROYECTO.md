# Estado del Proyecto

Ultima revision operativa: 2026-07-12.

Faro ya cuenta con una base funcional para investigar, entrenar, evaluar y monitorear modelos de decision de inversion. El sistema no promete precision perfecta ni debe operar capital real sin una etapa prolongada de validacion; esta construido para maximizar evidencia, trazabilidad y control de riesgo antes de tomar decisiones.

## Capacidades Implementadas

| Bloque | Estado |
| --- | --- |
| Ingestion de mercado | Jobs para descargar OHLCV, normalizar precios y cargar Supabase. |
| Datasets ML | Materializacion de features tecnicos y labels por activo. |
| Entrenamiento | Modelos candidatos, evaluacion walk-forward, scopes globales y por activo. |
| Promocion | Seleccion de candidatos y registro de `model_runs` versionados. |
| Reentrenamiento | Job operativo para evaluar candidatos, promover modelos aprobados y subir artefactos. |
| Inferencia | Job operativo para generar predicciones latest desde modelos promovidos. |
| Riesgo | Motor de riesgo con perfiles default, por clase de activo y por ticker. |
| Feedback | Evaluacion de predicciones previas contra retornos observados. |
| Backtesting | Backtests persistidos y comparables por instrumento/modelo. |
| Paper trading | Simulaciones persistidas con curva de equity, eventos y comparativo. |
| Salud operativa | Endpoint y panel para verificar API, Supabase, esquema requerido y alertas por activo. |
| Seguridad Supabase | RLS activado para tablas publicas de mercado/modelo, con lectura controlada y sin escrituras anonimas. |
| Notificaciones | Webhook operativo opcional desde GitHub Actions con resumen de reportes. |
| SDD | OpenSpec inicializado para planificar mejoras profesionales por bloques. |
| Frontend | Dashboard React con senal, chart, riesgo, backtests, paper trading, feedback y estado del sistema. |
| CI operativo | Workflow GitHub Actions para datos, inferencia, paper trading o corrida completa. |

## Flujo Operativo Recomendado

1. Aplicar migraciones pendientes en Supabase.
2. Verificar el esquema con `python -m collector.schema_check`.
3. Cargar o actualizar historicos con `python -m collector.run_market_data_job`.
4. Entrenar y evaluar candidatos con validacion walk-forward.
5. Promover solo modelos con evidencia out-of-sample superior a baselines.
6. Ejecutar `python -m brain.run_inference_job` para guardar predicciones.
7. Ejecutar `python -m brain.run_paper_trading_job` para medir comportamiento simulado.
8. Revisar `/api/feedback/{ticker}`, `/api/paper-trading-runs/{ticker}` y `/api/health`.
9. Reentrenar cuando el feedback muestre degradacion, bajo acierto o cambios de regimen.

## Criterios Antes de Produccion Real

- Mantener paper trading activo durante varios ciclos de mercado, idealmente 6 a 12 meses segun frecuencia operativa.
- Comparar modelos globales, por clase de activo y por ticker antes de fijar una estrategia.
- Medir retorno neto con fees, slippage, drawdown, exposicion y estabilidad, no solo accuracy.
- Ampliar alertas con notificaciones externas para datos faltantes, inferencia fallida y degradacion de predicciones.
- Integrar broker solo despues de validar controles de riesgo, limites por usuario y revision humana.
- Mantener secretos fuera del repositorio, conservar RLS activo y rotar credenciales si alguna vez fueron expuestas.

## Comandos de Verificacion

```bash
python -m collector.schema_check
pytest tests
cd ui && npm run lint && npm run build && npm audit
```

## Riesgos Conocidos

- El rendimiento historico no garantiza rendimiento futuro.
- La individualizacion por activo puede mejorar especializacion, pero tambien aumenta riesgo de overfitting si hay pocos datos.
- Criptomonedas y acciones tienen microestructuras distintas; deben evaluarse con costos, horarios, liquidez y volatilidad propios.
- El sistema todavia no ejecuta ordenes reales. Esa ausencia es intencional hasta cerrar validacion, monitoreo y gobierno de riesgo.
