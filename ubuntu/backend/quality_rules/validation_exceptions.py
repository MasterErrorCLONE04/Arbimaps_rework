from __future__ import annotations

import unicodedata

VALIDATION_MODE_ALL = "all"
VALIDATION_MODE_EXCEPTIONS = "exceptions"
DEFAULT_EXCEPTION_PROFILE = "default"

VALIDATION_EXCEPTION_RULES: dict[str, dict[str, str]] = {
    DEFAULT_EXCEPTION_PROFILE: {
        "4.9": "Excepcion inicial para validar sin ejecutar la regla economica 4.9.",
    },
}

_MODE_ALIASES = {
    "": VALIDATION_MODE_ALL,
    "all": VALIDATION_MODE_ALL,
    "normal": VALIDATION_MODE_ALL,
    "todos": VALIDATION_MODE_ALL,
    "validartodo": VALIDATION_MODE_ALL,
    "validacionnormal": VALIDATION_MODE_ALL,
    "exceptions": VALIDATION_MODE_EXCEPTIONS,
    "exception": VALIDATION_MODE_EXCEPTIONS,
    "conexcepciones": VALIDATION_MODE_EXCEPTIONS,
    "validarconexcepciones": VALIDATION_MODE_EXCEPTIONS,
}


def _normalize_token(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return "".join(ch for ch in text if ch.isalnum())


def normalize_validation_mode(value: object) -> str:
    return _MODE_ALIASES.get(_normalize_token(value), VALIDATION_MODE_ALL)


def exception_rule_ids(profile: str | None = None) -> frozenset[str]:
    profile_key = str(profile or DEFAULT_EXCEPTION_PROFILE).strip() or DEFAULT_EXCEPTION_PROFILE
    return frozenset(VALIDATION_EXCEPTION_RULES.get(profile_key, {}).keys())


def excluded_rule_ids_for_mode(
    mode: object,
    profile: str | None = None,
) -> frozenset[str]:
    if normalize_validation_mode(mode) != VALIDATION_MODE_EXCEPTIONS:
        return frozenset()
    return exception_rule_ids(profile)


def exception_rule_metadata(profile: str | None = None) -> list[dict[str, str]]:
    profile_key = str(profile or DEFAULT_EXCEPTION_PROFILE).strip() or DEFAULT_EXCEPTION_PROFILE
    rules = VALIDATION_EXCEPTION_RULES.get(profile_key, {})
    return [
        {"rule": rule_id, "reason": reason}
        for rule_id, reason in sorted(rules.items())
    ]
