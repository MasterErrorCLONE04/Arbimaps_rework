# ArbitriumSAS — Entorno de Desarrollo Dockerizado

Este repositorio contiene el backend de **ArbitriumSAS**, una API construida con FastAPI y desplegada mediante Docker. Este README documenta cómo configurar el entorno de desarrollo desde cero en Windows utilizando **Docker Desktop + WSL2 + Ubuntu**.

---

## 📐 Arquitectura del Entorno

### Objetivo

Configurar un entorno de desarrollo que:

- Mantenga compatibilidad total con **AWS / Linux**.
- Evite reconfiguraciones entre Windows y Ubuntu.
- Permita que Docker utilice Linux internamente.
- Permita trabajar normalmente desde **Windows con VSCode**.
- Evite duplicar archivos entre sistemas.

### Cómo funciona

| Componente | Rol |
|---|---|
| **Windows** | El proyecto vive físicamente aquí. Se edita con VSCode. |
| **Ubuntu / WSL2** | Actúa como entorno Linux para ejecutar Docker. |
| **Docker Desktop** | Usa WSL2 como motor Linux. |
| **Contenedores** | Se ejecutan dentro del subsistema Ubuntu. |

> Esto permite que el backend funcione exactamente igual que en AWS.

---

## 🛠️ Requisitos e Instalación

### 1. Instalar Docker Desktop

Descargar e instalar desde:
- [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/) o desde la **Microsoft Store**.

Durante la instalación:
- ✅ Activar la opción **WSL2**.
- 🔄 Reiniciar el computador si es solicitado.

### 2. Instalar WSL2 y Ubuntu

Abrir **PowerShell como administrador** y ejecutar:

```powershell
wsl --install
```

Esto instalará WSL2 y Ubuntu automáticamente.

Cuando Ubuntu se abra por primera vez, crear un usuario y contraseña:

> [!IMPORTANT]
> El nombre de usuario de Linux **debe estar en minúsculas**.
>
> ✅ Correcto: `usuariod`
>
> ❌ Incorrecto: `UsuarioD`

### 3. Actualizar Ubuntu

Abrir Ubuntu y ejecutar:

```bash
sudo apt update && sudo apt upgrade -y
```

### 4. Instalar Git en Windows

Descargar desde [git-scm.com/download/win](https://git-scm.com/download/win).

Esto habilitará los comandos `git clone`, `git pull`, `git push` en PowerShell.

### 5. Configurar Docker Desktop

1. Ir a **Settings → General** y activar:
   - ✅ `Use WSL 2 based engine`

2. Ir a **Settings → Resources → WSL Integration** y activar:
   - ✅ `Ubuntu`

3. Aplicar cambios y reiniciar Docker Desktop.

### 6. Verificar Docker en Ubuntu

Abrir Ubuntu desde PowerShell:

```powershell
wsl -d Ubuntu
```

Verificar que Docker esté disponible:

```bash
docker --version
```

Debe mostrar algo como: `Docker version XX.X.X`

---

## 📦 Clonar el Repositorio

> [!IMPORTANT]
> El repositorio **NO** debe copiarse a Ubuntu. El proyecto debe permanecer en Windows.

Abrir PowerShell:

```powershell
cd Desktop
git clone https://github.com/MasterErrorCLONE04/Develop.git
```

Esto creará la carpeta:

```
C:\Users\USUARIO\Desktop\Develop
```

---

## 🚀 Ejecutar el Proyecto

### Abrir Ubuntu

```powershell
wsl -d Ubuntu
```

### Acceder al proyecto desde Ubuntu

```bash
cd /mnt/c/Users/USUARIO/Desktop/Develop/ubuntu
```

> WSL monta automáticamente el disco `C:` en `/mnt/c`, por lo que Ubuntu accede directamente a los archivos de Windows. **No es necesario** copiar el proyecto a `/home/usuario`.

### Iniciar los contenedores

```bash
docker compose up --build
```

O en segundo plano:

```bash
docker compose up -d
```

### ✅ Verificar que funciona

Una vez iniciado, acceder desde el navegador a:

| Servicio | URL |
|---|---|
| Panel de Control | [http://localhost:8000/](http://localhost:8000/) |
| Documentación API | [http://localhost:8000/docs](http://localhost:8000/docs) |
| Health Check | [http://localhost:8000/health](http://localhost:8000/health) |

---

## 🐳 Comandos Docker Útiles

| Acción | Comando |
|---|---|
| Detener contenedores | `docker compose down` |
| Ver contenedores activos | `docker ps` |
| Ver logs | `docker compose logs` |
| Logs en tiempo real | `docker compose logs -f` |
| Reconstruir (tras cambios importantes) | `docker compose up --build` |
| Reiniciar servicio API | `docker compose restart api` |

> [!NOTE]
> Todos los comandos `docker compose` deben ejecutarse desde la carpeta `ubuntu/` del proyecto, ya que ahí reside el archivo `docker-compose.yml`.

---

## 🔄 Flujo Diario de Trabajo

### Abrir entorno

1. Abrir **Docker Desktop**.
2. Abrir Ubuntu:
   ```powershell
   wsl -d Ubuntu
   ```
3. Entrar al proyecto:
   ```bash
   cd /mnt/c/Users/USUARIO/Desktop/Develop/ubuntu
   ```
4. Ejecutar:
   ```bash
   docker compose up -d
   ```

### Trabajar normalmente

- Editar archivos desde **VSCode** en Windows.
- Docker reflejará automáticamente los cambios gracias a los volúmenes montados.

### Apagar entorno

```bash
docker compose down
```

---

## 🔄 Actualizar el Proyecto

Desde PowerShell o desde Ubuntu:

```bash
git pull
```

---

## ⚠️ Errores Comunes

### `permission denied while trying to connect to docker.sock`

Este error indica que el usuario de Ubuntu no tiene permisos para acceder al socket de Docker (`/var/run/docker.sock`), que por defecto es propiedad del usuario `root`.

> [!WARNING]
> Este error es frecuente cuando un colaborador configura el entorno por primera vez.

**Solución paso a paso:**

**1. Verificar que Docker Desktop esté abierto** y en ejecución en Windows.

**2. Añadir tu usuario al grupo Docker** dentro de Ubuntu:

```bash
sudo usermod -aG docker $USER
```

**3. Aplicar los cambios de grupo.** Es necesario cerrar sesión y volver a abrirla. Como alternativa rápida, puedes ejecutar:

```bash
newgrp docker
```

**4. Verificar los permisos:**

```bash
docker info
```

Si todo está bien configurado, este comando no generará errores de permisos.

**5. Ejecutar nuevamente:**

```bash
docker compose up --build
```

> [!TIP]
> Después de ejecutar `sudo usermod -aG docker $USER`, si `newgrp docker` no es suficiente, cierra completamente la terminal de Ubuntu y ábrela de nuevo con `wsl -d Ubuntu`.

### `docker command not found`

**Solución:** Verificar la integración de WSL en Docker Desktop:
- Settings → Resources → WSL Integration → Ubuntu activado.

### `unable to checkout working tree` (archivos `:Zone.Identifier`)

**Solución:** Estos archivos son metadatos de Windows incompatibles con Git. Están configurados en el `.gitignore` del proyecto (`*:Zone.Identifier`). Si aparecen, eliminarlos del repositorio:

```bash
find . -name "*:Zone.Identifier" -delete
```

---

## 📌 Ventajas de esta Arquitectura

- ✅ No se duplican archivos entre Windows y Linux.
- ✅ Docker funciona igual que en AWS.
- ✅ El entorno Linux permanece intacto.
- ✅ VSCode funciona directamente sobre Windows.
- ✅ Todo el equipo utiliza la misma arquitectura.
- ✅ Compatible con backend Linux y despliegue en AWS.

---

## 🛠️ Tecnologías Utilizadas

- **FastAPI** — Framework principal de la API.
- **Docker & Docker Compose** — Orquestación y portabilidad.
- **PostgreSQL / PostGIS** — Base de datos geoespacial.
- **GIS Python Stack** — GeoPandas, Fiona, Shapely, PyProj.
- **Box SDK** — Integración con almacenamiento en la nube (JWT).
- **Mergin Client** — Sincronización de datos con Mergin Maps.

---

*Desarrollado para ArbitriumSAS — Entorno Portable 2024*
