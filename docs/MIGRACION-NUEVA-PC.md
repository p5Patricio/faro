# Mover Faro a otra computadora

> Guía paso a paso. Está pensada para no perder nada: la base de datos se restaura y se **verifica**
> contra un inventario (tablas, filas y huellas) hecho en la computadora de origen.

## Qué viaja y cómo

| Qué | Cómo llega a la computadora nueva | ¿Va en GitHub? |
|---|---|---|
| Código y documentación | `git clone` | Sí |
| **Base de datos** (tus finanzas y el histórico de mercado) | Paquete de traspaso (`db\faro.dump`) | **No**: es información financiera personal, el repositorio es público y el respaldo rebasa el límite de 100 MB de GitHub |
| **Modelos entrenados** (`models\`, ~500 MB) | Paquete de traspaso | No. Sin ellos la inferencia falla con `artifact_not_found` (la base guarda rutas relativas, así que basta copiar la carpeta) |
| Tus documentos (`private\`: CFDI, estados de cuenta, constancias, contexto personal) | Paquete de traspaso | No |
| Memoria del agente de IA (Engram, proyecto `faro`) | Paquete de traspaso (`engram-faro.json`) | No |
| **Secretos** (`.env`: contraseña de la base, token de Telegram, claves) | **Los llevas tú a mano** (USB o gestor de contraseñas) | No, y el paquete **nunca** lo incluye |

El paquete se arma en una carpeta local que **no** está sincronizada con ninguna nube. Muévelo con una USB.
Contiene tu información financiera completa: trátalo como tal y bórralo de forma segura cuando termines.

## 1. En la computadora de origen: armar el paquete

Desde la raíz del repositorio, en PowerShell normal (no administrador):

```powershell
.\ops\prepare_transfer.ps1 -Destination C:\Traspaso-Faro
```

Hace, en este orden: respaldo nuevo de la base (`db\`) con su inventario `db\manifest.json`; copia de
`models\`, `artifacts\`, `reports\` y `private\`; exportación de la memoria de Engram; y `SHA256SUMS.txt`
con la huella de cada archivo. Es **repetible**: vuelve a correrlo justo antes del corte para llevarte los
últimos datos.

## 2. El día del corte (para no perder datos)

La base de origen sigue cambiando (tareas diarias, el bot de Telegram, lo que captures). Para que nada se
quede atrás:

1. Detén la app en la computadora vieja: `.\ops\run_local_app.ps1 -Stop`.
2. Deshabilita las tareas de Faro en la vieja (así no escribe en una base que ya no usarás):
   `Get-ScheduledTask -TaskPath '\Faro\' | Disable-ScheduledTask` y, aparte,
   `Disable-ScheduledTask -TaskName FaroFundamentalIngestionWeekly`.
   `Faro\LocalAppServers` se creó con permisos de administrador: ese hay que deshabilitarlo desde PowerShell
   como administrador.
3. **Solo una computadora debe hablar con el bot de Telegram.** Si las dos lo consultan, los mensajes los
   recibe quien llegue primero y el gasto queda en la base equivocada.
4. Corre otra vez `prepare_transfer.ps1`: ese es el paquete definitivo.

## 3. En la computadora nueva: instalar

Con `winget` (PowerShell normal):

```powershell
winget install --id Git.Git --exact
winget install --id GitHub.cli --exact
winget install --id Python.Python.3.14 --exact
winget install --id OpenJS.NodeJS.LTS --exact      # Node 24; "OpenJS.NodeJS" a secas instala la 26
winget install --id PostgreSQL.PostgreSQL.18 --exact
```

- **PostgreSQL 18** (misma versión mayor): el respaldo lo hizo `pg_dump` 18 y `pg_restore` debe ser 18 o
  superior. Anota la contraseña del usuario `postgres` que elijas en la instalación.
- Instala también Claude Code (o el agente que uses) y Engram si quieres conservar la memoria del proyecto.
- Opcional: `winget install --id Google.GoogleDrive --exact` si quieres la copia de respaldos en la nube.
- Abre una terminal nueva para que el PATH se actualice y inicia sesión en GitHub: `gh auth login`.

## 4. Clonar e instalar dependencias

```powershell
git clone https://github.com/p5Patricio/faro
cd faro
py -3.14 -m pip install -r requirements.txt
cd ui; npm ci; cd ..
```

## 5. Traer el paquete y verificarlo

Copia la carpeta `Traspaso-Faro` de la USB a `C:\Traspaso-Faro` y comprueba que nada se dañó (no debe imprimir nada):

```powershell
cd C:\Traspaso-Faro
Get-Content SHA256SUMS.txt | ForEach-Object {
  $hash, $path = $_ -split '  ', 2
  if ((Get-FileHash $path -Algorithm SHA256).Hash -ne $hash) { "FALLA: $path" }
}
cd <carpeta-del-repo>
```

## 6. Crear el `.env`

```powershell
Copy-Item docs\env.template .env
```

Ábrelo y completa **a mano** lo que traes del `.env` viejo (token de Telegram, `SEC_USER_AGENT`, claves). En
`LOCAL_DATABASE_URL` pon el usuario y la contraseña de PostgreSQL de **esta** computadora, base `ia_inversiones`.
La base de pruebas se crea una vez (la necesita `pytest`):

```powershell
& "C:\Program Files\PostgreSQL\18\bin\createdb.exe" -U postgres ia_inversiones_test
```

## 7. Restaurar la base de datos y verificarla

```powershell
py -3.14 -m ops.transfer restore `
  --dump C:\Traspaso-Faro\db\<carpeta-del-respaldo>\faro.dump `
  --manifest C:\Traspaso-Faro\db\manifest.json `
  --pg-restore "C:\Program Files\PostgreSQL\18\bin\pg_restore.exe"
```

Crea la base `ia_inversiones` (se niega a restaurar encima de una que ya tenga tablas), carga el respaldo y la
compara con el inventario. Debe terminar con **"OK"** y el número de tablas que coinciden. Si dice que algo
difiere, **no sigas**: avisa y repite con un paquete nuevo. Después:

```powershell
py -3.14 -m db.migrate --dry-run     # debe imprimir: No pending migrations.
```

## 8. Devolver modelos, documentos y memoria

```powershell
robocopy C:\Traspaso-Faro\models    models    /E
robocopy C:\Traspaso-Faro\private   private   /E
robocopy C:\Traspaso-Faro\artifacts artifacts /E
robocopy C:\Traspaso-Faro\reports   reports   /E
engram import C:\Traspaso-Faro\engram-faro.json
```

(`robocopy` devuelve códigos de 0 a 7 cuando todo salió bien.) `private\` queda ignorada por Git: no la subas.

## 9. Registrar las tareas programadas

En PowerShell **normal** (no administrador), desde la raíz del repo:

```powershell
.\ops\register_local_app.ps1
.\ops\register_local_jobs.ps1
.\ops\register_finance_bot.ps1
.\ops\register_backup_task.ps1
.\ops\register_fundamental_ingestion_weekly.ps1
.\ops\run_local_app.ps1
```

Todas se lanzan ocultas (sin ventanas de terminal) y con "ejecutar si se omitió" y "permitir con batería". El
respaldo diario usa `FARO_BACKUP_DIR` del `.env`.

## 10. Comprobación final

- `py -3.14 -m pytest -q` y, en `ui\`, `npm run lint`, `npm test`, `npm run build`.
- Abre `http://127.0.0.1:47319`: en **Inversiones** deben verse tus posiciones y en **Finanzas** tus movimientos.
- `GET http://localhost:47318/api/health` debe responder `ok`.
- Pídele al agente nuevo que lea `AGENTS.md` y `private\CONTEXTO-PERSONAL.md` antes de empezar.

## 11. Después del corte

- Conserva el paquete y la computadora vieja unos días, hasta confirmar que todo funciona.
- Borra el paquete (USB y `C:\Traspaso-Faro`) cuando ya no lo necesites: tiene tus finanzas completas.
- Si algo falla: `artifact_not_found` = falta copiar `models\`; `migration_checksum_mismatch` = no deberías verlo
  (el checksum ya ignora los saltos de línea de Windows); `pg_restore` de versión anterior = instala PostgreSQL 18.
