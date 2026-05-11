from __future__ import annotations

from typing import Any, Optional

from .config import (
    ASIG_ARB_INTERNAL_EMAILS,
    ASIG_ARB_INTERNAL_IDS,
    ASIG_ARB_INTERNAL_ONLY,
    ASIG_ARB_INTERNAL_ROLES,
    ASIG_ARB_INTERNAL_USERS,
    ASIG_MODEL,
)


def _norm_text(value: Any) -> str:
    return str(value or "").strip().lower()


def is_assignment_internal_rollout_active(model_name: Optional[str] = None) -> bool:
    target = _norm_text(model_name or ASIG_MODEL)
    return target == "arb" and ASIG_ARB_INTERNAL_ONLY


def is_assignment_internal_user(user: dict[str, Any] | None, *, role: Optional[str] = None) -> bool:
    if not user:
        return False

    username = _norm_text(user.get("username"))
    email = _norm_text(user.get("email"))
    user_id = _norm_text(user.get("id_global"))
    normalized_role = _norm_text(role or user.get("role") or user.get("rol") or user.get("role_code"))

    if normalized_role and normalized_role in ASIG_ARB_INTERNAL_ROLES:
        return True
    if username and username in ASIG_ARB_INTERNAL_USERS:
        return True
    if email and email in ASIG_ARB_INTERNAL_EMAILS:
        return True
    if user_id and user_id in ASIG_ARB_INTERNAL_IDS:
        return True
    return False


def can_access_assignment_model(
    user: dict[str, Any] | None,
    *,
    role: Optional[str] = None,
    model_name: Optional[str] = None,
) -> bool:
    if not is_assignment_internal_rollout_active(model_name):
        return True
    return is_assignment_internal_user(user, role=role)


def can_access_assignment_scope(
    user: dict[str, Any] | None,
    *,
    role: Optional[str] = None,
    allowed_roles: Optional[set[str]] = None,
    model_name: Optional[str] = None,
) -> bool:
    normalized_role = _norm_text(role or (user or {}).get("role"))
    normalized_allowed = {
        _norm_text(item)
        for item in (allowed_roles or set())
        if _norm_text(item)
    }

    if is_assignment_internal_rollout_active(model_name):
        if is_assignment_internal_user(user, role=normalized_role):
            return True

    if normalized_allowed and normalized_role not in normalized_allowed:
        return False

    return can_access_assignment_model(user, role=normalized_role, model_name=model_name)


def assignment_access_denied_detail(model_name: Optional[str] = None) -> str:
    if is_assignment_internal_rollout_active(model_name):
        return (
            "El modulo de asignaciones Arbimaps esta habilitado solo para usuarios internos "
            "durante la fase de pruebas."
        )
    return "No tienes permisos para acceder al modulo de asignaciones."
