# Plan de Implementación - Solicitudes de Creación de Usuarios por Líderes de Reconocimiento

Este plan describe la arquitectura y los pasos para habilitar el rol `lider_reconocimiento` para proponer la creación de nuevos usuarios bajo su cargo, enviando una solicitud a los usuarios de soporte/administradores para su revisión, establecimiento de contraseña, y aprobación final.

## User Review Required

> [!IMPORTANT]
> * **Roles Permitidos:** El líder de reconocimiento solo podrá solicitar la creación de usuarios con los roles: **`coordinador`**, **`reconocedor`** o **`digitalizador`**.
> * **Flujo de Contraseñas:** El líder de reconocimiento no establece la contraseña. El usuario de soporte/admin la asignará al aprobar la solicitud.
> * **Esquema de BD:** La tabla `solicitud_creacion_usuario` se creará en el esquema de `arbimaps_app` en todas las bases de datos de los municipios/tenants de forma dinámica y robusta.

## Proposed Changes

---

### Backend Components

#### [MODIFY] [asignaciones_repo.py](file://wsl.localhost/Ubuntu/home/arbimapas/Develop/ubuntu/backend/repositories/asignaciones_repo.py)
* En la función `ensure_asignacion_tables`, agregar la creación automática de la tabla `solicitud_creacion_usuario` en el esquema `arbimaps_app` (o el esquema correspondiente del tenant):
```sql
CREATE TABLE IF NOT EXISTS {app_schema}.solicitud_creacion_usuario (
    id SERIAL PRIMARY KEY,
    username TEXT NOT NULL,
    email TEXT,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    rol TEXT NOT NULL,
    fecha_inicio DATE,
    fecha_fin DATE,
    supervisor_id BIGINT REFERENCES {app_schema}.users(id_global) ON DELETE SET NULL,
    creado_por_id BIGINT REFERENCES {app_schema}.users(id_global) ON DELETE SET NULL,
    estado TEXT NOT NULL DEFAULT 'PENDIENTE', -- PENDIENTE, APROBADA, RECHAZADA
    creado_en TIMESTAMPTZ DEFAULT now(),
    comentarios_soporte TEXT
);
```
* Crear índices en `creado_por_id` y `estado` para la tabla `solicitud_creacion_usuario`.

#### [MODIFY] [usuarios.py](file://wsl.localhost/Ubuntu/home/arbimapas/Develop/ubuntu/backend/routers/usuarios.py)
* Importar `repositories.asignaciones_repo as asignaciones_repo` y asegurar que al listar usuarios o crear solicitudes se llame a `asignaciones_repo.ensure_asignacion_tables(conn, tenant)`.
* Definir esquemas Pydantic:
  * `SolicitudCreacionUsuarioCreate`: campos básicos de usuario exceptuando contraseña. Validar que el campo `rol` esté limitado estrictamente a `{"coordinador", "reconocedor", "digitalizador"}`.
  * `SolicitudCreacionUsuarioAprobar`: recibe la contraseña del nuevo usuario.
  * `SolicitudCreacionUsuarioRechazar`: recibe un comentario opcional con la razón.
* Agregar endpoint `POST /usuarios/solicitudes`:
  * Inserta la solicitud en `solicitud_creacion_usuario`.
  * Genera un registro en la tabla `notificaciones` para todos los usuarios con rol `soporte` y `admin` activos.
* Agregar endpoint `GET /usuarios/solicitudes`:
  * Líderes de reconocimiento ven solo solicitudes creadas por su ID.
  * Soporte y Admin ven la lista completa de solicitudes del tenant.
* Agregar endpoint `POST /usuarios/solicitudes/{id}/aprobar`:
  * Disponible para Soporte y Admin.
  * Verifica que la solicitud esté `PENDIENTE`.
  * Verifica si el `username` ya existe en `users`. De ser así, aborta con error 400.
  * Crea el usuario en la tabla `users` usando la contraseña provista (hasheada).
  * Cambia el estado de la solicitud a `APROBADA`.
  * Notifica al líder solicitante que la creación fue aprobada y completada.
* Agregar endpoint `POST /usuarios/solicitudes/{id}/rechazar`:
  * Disponible para Soporte y Admin.
  * Cambia el estado a `RECHAZADA` y guarda la razón en `comentarios_soporte`.
  * Notifica al líder solicitante sobre el rechazo.

---

### Frontend Components

#### [MODIFY] [usuarios.html](file://wsl.localhost/Ubuntu/home/arbimapas/Develop/ubuntu/backend/templates/usuarios.html)
* **Pestañas de Navegación:**
  * Si el rol actual es `lider_reconocimiento`, `soporte` o `admin`, mostrar una nueva pestaña: **"Solicitudes"** (`tabSolicitudes`) con su contador badge correspondiente.
  * En la pestaña "Solicitudes", renderizar una tabla dinámica con las solicitudes cargadas desde `/usuarios/solicitudes`.
* **Control de Formulario en Modal (`#modalUsuario`):**
  * Si el rol es `lider_reconocimiento`:
    * Ocultar el campo de "Contraseña".
    * Ocultar/bloquear el selector de rol del formulario para permitir únicamente: **`Coordinador`**, **`Reconocedor`** o **`Digitalizador`**.
    * Si se selecciona `Reconocedor`, el selector de "Supervisor" se precargará y bloqueará con el ID del propio líder logueado. Si es `Coordinador` o `Digitalizador`, se deshabilitará el selector de supervisor (debe enviarse vacío/nulo).
    * Al enviar el formulario, interceptar el submit y realizar un `POST` a `/usuarios/solicitudes` en vez de `/usuarios/`.
* **Acciones de Soporte/Admin:**
  * En la tabla de solicitudes, renderizar botones de acción rápidos en la columna "Acciones" para registros en estado `PENDIENTE`:
    * **Aprobar (Check):** Despliega un modal interactivo (SweetAlert2) solicitando la contraseña del usuario. Al confirmar, envía el `POST` de aprobación.
    * **Rechazar (Cross):** Despliega un modal solicitando el motivo del rechazo. Al confirmar, envía el `POST` de rechazo.

## Verification Plan

### Automated Tests
* Ejecutar pruebas unitarias de FastAPI usando pytest para asegurar que las validaciones de roles y endpoints devuelven códigos HTTP apropiados.

### Manual Verification
1. Iniciar sesión como `lider_reconocimiento`.
2. Acceder al módulo de usuarios y verificar la pestaña "Solicitudes".
3. Hacer clic en "Agregar usuario" (que funcionará como "Solicitar creación"). Rellenar datos sin contraseña y guardar.
4. Validar que la solicitud quede en estado "PENDIENTE".
5. Iniciar sesión como `soporte`.
6. Entrar al módulo, verificar la notificación generada y abrir la pestaña "Solicitudes".
7. Aprobar la solicitud ingresando una contraseña de prueba.
8. Comprobar que el usuario aparezca en la lista de usuarios activos de la plataforma.
