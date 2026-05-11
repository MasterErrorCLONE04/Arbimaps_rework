# ArbitriumSAS API - Entorno Dockerizado 🚀

Este proyecto contiene la API de ArbitriumSAS migrada a un entorno **Docker**, lo que garantiza que sea portátil, reproducible y fácil de desplegar en cualquier máquina (Localhost, WSL, AWS, etc.).

## 📋 Requisitos Previos

Solo necesitas tener instalado:
*   [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows/Mac) o Docker Engine (Linux).

## 🚀 Instalación Rápida

1.  **Copiar el proyecto**: Clona o descarga esta carpeta en tu nueva máquina.
2.  **Configurar Variables**: Asegúrate de que los archivos `.env` existan en las rutas correspondientes (ver sección Variables de Entorno).
3.  **Lanzar el contenedor**: Abre una terminal en la carpeta raíz del proyecto (`ubuntu/`) y ejecuta:
    ```bash
    docker compose up --build -d
    ```

El sistema descargará las imágenes necesarias e instalará todas las dependencias (incluyendo librerías GIS complejas como GDAL y Fiona) de forma automática.

## 🛠️ Tecnologías Utilizadas

*   **FastAPI**: Framework principal para la API.
*   **Docker & Docker Compose**: Orquestación y portabilidad.
*   **PostgreSQL/PostGIS**: Base de datos (acceso externo).
*   **GIS Python Stack**: GeoPandas, Fiona, Shapely, PyProj.
*   **Box SDK**: Integración con almacenamiento en la nube (JWT).
*   **Mergin Client**: Sincronización de datos con Mergin Maps.

## 🔑 Variables de Entorno

Para que la API funcione, debes asegurar la presencia de los archivos `.env`. 

### Backend (`backend/.env`)
Contiene credenciales de DB, Box JWT y configuraciones de la app:
```env
DB_HOST=...
DB_NAME=...
BOX_CLIENT_ID=...
# ... etc
```

## 📂 Estructura del Proyecto Docker

*   `ubuntu/docker-compose.yml`: Define los servicios y volúmenes.
*   `backend/Dockerfile`: Instrucciones de construcción de la imagen de la API.
*   `backend/requirements.txt`: Dependencias de Python.
*   `backend/`: Código fuente de la aplicación.

## 🔍 Verificación

Una vez encendido, puedes acceder a:
*   **Panel de Control**: [http://localhost:8000/](http://localhost:8000/)
*   **Documentación API**: [http://localhost:8000/docs](http://localhost:8000/docs)
*   **Estado de Salud**: [http://localhost:8000/health](http://localhost:8000/health)

## 🐳 Comandos Útiles

*   **Ver logs**: `docker compose logs -f api`
*   **Detener**: `docker compose down`
*   **Reiniciar**: `docker compose restart api`
*   **Reconstruir**: `docker compose up --build -d` (usar si cambias el requirements.txt o Dockerfile).

---
*Desarrollado para ArbitriumSAS - Entorno Portable 2024*
