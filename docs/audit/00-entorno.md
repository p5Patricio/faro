# Fase 0 — Orientación y entorno de ejecución

Fecha: 2026-10-03. Rama de trabajo: `claude/gallant-fermat-q1h432` (desde `main` @ d04c655).

## Qué se leyó

- `AGENTS.md` (parcialmente desactualizado: sí existe el runner `python -m db.migrate`, y el CI lo usa).
- `odd/tasks/faro-macro-finance-expansion.md` (decisiones D1-D16, slices S1-S9, estado y diferidos).
- `.github/workflows/ci.yml`, `requirements.txt`, `tests/conftest.py`, `db/migrations/` (la más alta es `0015_asset_market_caps.sql`; la siguiente libre es `0016`).

## Entorno levantado (contenedor Linux efímero en la nube)

| Componente | Versión aquí | Versión en CI | Nota |
|---|---|---|---|
| Python | 3.13 (venv con `uv`) | 3.14 | Python 3.14 solo estaba disponible como `3.14.0rc2`, y pydantic 2.13.3 falla al recolectar `tests/test_api.py` con un `AssertionError` en `eval_type_backport` sobre esa *release candidate*. Con 3.13 todo pasa. No es un bug de Faro; el CI (3.14 estable) es la referencia. |
| Node | 22.22 | 24 | Lint, Vitest y build pasan con 22. |
| Postgres | 16 (cluster local, `ia_inversiones_test`) | 16 (servicio) | `TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/ia_inversiones_test`. |
| `torch` / `transformers` | **no instalados** | instalados | Se importan de forma perezosa; los tests no los necesitan. |

## Resultado de las suites (una sola corrida, estado de `main`)

- Backend: `python -m pytest -q` → **943 passed** en 19.5 s (1 warning de deprecación de `httpx` en `starlette.testclient`).
- Frontend (`ui/`): `npm ci`; `npm run lint` limpio; `npm test -- --run` → **141 passed** (19 archivos); `vite build --outDir <scratch>` ok, con aviso de chunk > 500 kB (`HeatmapDashboard` 550 kB, ECharts).
- `pip-audit` sobre `requirements.txt` sin `torch`/`transformers`: **sin vulnerabilidades conocidas**. Con ellos: `transformers 4.57.1` y `torch 2.9.0` tienen avisos PYSEC (ver auditoría, hallazgo S-5).
- `npm audit --omit=dev`: **0 vulnerabilidades**.

## Qué sí y qué no se puede ejecutar aquí

| Puede | No puede |
|---|---|
| Suites backend y frontend contra un Postgres efímero | Acceder a tu PC, tu base real, `.env` o tokens (`BANXICO_TOKEN`, `FINNHUB_API_KEY`, `TELEGRAM_*`) |
| Migraciones contra la base de pruebas (vía `conftest.py`) | Ejecutar `ops/*.ps1`, Task Scheduler o PowerShell (revisión solo estática) |
| Búsquedas web (herramientas de búsqueda/lectura del agente) | Peticiones HTTP desde el contenedor a Yahoo, FRED, Banxico, SAT o DOF: `curl` devuelve error de conexión (política de red del entorno). Por eso **ningún proveedor de datos se verificó en vivo aquí**; cualquier cifra de mercado que aparezca es NO VERIFICADA salvo que se cite una fuente web consultada. |
| Abrir PRs contra `main` y dejar que el CI (Python 3.14 + Postgres 16) los valide | Hacer merge (no se hará: lo revisas tú) |

## Cómo reproducirlo

```bash
service postgresql start
psql -U postgres -c "CREATE DATABASE ia_inversiones_test;"
uv venv -p 3.13 .venv && uv pip install -r requirements.txt   # opcional: sin torch/transformers
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/ia_inversiones_test APP_ENV=test python -m pytest -q
cd ui && npm ci && npm run lint && npm test -- --run && npx vite build --outDir /tmp/dist
```
