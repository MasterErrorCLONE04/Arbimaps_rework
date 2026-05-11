from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from routers.auth import COOKIE_NAME
from routers.pages import with_root_path

router = APIRouter()


@router.get("/logout-app")
def logout_app(request: Request):
    """
    Cierra la sesión local de la aplicación y vuelve al login.
    """
    target = with_root_path(request, "/")
    resp = RedirectResponse(url=target, status_code=302)

    # Cookie de sesión propia de la app
    resp.delete_cookie(COOKIE_NAME, path="/")

    return resp
