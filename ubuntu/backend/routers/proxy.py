import os
import time
import urllib.parse
from threading import Lock

from fastapi import APIRouter, HTTPException, Request, Response
import requests

from core.env_loader import load_env_file_if_present
from services.session_auth import get_current_tenant_from_session

router = APIRouter(prefix="/proxy", tags=["proxy"])


class InMemoryCache:
    def __init__(self, default_ttl: int = 60, max_size: int = 1000):
        self.store = {}
        self.lock = Lock()
        self.default_ttl = default_ttl
        self.max_size = max_size

    def get(self, key: str):
        with self.lock:
            entry = self.store.get(key)
            if entry:
                content, content_type, status_code, headers, expires_at = entry
                if time.time() < expires_at:
                    return content, content_type, status_code, headers
                else:
                    del self.store[key]
            return None

    def set(self, key: str, content: bytes, content_type: str, status_code: int, headers: dict, ttl: int = None):
        if ttl is None:
            ttl = self.default_ttl
        now = time.time()
        with self.lock:
            if len(self.store) >= self.max_size:
                # Clean expired entries to free up space
                self.store = {k: v for k, v in self.store.items() if now < v[4]}
                if len(self.store) >= self.max_size:
                    self.store.clear()
            self.store[key] = (content, content_type, status_code, headers, now + ttl)


def make_cache_key(url: str, params: dict) -> str:
    sorted_params = sorted(params.items()) if params else []
    query_str = urllib.parse.urlencode(sorted_params)
    return f"{url}?{query_str}"


local_cache = InMemoryCache()

load_env_file_if_present()

DEFAULT_WMS_BASE_URL = os.getenv(
    "WMS_BASE_URL",
    "https://arbitriumsas.arbimaps.com/geoserver/wms",
)


def _strip_trailing_slash(value: str) -> str:
    return str(value or "").strip().rstrip("/")


def _derive_geoserver_root_from_wms(wms_url: str) -> str:
    clean_url = str(wms_url or "").strip()
    idx = clean_url.find("/geoserver")
    if idx != -1:
        return clean_url[: idx + len("/geoserver")]
    return "https://arbitriumsas.arbimaps.com/geoserver"


def _get_optional_tenant(request: Request):
    try:
        return get_current_tenant_from_session(request)
    except HTTPException:
        return None


def _resolve_wms_base_url(request: Request) -> str:
    tenant = _get_optional_tenant(request)
    if tenant is not None:
        configured_wms = _strip_trailing_slash(tenant.wms_base_url)
        if configured_wms:
            return configured_wms

        base_url = _strip_trailing_slash(tenant.geoserver_base_url)
        workspace = _strip_trailing_slash(tenant.geoserver_workspace)
        if base_url and workspace:
            return f"{base_url}/{workspace}/wms"

    return _strip_trailing_slash(DEFAULT_WMS_BASE_URL)


def _resolve_geoserver_root(request: Request) -> str:
    tenant = _get_optional_tenant(request)
    if tenant is not None:
        configured_root = _strip_trailing_slash(tenant.geoserver_base_url)
        if configured_root:
            return configured_root

        configured_wms = _strip_trailing_slash(tenant.wms_base_url)
        if configured_wms:
            return _derive_geoserver_root_from_wms(configured_wms)

    return _derive_geoserver_root_from_wms(DEFAULT_WMS_BASE_URL)


def _forward_get(base_url: str, params: dict) -> Response:
    """
    Proxy sencillo de peticiones GET al WMS con soporte de caché.
    """
    if not base_url:
        raise HTTPException(status_code=500, detail="WMS_BASE_URL invalida")

    cache_key = make_cache_key(base_url, params)
    cached = local_cache.get(cache_key)
    if cached is not None:
        content, content_type, status_code, headers = cached
        return Response(content=content, status_code=status_code, headers=headers)

    try:
        resp = requests.get(
            base_url,
            params=params,
            timeout=30,
            allow_redirects=True,
        )
        body = resp.content
        content_type = resp.headers.get("Content-Type", "image/png")
        status_code = resp.status_code
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Error al conectar con WMS: {exc}") from exc

    headers = {
        "Access-Control-Allow-Origin": "*",
        "Content-Type": content_type,
    }

    if status_code == 200:
        is_image = content_type.startswith("image/")
        is_vector = (
            "json" in content_type.lower()
            or "xml" in content_type.lower()
            or "javascript" in content_type.lower()
            or "text" in content_type.lower()
        )
        if is_image:
            cache_ttl = int(os.getenv("PROXY_IMAGE_CACHE_MAX_AGE", "300"))
            headers["Cache-Control"] = f"public, max-age={cache_ttl}"
        elif is_vector:
            vector_ttl = int(os.getenv("PROXY_VECTOR_CACHE_TTL", "60"))
            browser_ttl = int(os.getenv("PROXY_VECTOR_BROWSER_CACHE_MAX_AGE", "15"))
            headers["Cache-Control"] = f"public, max-age={browser_ttl}"
            local_cache.set(cache_key, body, content_type, status_code, headers, ttl=vector_ttl)

    return Response(content=body, status_code=status_code, headers=headers)


@router.get("/wms")
def proxy_wms(request: Request) -> Response:
    """
    Proxy de WMS:
    - Recibe los mismos query params que un GetMap.
    - Llama al servidor WMS configurado en WMS_BASE_URL.
    - Devuelve la imagen/respuesta al navegador evitando CORS.
    """
    params = dict(request.query_params)
    if not params:
        # No tiene sentido llamar al WMS sin parametros
        raise HTTPException(status_code=400, detail="Faltan parametros de consulta WMS")

    return _forward_get(_resolve_wms_base_url(request), params)


# -----------------------------------------------------------------
# Proxy de GeoServer para Desarrollo Local (evita 404/CORS)
# -----------------------------------------------------------------
geoserver_router = APIRouter(tags=["geoserver"])


@geoserver_router.api_route("/geoserver/{path:path}", methods=["GET", "POST", "OPTIONS"])
async def proxy_geoserver(path: str, request: Request) -> Response:
    """
    Proxy de GeoServer: redirige las peticiones locales /geoserver/... al GeoServer remoto.
    """
    params = dict(request.query_params)
    body = await request.body()

    tenant = _get_optional_tenant(request)
    if tenant is not None and tenant.geoserver_workspace:
        ws = tenant.geoserver_workspace.strip()
        if ws and ws.lower() != "b_asignaciones_arb":
            # 1. Rewrite path
            if path.startswith("B_ASIGNACIONES_ARB/"):
                path = path.replace("B_ASIGNACIONES_ARB/", f"{ws}/", 1)
            elif path.startswith("b_asignaciones_arb/"):
                path = path.replace("b_asignaciones_arb/", f"{ws}/", 1)
            elif path == "B_ASIGNACIONES_ARB":
                path = ws
            elif path == "b_asignaciones_arb":
                path = ws

            # 2. Rewrite query parameters
            new_params = {}
            for k, v in params.items():
                if isinstance(v, str):
                    v = v.replace("B_ASIGNACIONES_ARB:ASIGNACIONES", f"{ws}:arb_terreno")
                    v = v.replace("b_asignaciones_arb:ASIGNACIONES", f"{ws}:arb_terreno")
                    v = v.replace("B_ASIGNACIONES_ARB", ws)
                    v = v.replace("b_asignaciones_arb", ws)
                new_params[k] = v
            params = new_params

            # 3. Rewrite request body
            if body:
                try:
                    ws_bytes = ws.encode("utf-8")
                    body = body.replace(b"B_ASIGNACIONES_ARB:ASIGNACIONES", ws_bytes + b":arb_terreno")
                    body = body.replace(b"b_asignaciones_arb:ASIGNACIONES", ws_bytes + b":arb_terreno")
                    body = body.replace(b"B_ASIGNACIONES_ARB", ws_bytes)
                    body = body.replace(b"b_asignaciones_arb", ws_bytes)
                except Exception:
                    pass

    target_url = f"{_resolve_geoserver_root(request)}/{path}"
    method = request.method

    cache_key = None
    if method == "GET":
        cache_key = make_cache_key(target_url, params)
        cached = local_cache.get(cache_key)
        if cached is not None:
            content, content_type, status_code, headers = cached
            return Response(content=content, status_code=status_code, headers=headers)

    try:
        resp = requests.request(
            method=method,
            url=target_url,
            params=params,
            data=body,
            headers={k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length")},
            timeout=30,
            allow_redirects=True,
        )
        content_type = resp.headers.get("Content-Type", "image/png")
        status_code = resp.status_code
        headers = {
            "Access-Control-Allow-Origin": "*",
            "Content-Type": content_type,
        }

        if method == "GET" and status_code == 200:
            is_image = content_type.startswith("image/")
            is_vector = (
                "json" in content_type.lower()
                or "xml" in content_type.lower()
                or "javascript" in content_type.lower()
                or "text" in content_type.lower()
            )
            if is_image:
                cache_ttl = int(os.getenv("PROXY_IMAGE_CACHE_MAX_AGE", "300"))
                headers["Cache-Control"] = f"public, max-age={cache_ttl}"
            elif is_vector:
                vector_ttl = int(os.getenv("PROXY_VECTOR_CACHE_TTL", "60"))
                browser_ttl = int(os.getenv("PROXY_VECTOR_BROWSER_CACHE_MAX_AGE", "15"))
                headers["Cache-Control"] = f"public, max-age={browser_ttl}"
                local_cache.set(cache_key, resp.content, content_type, status_code, headers, ttl=vector_ttl)

        return Response(content=resp.content, status_code=status_code, headers=headers)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Error en proxy de GeoServer local al servidor remoto: {exc}"
        )
