import os
import importlib
import logging
from dataclasses import dataclass

from fastapi import Depends, FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware  # 👈 IMPORTANTE

from routers.asignaciones import router as asignaciones_router
from routers.asignaciones_detalle import router as asignaciones_detalle_router
from routers.asignaciones_paquetes import router as asignaciones_paquetes_router
from routers.buscar_predio import router as predio_router
from routers.logout_app import router as logout_router
from routers.pages import router as pages_router
from routers.proxy import router as proxy_router
from routers.validacion import router as validacion_router
from routers.predios_edit_api import router as predios_edit_router
from routers.usuarios import router as usuarios_router
from routers.visor_queries import router as visor_queries_router
from routers.visor_tortas import router as resumenp_router
from routers.auth import require_user, get_user_role
from routers.sync_routes import router as sync_router
from tenants import ConnectionManager, init_connection_manager, init_municipality_registry

# importacion para el archivo de edicion del predio
from routers.editar_predio_queries import router as editar_predio_queries_router

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_version: str
    static_url: str
    static_dir: str


def get_settings() -> Settings:
    return Settings(
        app_name=os.getenv("APP_NAME", "ArbitriumSAS API"),
        app_version=os.getenv("APP_VERSION", "0.1.0"),
        static_url=os.getenv("STATIC_URL", "/static"),
        static_dir=os.path.join(BASE_DIR, "static"),
    )


def _load_optional_router(module_path: str):
    try:
        module = importlib.import_module(module_path)
        return getattr(module, "router")
    except Exception as exc:
        logger.warning("Optional router disabled: %s (%s)", module_path, exc)
        return None


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version=settings.app_version)

    @app.on_event("startup")
    def _startup_registry() -> None:
        registry = init_municipality_registry(app)
        manager = ConnectionManager()
        init_connection_manager(app, manager)
        logger.info(
            "Municipality registry loaded: total=%s active=%s codes=%s pool=%s-%s",
            len(registry.all()),
            len(registry.active()),
            ",".join(registry.codes()),
            manager.minconn,
            manager.maxconn,
        )

    @app.on_event("shutdown")
    def _shutdown_connection_manager() -> None:
        manager = getattr(app.state, "tenant_connection_manager", None)
        if manager is None:
            return
        try:
            manager.close_all()
        except Exception as exc:
            logger.warning("ConnectionManager shutdown warning: %s", exc)

    # 🔥 CORS (CORRECTO)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.mount(settings.static_url, StaticFiles(directory=settings.static_dir), name="static")

    app.include_router(pages_router)
    app.include_router(predio_router)
    app.include_router(visor_queries_router)
    app.include_router(resumenp_router)
    app.include_router(proxy_router)
    app.include_router(asignaciones_router)
    app.include_router(asignaciones_detalle_router)
    app.include_router(asignaciones_paquetes_router)
    app.include_router(validacion_router)
    app.include_router(usuarios_router)
    app.include_router(logout_router)

    # incluir la variable predifinida del archivo de edicion del predio
    app.include_router(editar_predio_queries_router)


    app.include_router(sync_router, prefix="/api")
    app.include_router(predios_edit_router, prefix="/api")

    box_router = _load_optional_router("routers.box_routes")
    if box_router is not None:
        app.include_router(box_router, prefix="/api")

    docs_router = _load_optional_router("routers.docs_services")
    if docs_router is not None:
        app.include_router(docs_router)

    @app.get("/health", tags=["system"])
    def health():
        return {"status": "healthy"}

    @app.get("/api/health", tags=["system"])
    def health_api_alias():
        return {"status": "healthy"}

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return RedirectResponse(url=f"{settings.static_url}/icon.png", status_code=307)

    @app.get("/api/protected", tags=["auth"])
    def protected(user=Depends(require_user)):
        return {
            "ok": True,
            "user": user.get("username"),
            "email": user.get("email"),
            "role": get_user_role(user),
        }

    return app


app = create_app()



