# Tareas - Solicitudes de Creación de Usuarios por Líderes de Reconocimiento

- [x] **Base de Datos**
  - [x] Crear la tabla `solicitud_creacion_usuario` en `ensure_asignacion_tables` de `asignaciones_repo.py`.
  - [x] Crear los índices para `creado_por_id` y `estado` en la tabla.
- [ ] **Modelos y Endpoints del Backend**
  - [ ] Definir los esquemas Pydantic `SolicitudCreacionUsuarioCreate`, `SolicitudCreacionUsuarioAprobar`, `SolicitudCreacionUsuarioRechazar` en `usuarios.py`.
  - [ ] Implementar `POST /usuarios/solicitudes` en `usuarios.py` para guardar la solicitud y notificar a soporte/admin.
  - [ ] Implementar `GET /usuarios/solicitudes` en `usuarios.py` con alcance limitado para líderes.
  - [ ] Implementar `POST /usuarios/solicitudes/{id}/aprobar` en `usuarios.py` (crear usuario real, hashear contraseña, estado APROBADA, notificar).
  - [ ] Implementar `POST /usuarios/solicitudes/{id}/rechazar` en `usuarios.py` (estado RECHAZADA, comentarios de rechazo, notificar).
  - [ ] Importar y asegurar la inicialización de la tabla (`ensure_asignacion_tables`) al entrar a endpoints de usuarios.
- [ ] **Frontend de Usuarios y Cuadrillas**
  - [ ] Habilitar pestaña "Solicitudes" (`tabSolicitudes`) en `usuarios.html` para líderes, soporte y admin.
  - [ ] Modificar formulario en modal `#modalUsuario` en `usuarios.html` para líderes: ocultar contraseña, restringir roles y interceptar envío.
  - [ ] Renderizar y paginar la tabla de solicitudes en la nueva pestaña.
  - [ ] Implementar botones rápidos de "Aprobar" (SweetAlert2 con password) y "Rechazar" (SweetAlert2 con comentarios) para soporte y admin.
- [ ] **Verificación y Pruebas**
  - [ ] Verificar el flujo completo de manera manual.
