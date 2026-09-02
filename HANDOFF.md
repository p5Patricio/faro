# Traspaso de Sesión — Faro

Fecha: 2026-08-29. Este documento es para el próximo agente/sesión que continúe este
proyecto sin el contexto de la conversación anterior. Léelo completo antes de tocar
código. Está escrito para que alguien (o algo) sin memoria de lo anterior pueda retomar
sin re-descubrir nada de lo que ya se investigó y decidió.

## 1. Qué es Faro

Plataforma MLOps local de señales de inversión (Python/FastAPI + React). Convierte datos
de mercado en señales auditables `BUY`/`SELL`/`HOLD` con confianza, riesgo y trazabilidad
completa del modelo. **No es asesoría financiera** — filosofía explícita del proyecto:
evidencia y supervisión humana antes que automatización ciega. Ver `README.md` para la
arquitectura completa; no lo duplico acá.

- Repo GitHub: `github.com/p5Patricio/faro` (recién renombrado desde
  `plataforma-ia-inversiones`, con redirect automático).
- Carpeta local: `C:\Users\Usuario\Documents\Faro` (recién renombrada desde
  `plataforma-ia-inversiones`).
- Rama activa: `codex/sdd-professional-improvements`.
- **39 commits por delante de `origin`, nada pusheado todavía.** El usuario no pidió push
  en ningún momento de esta sesión — no asumas que hay que hacerlo, preguntale primero.

## 2. Qué se hizo en la sesión anterior (resumen cronológico)

Todo esto se hizo con SDD (Spec-Driven Development, ver `openspec/`), en modo automático,
con verificación adversarial real en cada cambio (no sello de goma — cada `sdd-verify`
encontró hallazgos reales y se cerraron antes de archivar).

### 2.1 Migración completa de Supabase a PostgreSQL local
**Archivado**: `openspec/changes/archive/2026-08-26-local-postgres-migration/`

Se eliminó Supabase por completo (base de datos, auth, storage). Reemplazado por:
- PostgreSQL 18.4 local, dos bases: `ia_inversiones` (real) y `ia_inversiones_test` (tests).
- `collector/local_repository.py` — repositorio psycopg3 con los ~30 métodos que tenía el
  repositorio de Supabase, mismo contrato.
- `db/migrations/0001` a `0004` — esquema portado (sin RLS, sin `auth.*`).
- Auth eliminado por completo — un solo operador local, perfiles de riesgo por
  scope (`default`/`asset_class`/`ticker`), sin usuarios.
- `brain/artifacts.py` — modelos `.joblib` en filesystem local (`models/`) en vez de
  Supabase Storage.
- `ops/run_local_scheduler.py` + `ops/register_local_jobs.ps1` — reemplaza el GitHub
  Actions que corría contra Supabase (estaba fallando todos los días antes de esta sesión).
  **El usuario tiene el comando para registrar las tareas de Windows Task Scheduler pero
  puede que todavía no lo haya corrido** (yo no lo puedo ejecutar — modificar configuración
  del sistema operativo está fuera de lo que un agente hace). Verificalo:
  ```powershell
  schtasks /Query /TN "Faro\DailyOperationalCycle" /V /FO LIST
  ```
  Si no existe, el comando para registrarlas es `.\ops\register_local_jobs.ps1` desde
  PowerShell (no admin) en la raíz del repo.

### 2.2 Bot de Telegram para notificaciones
**Archivado**: `openspec/changes/archive/2026-08-26-telegram-notifications/`

- `ops/telegram_notifier.py` — cliente delgado (long-polling, no webhooks — imposible
  detrás de NAT sin exponer el equipo), redacción de token verificada de verdad (se forzó
  un error real y se confirmó que el token nunca aparece en ningún lado).
- `ops/notification_dispatch.py` — 4 disparadores: fallo de job, cambio de señal
  (BUY→BUY no notifica, HOLD→BUY sí), degradación de modelo, datos vencidos. Cooldown y
  dedupe son mecanismos separados, ambos probados.
- **Ya está funcionando de punta a punta**: el usuario tiene `TELEGRAM_BOT_TOKEN` y
  `TELEGRAM_CHAT_ID` reales en su `.env`, y confirmó haber recibido un mensaje de prueba
  real durante la sesión.

### 2.3 Rebranding completo a "Faro"
- Repo GitHub y carpeta local renombrados (ver arriba).
- Logo nuevo (faro/lighthouse) integrado en `ui/public/brand/faro-logo.png`, referenciado
  en `README.md` y `ui/src/App.tsx`.
- 18+ archivos de documentación actualizados (README, CONTRIBUTING, SECURITY, planes, etc.)
  para decir "Faro" en vez de "IA Inversiones"/"Plataforma IA Inversiones".
- **`ESTADO_PROYECTO.md` quedó desactualizado** — el rebrand solo tocó el nombre, no el
  contenido. Todavía dice "cargar Supabase", fecha "2026-07-12", y no menciona nada de lo
  hecho en esta sesión (Postgres local, Telegram, universo S&P 100). Convendría
  actualizarlo pronto — no es código, es puramente cosmético/documental, bajo riesgo.

### 2.4 Limpieza de basura del proyecto
- Eliminado: `GEMINI.md` (instrucciones de agente Gemini CLI, desactualizadas y
  engañosas — mencionaba Supabase y una tabla `signals` ya eliminada), caché de Supabase
  CLI, `__pycache__`, `.pytest_cache`, `.benchmarks`, logs/reportes viejos,
  `package.json`/`package-lock.json`/`node_modules` raíz (solo existían para el CLI de
  Supabase).
- `models/` vaciado — contenía modelos `.joblib` de julio, obsoletos con el pipeline y
  esquema nuevos. **La carpeta está vacía ahora, no hay ningún modelo entrenado en el
  sistema todavía.**
- `CONTRIBUTING.md` se mantuvo (no molesta, aunque el proyecto sea de un solo operador).
- Se encontró y arregló un bug real de aislamiento de tests (`tests/test_migrate.py`):
  `resolve_dsn()` llama `load_dotenv()` sin argumento, que nunca se había disparado porque
  hasta esta sesión **nunca existió un `.env` real** en ningún test run anterior. Al crear
  el `.env` real del usuario, dos tests empezaron a fallar porque el archivo real
  "contaminaba" el escenario que simulaba "sin configuración". Arreglado con
  `monkeypatch.setattr("db.migrate.load_dotenv", lambda *a, **k: False)` en esos dos tests.

### 2.5 Base compartida de inteligencia financiera
**Archivado**: `openspec/changes/archive/2026-08-29-financial-intelligence-expansion/`

Este es el trabajo más grande y el más relevante para lo que sigue. Investigación previa
(ver `openspec/changes/archive/2026-08-29-financial-intelligence-expansion/exploration.md`)
cubrió 4 áreas: análisis fundamental, "copy trading" institucional, Telegram (ya hecho,
sección 2.2) y finanzas personales + Gemini. Se decidió dividir el trabajo en **7 cambios
SDD hermanos**, de los cuales **solo se completó la base compartida** (charter/foundation).
Los otros 6 quedan por hacer — ver sección 4.

Lo que sí quedó implementado y verificado:
- `config/universe.sp100.json` — **101 tickers del S&P 100**, fuente citada (Wikipedia,
  recuperado 2026-08-28, membresía fechada 2025-09-22 — anotado honestamente, no
  falseado como "de hoy"). `HON` verificado contra SEC EDGAR después de que la fuente
  original tenía un error de scraping (`HONA`).
- **Política de objetivos acotada** (`brain/retraining_job.py`): ampliar el universo
  ingerido a ~100 activos **no** amplía qué se entrena por defecto. Sigue siendo
  `config/targets.core.json` = `["BTC-USD", "ETH-USD", "AAPL", "MSFT"]` (idéntico a antes).
  Si se supera `max_auto_targets=8` sin pasar `--tickers`/`--targets-file` explícito,
  **falla con error claro** en vez de entrenar sobre todo silenciosamente. Esto existe
  porque ampliar sin este límite multiplicaría el tiempo de reentrenamiento hasta ~625x
  (25x más objetivos × 25x más datos por fit en scope global).
- `collector/providers/sec_edgar_client.py` — cliente de la API de la SEC con límite de
  10 req/s, requiere `SEC_USER_AGENT` (falla fuerte sin él, nunca silencioso), auditoría
  de cada llamada en `ingestion_runs` (incluida `max_filed_date` — esto fue el único
  hallazgo CRÍTICO real de la verificación, y se cerró).
- `collector/local_repository.py` — nuevas tablas `asset_identifiers` (mapeo
  ticker→CIK/CUSIP/etc.) e `ingestion_runs` (auditoría de cada fetch externo).
  Migración `db/migrations/0005_shared_ingestion.sql`.
- `brain/features.py` — punto de resolución de feature-sets por `assets.asset_class`
  (`feature_columns_for_set(..., asset_class=...)`), **vacío por ahora** — los 6 cambios
  hermanos son los que van a registrar overlays reales (fundamentales para acciones,
  perfil de fondo para ETFs, on-chain para cripto). Hoy con el mapa vacío, todo cae al
  spine `technical_v2` de siempre, sin romper nada existente.
- `GET /api/universe` — nuevo endpoint, expone el disclosure de sesgo de supervivencia.

**Importante — esto NUNCA se corrió con datos reales.** El diseño explícitamente dice "no
reentrenar con el universo ampliado en el mismo cambio que lo agrega" — así que:
- La base de datos sigue **vacía** (0 filas en `assets`, `prices`, todo). Nunca se hizo un
  backfill real del universo de 101 tickers.
- Los valores `max_auto_targets=8` / `max_global_scope_assets=12` son **propuestos, no
  medidos**. El diseño pedía medir el tiempo real de reentrenamiento antes/después y
  ajustar si hace falta — esto está documentado como "Pendiente" en el README, no
  inventado, pero sigue pendiente de verdad.

## 3. Estado verificado ahora mismo

```
337 tests pasando, 0 fallas (contra Postgres real, no mockeado)
```

Para correr los tests vos mismo (las credenciales están en tu `.env`, exportalas así):
```bash
export LOCAL_DATABASE_URL='postgresql://postgres:<tu-password>@localhost:5432/ia_inversiones'
export TEST_DATABASE_URL='postgresql://postgres:<tu-password>@localhost:5432/ia_inversiones_test'
cd "C:/Users/Usuario/Documents/Faro"
py -3.14 -m pytest -q
```
La contraseña real está en `.env` (gitignored) — no la repito acá. Si necesitás leerla sin
imprimirla directo, `python-dotenv` ya la carga si corrés cualquier script del proyecto.

**Pero "337 tests pasan" no es lo mismo que "la app funciona con datos reales" —** y el
usuario pidió explícitamente una base *funcionando*, no solo testeada. Ver el plan en la
sección 5, es el primer bloque de trabajo.

## 4. Lo que falta (roadmap)

### 4.1 Los 6 cambios SDD hermanos de la expansión financiera
Todos dependen de `financial-intelligence-expansion` (ya archivado, listo para construir
encima). Orden de dependencia sugerido por la propia propuesta original
(`openspec/changes/archive/2026-08-29-financial-intelligence-expansion/proposal.md`):

1. **`fundamental-analysis`** — F-Score, Z-Score, rentabilidad bruta desde SEC EDGAR
   XBRL, indexado por `filed_date` (NUNCA `period_end` — es la regla de oro contra el
   sesgo de anticipación que se investigó a fondo). Solo aplica a acciones.
2. **`institutional-consensus`** — no es "copy trading" real (imposible con datos
   públicos: 13F tiene 45 días de retraso y omite posiciones cortas). Es un "Consenso
   Institucional" + alertas de compras de insiders (Form 4, T+2 días, sí es oportuno).
3. **`personal-finance`** — registro de gastos/compras propio del usuario, modelo
   single-entry con `transfer_group_id`, separado estrictamente de paper trading.
4. **`asset-class-profile-overlays`** — perfil de ETFs (expense ratio, holdings) y
   cripto (supply, métricas on-chain), registrándose en el mapa vacío de
   `brain/features.py` que ya existe.
5. **`gemini-optional-assist`** — Gemini SOLO para extracción cacheada (arriba del
   pipeline) o explicación en lenguaje natural (abajo, de una decisión ya tomada).
   **Nunca genera la señal directamente** — no es reproducible, no se puede backtestear
   sin trampa. Esta regla es dura, no es una sugerencia.
6. **`dependency-pinning`** — `requirements.txt` no tiene NINGUNA versión fijada. Riesgo
   real: los modelos `.joblib` pueden fallar al cargar si sklearn cambia de versión entre
   entrenamiento e inferencia. Es mecánico, probablemente no necesita SDD completo.

Para arrancar cualquiera de estos: `/sdd-new <nombre-del-cambio>` o pedile a Claude que
siga el mismo patrón que usó esta sesión (exploración si hace falta → propuesta → spec →
diseño → tareas → apply en lotes paralelos cuando no hay archivos compartidos → verify
adversarial real → archive).

### 4.2 Endurecimiento pendiente (identificado al principio de la sesión, nunca hecho)
- **CORS mal configurado**: `app_config.py` default `cors_origins=("*",)` +
  `allow_credentials=True` en `api/main.py` — combinación inválida por spec e insegura.
- **Sin rate limiting** en los endpoints públicos de la API.
- **Logging estructurado** — hoy cada endpoint hace `except (RuntimeError, ...)` amplio y
  cae a modo demo; sin logs estructurados es difícil saber si algo falló de verdad.
- **Cobertura de tests de API y frontend** — el núcleo de ML está bien testeado, la capa
  API y el frontend casi no.

### 4.3 Housekeeping menor
- `ESTADO_PROYECTO.md` desactualizado (sección 2.3).
- `openspec/changes/professional-improvements-foundation/` — cambio SDD viejo, completo
  pero **nunca archivado**. No es parte de esta sesión, es anterior. Se puede archivar
  cuando quieras (`sdd-archive` directo, ya tiene todas las fases hechas).
- 4 warnings de seguridad de severidad alta en `npm audit` (frontend) — mencionado, no
  resuelto.

## 5. Plan sugerido para la próxima sesión

**Prioridad 1 — llevar la app a un estado realmente funcionando (esto es lo que pidió el
usuario explícitamente antes de seguir con features nuevas):**

1. Confirmar que el usuario registró las tareas de Windows Task Scheduler (sección 2.1).
2. Backfill real de datos: correr el collector contra el universo ampliado —
   ```bash
   py -3.14 -m collector.main --assets-file config/universe.sp100.json --start 2020-01-01
   ```
   (esto puede tardar — son 101 tickers de yfinance). Considerar empezar con un subconjunto
   chico primero para no comerse el rate limit de yfinance.
3. Materializar features/labels, entrenar al menos un modelo real, correr inferencia —
   seguir el flujo que ya documenta `README.md` (`collector.run_market_data_job`,
   `brain.run_retraining_job`, `brain.run_inference_job`).
4. Con eso corrido, **medir el tiempo real de reentrenamiento** antes/después de la
   ampliación (lo que quedó pendiente en la sección 2.5) y ajustar `max_auto_targets`/
   `max_global_scope_assets` si los números no acompañan la estimación original.
5. Levantar API + UI (`uvicorn api.main:app` / `cd ui && npm run dev`) y confirmar
   visualmente que el dashboard muestra señales reales, no solo demo data.
6. Forzar una notificación real de Telegram desde el flujo real (no el script de prueba
   manual que se usó esta sesión) para confirmar el circuito completo end-to-end.

**Prioridad 2 — una vez que la base esté demostrada funcionando con datos reales:**

7. Retomar los 6 cambios hermanos de la sección 4.1, en el orden sugerido (fundamental
   analysis primero, tiene el mayor valor de señal).
8. Intercalar el endurecimiento de la sección 4.2 cuando convenga — `dependency-pinning`
   en particular es barato y de alto valor, podría ir temprano.

## 6. Convenciones y detalles operativos que hay que saber

- **SDD**: artifact store = `openspec` (archivos en el repo, no solo memoria). Cadena de
  PRs: `stacked-to-main`. Estrategia de entrega: `ask-on-risk` (para, pregunta si un PR se
  pasa mucho del presupuesto de 400 líneas). Estos fueron acuerdos de ESTA sesión — una
  sesión nueva probablemente tenga que volver a confirmarlos (es un hard gate del
  workflow SDD), pero mantené la misma convención salvo que el usuario pida otra cosa.
- **Git**: nunca `git add -A` en este proyecto — siempre paths explícitos. Se comprobó
  necesario porque varios agentes trabajaron en paralelo sobre el mismo working tree.
- **Password de Postgres**: el usuario la compartió una vez en el chat al principio de la
  sesión anterior. Está en su `.env` real ahora. No hace falta que la vuelva a compartir.
- **Harness**: no se puede usar `Read`/`Edit`/`Write` directo sobre archivos `.env*` — pero
  `Bash` con heredoc (`cat > .env <<'EOF' ... EOF`) o `cmp -s` (para comparar sin mostrar
  contenido) sí funcionan. Usalo si necesitás tocar `.env`.
- **`load_dotenv()`**: si corrés un script Python vía heredoc/stdin (`py -3.14 - <<'EOF'`),
  `load_dotenv()` sin argumento falla con `AssertionError` (no tiene frame con
  `__file__`). Pasale la ruta explícita: `load_dotenv(".env")`.
- **Modelos de agente**: cuando trabajes con sub-agentes SDD, este proyecto usa
  `sonnet` para explore/spec/tasks/apply/verify, `opus` para propose/design, `haiku` para
  archive — según la tabla de asignación de modelos del workflow SDD compartido.
- No hay nada corriendo en background ahora mismo — cada sub-agente de la sesión anterior
  terminó y commiteó (o quedó documentado si algo se cortó por límite de sesión).
