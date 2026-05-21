from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from routers.auth import clear_session_cookie
from routers.pages import with_root_path

router = APIRouter()


@router.get("/logout-app")
def logout_app(request: Request):
    """
    Cierra la sesin local de la aplicacin y vuelve al login.
    """
    target = with_root_path(request, "/")
    resp = RedirectResponse(url=target, status_code=302)

    # Cookie de sesion propia de la app usando el nuevo servicio centralizado
    clear_session_cookie(resp)

    return resp
