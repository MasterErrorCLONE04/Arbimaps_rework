# ArbitriumSAS — Entorno de Desarrollo Dockerizado 🚀

Este repositorio contiene el backend de **ArbitriumSAS**, una API construida con **FastAPI** y desplegada mediante **Docker**. Esta guía documenta **paso a paso** cómo configurar el entorno de desarrollo desde cero en Windows utilizando **Docker Desktop + WSL2 + Ubuntu**, desde la descarga del repositorio hasta tener el proyecto corriendo en local.

---

## 📐 Arquitectura del Entorno

| Componente | Rol |
|---|---|
| **Ubuntu / WSL2** | El proyecto vive físicamente aquí (en `/home/usuario`). Es mucho más rápido. |
| **Windows** | Se edita desde aquí usando VSCode con la extensión **WSL**. |
| **Docker Desktop** | Usa WSL2 como motor Linux nativo. |
| **Contenedores** | Se ejecutan con acceso directo al sistema de archivos de Linux. |

> [!TIP]
> Trabajar dentro del sistema de archivos de Ubuntu (`/home/...`) evita errores de latencia en la base de datos y hace que `docker compose` sea hasta **10 veces más rápido**.

---

## 🏁 Paso 1: Descargar el Proyecto del Repositorio

Lo primero es descargar el código fuente del proyecto en tu máquina Windows.

1.  Abre una terminal (PowerShell o CMD) en la carpeta donde quieras guardar el proyecto (ej. `Downloads`, `Documents`, `Desktop`).
2.  Clona el repositorio:
    ```powershell
    git clone <URL_DEL_REPOSITORIO>
    ```
3.  Entra a la carpeta del proyecto:
    ```powershell
    cd Develop/ubuntu
    ```

> [!NOTE]
> Si no tienes Git instalado en Windows, descárgalo desde [git-scm.com/download/win](https://git-scm.com/download/win). Esto habilitará los comandos `git clone`, `git pull`, `git push` en PowerShell.

---

## 🔧 Paso 2: Configurar el Archivo `.env` en Windows

Antes de mover el proyecto a Linux, configura las variables de entorno directamente desde Windows:

1.  Dentro de la carpeta `ubuntu/`, busca el archivo `.env.example`.
2.  Crea una copia y renómbrala a `.env`:
3.  Abre el archivo `.env` con un editor de texto (Notepad, VS Code, etc.) y configura los valores necesarios (credenciales de base de datos, configuraciones de Box, etc.).

---

## 💾 Paso 3: Obtener la Base de Datos

El líder del proyecto te proporcionará un archivo SQL (`.sql`) con el volcado de la base de datos.

1.  Descarga el archivo SQL y guárdalo en una ruta conocida de tu disco `C:` (ej. `C:\Users\TuUsuario\Downloads\SERVIDOR_AWS_FREE_08-05.sql`).
2.  **No lo coloques dentro de la carpeta del proyecto**, ya que supera los **100MB** y Docker no puede cargarlo automáticamente.

---

## 🐧 Paso 4: Instalar WSL2 (Windows Subsystem for Linux)

1.  Abre **PowerShell como administrador** (clic derecho → "Ejecutar como administrador").
2.  Ejecuta el siguiente comando:
    ```powershell
    wsl --install
    ```
3.  **Reinicia tu computadora** cuando el sistema lo solicite.

---

## 👤 Paso 5: Configurar Ubuntu en WSL

Después de reiniciar, debes configurar Ubuntu por primera vez:

1.  Abre una terminal (PowerShell o CMD) y ejecuta:
    ```powershell
    wsl -d Ubuntu
    ```
2.  Espera a que termine la instalación inicial de Ubuntu (puede tardar unos minutos).
3.  Cuando se te solicite, ingresa un **nombre de usuario** (en minúsculas, sin espacios, ej. `dev`):
    ```
    Enter new UNIX username: dev
    ```

> [!IMPORTANT]
> El nombre de usuario de Linux **debe estar en minúsculas**.
>
> ✅ Correcto: `dev`
>
> ❌ Incorrecto: `Dev` o `DEV`

4.  Ingresa una **contraseña** y confírmala:
    ```
    New password: ********
    Retype new password: ********
    ```

> [!NOTE]
> No verás los caracteres en pantalla al escribir la contraseña. Esto es normal por seguridad. Solo escribe y presiona Enter.

5.  Una vez dentro de la terminal de Linux, actualiza el sistema:
    ```bash
    sudo apt update && sudo apt upgrade -y
    ```

---

## 🐳 Paso 6: Instalar Docker Desktop

1.  **Opción recomendada**: Descarga e instala **Docker Desktop** desde la [Microsoft Store](https://apps.microsoft.com/store/detail/docker-desktop/9P9S3TZS6SFF) (facilita las actualizaciones automáticas). También puedes descargarlo desde su [sitio oficial](https://www.docker.com/products/docker-desktop/).
2.  Durante la instalación, asegúrate de que la opción **"Use the WSL 2 based engine"** esté activada.
3.  🔄 Reinicia el computador si es solicitado.

---

## 🔗 Paso 7: Activar WSL y Ubuntu en Docker Desktop

1.  Abre **Docker Desktop**.
2.  Ve a **Settings** (ícono de engranaje).
3.  En **Settings → General**, verifica que esté activado:
    *   ✅ `Use WSL 2 based engine`
4.  En el menú lateral, selecciona **Resources → WSL Integration**:
    *   Activa **"Enable integration with my default WSL distro"**.
    *   Activa el switch de tu distribución **Ubuntu**.
5.  Haz clic en **"Apply & Restart"**.

### Verificar Docker en Ubuntu

Abre Ubuntu desde PowerShell:
```powershell
wsl -d Ubuntu
```

Verifica que Docker esté disponible:
```bash
docker --version
```

Debe mostrar algo como: `Docker version XX.X.X`

---

## 📦 Paso 8: Copiar el Proyecto de Windows a Ubuntu (WSL)

> [!IMPORTANT]
> Para el mejor rendimiento, el proyecto **DEBE** residir dentro del sistema de archivos de Linux (`/home/...`), **NO** en una carpeta de Windows (`/mnt/c/...`).

1.  Abre una terminal y entra a Ubuntu:
    ```powershell
    wsl -d Ubuntu
    ```
2.  Copia la carpeta completa del proyecto desde Windows hacia tu home de Linux (ajusta la ruta según donde clonaste el repositorio en el Paso 1):
    ```bash
    # Ejemplo: si clonaste en el Escritorio
    cp -r /mnt/c/Users/<TuUsuario>/Desktop/Develop ~/
    ```
    > La carpeta del repositorio ya se llama `Develop`, por lo que al copiarla quedará en `~/Develop`.
3.  Verifica que los archivos se copiaron correctamente:
    ```bash
    ls ~/Develop/ubuntu/
    ```

### 💡 Alternativa: Clonar directamente en Ubuntu

Si prefieres clonar directamente dentro de Ubuntu (sin pasar por Windows):
```bash
cd ~/Develop
git clone <URL_DEL_REPOSITORIO>
```

---

## 🚀 Paso 9: Levantar el Proyecto con Docker

1.  Navega a la carpeta del proyecto dentro de Linux:
    ```bash
    cd ~/Develop/ubuntu
    ```
2.  Ejecuta Docker Compose para construir y levantar los contenedores:
    ```bash
    docker compose up --build
    ```
3.  Espera a que los contenedores se descarguen, construyan e inicien. Verás los logs en pantalla.
4.  Una vez que veas que la API está corriendo, presiona **Ctrl + C** para detener los logs en la terminal.
5.  Ahora levanta los contenedores en segundo plano para liberar la terminal:
    ```bash
    docker compose up -d
    ```

> [!NOTE]
> Al estar dentro de `/home`, Docker tiene acceso nativo al disco, eliminando errores de "Workspace" o latencia en PostGIS.

---

## 🗄️ Paso 10: Importar la Base de Datos Manualmente

La base de datos supera los **100MB**, por lo que Docker no puede cargarla automáticamente al iniciar. Se debe importar de forma manual:

> [!IMPORTANT]
> Los contenedores de Docker **deben estar encendidos** para realizar la importación.

1.  Desde la terminal de Ubuntu, ejecuta el siguiente comando (reemplaza `<TuUsuario>` con tu usuario de Windows y el nombre del archivo SQL con el que te proporcionó el líder):
    ```bash
    cat "/mnt/c/Users/<TuUsuario>/Downloads/SERVIDOR_AWS_FREE_08-05.sql" | docker exec -i arbitriumsas-db psql -U postgres -d programacion
    ```
    > Este comando lee el archivo SQL directamente desde la carpeta de Windows y lo inyecta en el contenedor de la base de datos.
2.  Espera a que termine la importación (puede tardar varios minutos dependiendo del tamaño del archivo).

---

## ✅ Paso 11: Verificar que Todo Funciona

Una vez completados todos los pasos anteriores, el proyecto estará corriendo. Verifica abriendo estas URLs en tu navegador:

| Servicio | URL |
|---|---|
| Panel de Control | [http://localhost:8000/](http://localhost:8000/) |
| Documentación API (Swagger) | [http://localhost:8000/docs](http://localhost:8000/docs) |
| Health Check | [http://localhost:8000/health](http://localhost:8000/health) |

Para editar el código, abre una terminal en la carpeta del proyecto dentro de Linux y ejecuta:
```bash
code .
```
Esto abrirá **VS Code** conectado directamente a WSL, permitiéndote editar los archivos de Linux con la velocidad nativa de Windows.

---

## 🔄 Flujo Diario de Trabajo

Una vez configurado el entorno, el día a día es sencillo:

### Abrir entorno
1.  Abrir **Docker Desktop** en Windows.
2.  Abrir Ubuntu desde PowerShell:
    ```powershell
    wsl -d Ubuntu
    ```
3.  Entrar al proyecto:
    ```bash
    cd ~/Develop/ubuntu
    ```
4.  Levantar contenedores:
    ```bash
    docker compose up -d
    ```

### Trabajar normalmente
-   Editar archivos desde **VSCode** en Windows (usando `code .` desde la terminal de Ubuntu).
-   Docker reflejará automáticamente los cambios gracias a los volúmenes montados.

### Apagar entorno
```bash
docker compose down
```

### Actualizar el proyecto
```bash
git pull
```

---

## 🐳 Comandos Útiles de Referencia

| Acción | Comando |
| :--- | :--- |
| **Entrar a Ubuntu desde Windows** | `wsl -d Ubuntu` |
| **Ir al proyecto** | `cd ~/Develop/ubuntu` |
| **Ver logs de la API** | `docker compose logs -f api` |
| **Logs en tiempo real (todos)** | `docker compose logs -f` |
| **Detener todos los contenedores** | `docker compose down` |
| **Reiniciar la API** | `docker compose restart api` |
| **Reconstruir imagen** | `docker compose up --build -d` |
| **Entrar al contenedor de la API** | `docker exec -it arbitriumsas-api bash` |
| **Entrar a la base de datos** | `docker exec -it arbitriumsas-db psql -U postgres -d programacion` |
| **Ver contenedores corriendo** | `docker ps` |

> [!NOTE]
> Todos los comandos `docker compose` deben ejecutarse desde la carpeta `ubuntu/` del proyecto, ya que ahí reside el archivo `docker-compose.yml`.

---

## ⚠️ Errores Comunes

### `permission denied while trying to connect to docker.sock`

Este error indica que el usuario de Ubuntu no tiene permisos para acceder al socket de Docker.

> [!WARNING]
> Este error es frecuente cuando un colaborador configura el entorno por primera vez.

**Solución paso a paso:**

**1. Verificar que Docker Desktop esté abierto** y en ejecución en Windows.

**2. Añadir tu usuario al grupo Docker** dentro de Ubuntu:
```bash
sudo usermod -aG docker $USER
```

**3. Aplicar los cambios de grupo.** Cerrar sesión y volver a abrirla. Como alternativa rápida:
```bash
newgrp docker
```

**4. Verificar los permisos:**
```bash
docker info
```

**5. Ejecutar nuevamente:**
```bash
docker compose up --build
```

> [!TIP]
> Si `newgrp docker` no es suficiente, cierra completamente la terminal de Ubuntu y ábrela de nuevo con `wsl -d Ubuntu`.

### `docker command not found`

**Solución:** Verificar la integración de WSL en Docker Desktop:
-   Settings → Resources → WSL Integration → Ubuntu activado.

### `unable to checkout working tree` (archivos `:Zone.Identifier`)

**Solución:** Estos archivos son metadatos de Windows incompatibles con Git. Están configurados en el `.gitignore` del proyecto. Si aparecen, eliminarlos:
```bash
find . -name "*:Zone.Identifier" -delete
```

### Otros problemas frecuentes

| Problema | Solución |
| :--- | :--- |
| **Error de conexión a la DB** | Verifica que el contenedor `arbitriumsas-db` esté corriendo con `docker ps` |
| **Puertos 8000 o 5432 ocupados** | Cierra cualquier otro servicio que esté usando esos puertos |
| **Proyecto lento** | Asegúrate de que el código esté en `~/Develop/ubuntu` (Linux) y NO en `/mnt/c/...` (Windows) |
| **Permisos denegados en archivos** | Ejecuta `sudo chown -R $USER:$USER ~/Develop/ubuntu` dentro de Ubuntu |

---

## 🏗️ Estructura del Proyecto

*   `ubuntu/docker-compose.yml` — Orquestación de servicios (API + Base de Datos PostGIS).
*   `ubuntu/backend/Dockerfile` — Configuración del entorno Linux (Python 3.10 Slim + GDAL + Java).
*   `ubuntu/backend/` — Código fuente de la API (FastAPI).
*   `ubuntu/backend/requirements.txt` — Dependencias de Python.
*   `ubuntu/mergin_sync/` — Carpeta vinculada para sincronización de datos Mergin Maps.
*   `ubuntu/.env` — Variables de entorno (credenciales, configuraciones).

---

## 🛠️ Tecnologías Utilizadas

-   **FastAPI** — Framework principal de la API.
-   **Docker & Docker Compose** — Orquestación y portabilidad.
-   **PostgreSQL / PostGIS** — Base de datos geoespacial.
-   **GIS Python Stack** — GeoPandas, Fiona, Shapely, PyProj.
-   **Box SDK** — Integración con almacenamiento en la nube (JWT).
-   **Mergin Client** — Sincronización de datos con Mergin Maps.
-   **ili2pg / ilivalidator** — Herramientas INTERLIS para importación/exportación y validación XTF.

---

## ☁️ Despliegue en AWS (Referencia)

Para llevar este entorno a producción:

1.  **Base de Datos:** AWS RDS (PostgreSQL 15 + PostGIS).
2.  **Servidor:** EC2 Ubuntu t3.micro (Dockerizado).
3.  Clonar el repo en el servidor EC2.
4.  Configurar el `.env` con el `DB_HOST` apuntando al endpoint de RDS.
5.  Ejecutar `docker compose up -d --build`.

---

## 📌 Ventajas de esta Arquitectura

-   ✅ **Rendimiento Nativo:** Al usar `/home` en Ubuntu, el I/O de disco es inmediato.
-   ✅ **Paridad con Producción:** El entorno es idéntico a AWS.
-   ✅ **VSCode Remote:** Puedes usar VSCode en Windows conectándote a WSL para editar los archivos "dentro" de Linux.
-   ✅ **Portabilidad Total:** Cualquier colaborador puede replicar el entorno en minutos.

---
*Desarrollado para ArbitriumSAS — Entorno Portable 2024*
