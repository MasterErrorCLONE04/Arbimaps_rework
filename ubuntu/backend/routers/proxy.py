import os
import http.client
import urllib.parse

from fastapi import APIRouter, HTTPException, Request, Response

from core.env_loader import load_env_file_if_present

router = APIRouter(prefix="/proxy", tags=["proxy"])

load_env_file_if_present()

WMS_BASE_URL = os.getenv(
    "WMS_BASE_URL",
    "https://arbitriumsas.arbimaps.com/geoserver/wms",
)


def _forward_get(base_url: str, params: dict) -> Response:
    """
    Proxy sencillo de peticiones GET al WMS.

    Se usa para evitar problemas de CORS en el navegador.
    """
    parsed = urllib.parse.urlsplit(base_url)
    scheme = parsed.scheme or "http"
    netloc = parsed.netloc
    if not netloc:
        raise HTTPException(status_code=500, detail="WMS_BASE_URL invalida")

    query = urllib.parse.urlencode(params, doseq=True)
    path = parsed.path or "/"
    if query:
        path = f"{path}?{query}"

    conn_cls = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
    conn = conn_cls(netloc, timeout=30)

    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        content_type = resp.getheader("Content-Type", "image/png")
        status_code = resp.status
    except OSError as exc:
        raise HTTPException(status_code=502, detail=f"Error al conectar con WMS: {exc}") from exc
    finally:
        conn.close()

    headers = {
        "Access-Control-Allow-Origin": "*",
        "Content-Type": content_type,
    }
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

    return _forward_get(WMS_BASE_URL, params)
