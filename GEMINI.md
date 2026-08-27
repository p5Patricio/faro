# Instrucciones del Proyecto: Faro

Este documento contiene los mandatos y convenciones específicos para el desarrollo de este proyecto.

## Arquitectura y Tecnologías
- **Backend:** FastAPI. Seguir patrones de diseño modulares (routers, services, models).
- **Frontend:** React con TypeScript. Usar Shadcn/UI para componentes de interfaz.
- **Base de Datos:** Supabase (PostgreSQL). Utilizar `supabase-py` para el backend.
- **Datos:** Priorizar `yfinance` para datos históricos y de mercado gratuitos.
- **IA/ML:** 
    - Modelos: XGBoost, Random Forest.
    - NLP: FinBERT para sentimiento.
    - Librerías: `pandas`, `pandas_ta`, `scikit-learn`, `transformers`.

## Convenciones de Desarrollo
- **KISS:** No sobre-diseñar. Mantener la implementación simple y funcional.
- **Documentación:** Cada módulo debe tener un `README.md` o comentarios claros sobre su funcionamiento.
- **Pruebas:** Cada nueva funcionalidad debe incluir pruebas unitarias o scripts de verificación en la carpeta correspondiente.
- **Variables de Entorno:** Nunca hardcodear credenciales. Usar archivos `.env` (asegurarse de que estén en `.gitignore`).

## Estructura de Datos (Inicial)
- **Tabla `assets`:** Información de los activos (ticker, nombre, clase de activo).
- **Tabla `prices`:** Series temporales de precios OHLCV (timestamp, asset_id, open, high, low, close, volume).
- **Tabla `signals`:** Predicciones generadas (timestamp, asset_id, signal_type, confidence).
