"""LDAP authentication and optional group-to-role mapping.

The LDAP bind password is used only to verify the user's credentials against
the directory. Flowsmith stores neither the LDAP password nor a directory
session; successful users receive the normal application JWT (and MFA
challenge, when enabled).
"""

from __future__ import annotations

import json
import logging
import ssl
from dataclasses import dataclass
from urllib.parse import urlparse

from ldap3 import BASE, NONE, SUBTREE, Connection, Server, Tls
from ldap3.core.exceptions import LDAPException
from ldap3.utils.conv import escape_filter_chars

from app.config import get_settings

logger = logging.getLogger("ldap")

LDAP_INVALID_CREDENTIALS = 49


class LdapUnavailable(Exception):
    """Directory server/config failure; login must fail closed."""


class LdapInvalidCredentials(Exception):
    """The user bind was rejected by the directory."""


class LdapConfigError(LdapUnavailable):
    """LDAP is enabled but its configuration cannot be used."""


@dataclass(frozen=True)
class LdapProfile:
    username: str
    email: str
    dn: str
    display_name: str
    groups: tuple[str, ...]


def _first(attributes: dict, name: str) -> str:
    values = attributes.get(name)
    if values is None:
        for key, candidate in attributes.items():
            if str(key).lower() == name.lower():
                values = candidate
                break
    if isinstance(values, (list, tuple)):
        return str(values[0]).strip() if values else ""
    return str(values).strip() if values is not None else ""


def _server_url(value: str) -> tuple[str, int, bool]:
    raw = value.strip()
    if "://" not in raw:
        raw = "ldap://" + raw
    parsed = urlparse(raw)
    if parsed.scheme not in ("ldap", "ldaps"):
        raise LdapConfigError("LDAP_SERVER_URL must use ldap:// or ldaps://.")
    host = parsed.hostname
    if not host:
        raise LdapConfigError("LDAP_SERVER_URL has no hostname.")
    use_ssl = parsed.scheme == "ldaps"
    try:
        port = parsed.port or (636 if use_ssl else 389)
    except ValueError as exc:
        raise LdapConfigError("LDAP_SERVER_URL has an invalid port.") from exc
    return host, port, use_ssl


def build_user_filter(username: str) -> str:
    template = get_settings().ldap_user_search_filter
    if template.count("{username}") != 1:
        raise LdapConfigError("LDAP_USER_SEARCH_FILTER must contain {username} exactly once.")
    return template.replace("{username}", escape_filter_chars(username))


def build_group_filter(user_dn: str) -> str:
    template = get_settings().ldap_group_search_filter
    if template.count("{user_dn}") != 1:
        raise LdapConfigError("LDAP_GROUP_SEARCH_FILTER must contain {user_dn} exactly once.")
    return template.replace("{user_dn}", escape_filter_chars(user_dn))


def parse_group_role_map(raw: str | None = None) -> dict[str, str]:
    value = get_settings().ldap_group_role_map if raw is None else raw
    if not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except ValueError:
        logger.warning("LDAP_GROUP_ROLE_MAP is not valid JSON; ignoring group role mapping")
        return {}
    if not isinstance(parsed, dict):
        logger.warning("LDAP_GROUP_ROLE_MAP must be a JSON object; ignoring")
        return {}
    result: dict[str, str] = {}
    for group, role in parsed.items():
        normalized_role = str(role).strip().lower()
        if normalized_role in ("admin", "member"):
            result[str(group).strip().lower()] = normalized_role
    return result


def role_for_groups(
    groups: tuple[str, ...] | list[str],
    role_map: dict[str, str],
    default_role: str,
) -> str:
    mapped = {
        role_map[group.strip().lower()]
        for group in groups
        if group.strip().lower() in role_map
    }
    if "admin" in mapped:
        return "admin"
    if "member" in mapped:
        return "member"
    return "admin" if default_role.strip().lower() == "admin" else "member"


def _settings():
    return get_settings()


def _server() -> Server:
    settings = _settings()
    host, port, use_ssl = _server_url(settings.ldap_server_url)
    tls = Tls(
        validate=ssl.CERT_REQUIRED if settings.ldap_tls_verify else ssl.CERT_NONE,
        ca_certs_file=settings.ldap_ca_cert_file or None,
    )
    return Server(
        host,
        port=port,
        use_ssl=use_ssl,
        tls=tls,
        get_info=NONE,
        connect_timeout=settings.ldap_connect_timeout_seconds,
    )


def _connection(
    server: Server,
    *,
    user: str | None = None,
    password: str | None = None,
) -> Connection:
    settings = _settings()
    connection = Connection(
        server,
        user=user or None,
        password=password or None,
        auto_bind=False,
        receive_timeout=settings.ldap_receive_timeout_seconds,
    )
    try:
        connection.open()
        if connection.socket is None:
            raise LdapUnavailable("LDAP server is unreachable.")
        if settings.ldap_start_tls and not server.ssl:
            if not connection.start_tls():
                raise LdapUnavailable("LDAP StartTLS negotiation failed.")
        if not connection.bind():
            result = connection.result or {}
            if user and result.get("result") == LDAP_INVALID_CREDENTIALS:
                raise LdapInvalidCredentials()
            raise LdapUnavailable(
                f"LDAP bind failed ({result.get('description') or 'unknown error'})."
            )
        return connection
    except (LdapInvalidCredentials, LdapUnavailable):
        connection.unbind()
        raise
    except LDAPException as exc:
        connection.unbind()
        logger.warning("LDAP connection error: %s", exc)
        raise LdapUnavailable("LDAP server is unavailable.") from exc


def _search_user(connection: Connection, username: str) -> dict | None:
    settings = _settings()
    try:
        found = connection.search(
            settings.ldap_user_search_base,
            build_user_filter(username),
            search_scope=SUBTREE,
            attributes=[
                settings.ldap_user_email_attribute,
                settings.ldap_user_display_attribute,
                "cn",
                "uid",
                "sAMAccountName",
            ],
            size_limit=2,
        )
    except LDAPException as exc:
        logger.warning("LDAP user search failed: %s", exc)
        raise LdapUnavailable("LDAP user search failed.") from exc
    entries = connection.entries or []
    responses = connection.response or []
    if not found or not entries:
        return None
    if len(entries) > 1:
        logger.warning("LDAP user search for %r returned multiple entries", username)
        raise LdapUnavailable("Ambiguous LDAP user search.")
    response = responses[0]
    return {
        "dn": response.get("dn", ""),
        "attributes": response.get("attributes", {}) or {},
    }


def _search_groups(connection: Connection, user_dn: str) -> tuple[str, ...]:
    settings = _settings()
    if not settings.ldap_group_search_base.strip():
        return ()
    try:
        connection.search(
            settings.ldap_group_search_base,
            build_group_filter(user_dn),
            search_scope=SUBTREE,
            attributes=[settings.ldap_group_attribute, "cn"],
            size_limit=200,
        )
    except LDAPException as exc:
        # Never treat a failed group lookup as "no groups": login-time and
        # background sync would otherwise revoke mapped workspace/org access.
        logger.warning("LDAP group search failed: %s", exc)
        raise LdapUnavailable("LDAP group search failed.") from exc
    groups: set[str] = set()
    for response in connection.response or []:
        if response.get("type") != "searchResEntry":
            continue
        attributes = response.get("attributes", {}) or {}
        group = _first(attributes, settings.ldap_group_attribute) or _first(attributes, "cn")
        if group:
            groups.add(group)
    return tuple(sorted(groups))


def lookup_ldap_profile(dn: str) -> LdapProfile | None:
    """Refresh email/display/groups for a stored user DN using the service account."""
    settings = _settings()
    if not settings.ldap_enabled or not dn.strip():
        return None
    server = _server()
    service: Connection | None = None
    try:
        service = _connection(
            server,
            user=settings.ldap_bind_dn or None,
            password=settings.ldap_bind_password or None,
        )
        found = service.search(
            dn.strip(),
            "(objectClass=*)",
            search_scope=BASE,
            attributes=[
                settings.ldap_user_email_attribute,
                settings.ldap_user_display_attribute,
                "cn",
            ],
            size_limit=1,
        )
        if not found or not service.entries:
            return None
        response = (service.response or [None])[0]
        if not response:
            return None
        attributes = response.get("attributes", {}) or {}
        email = _first(attributes, settings.ldap_user_email_attribute)
        if not email:
            return None
        return LdapProfile(
            username="",
            email=email.lower(),
            dn=dn.strip(),
            display_name=_first(attributes, settings.ldap_user_display_attribute),
            groups=_search_groups(service, dn.strip()),
        )
    except LDAPException as exc:
        logger.warning("LDAP profile refresh failed: %s", exc)
        raise LdapUnavailable("LDAP profile refresh failed.") from exc
    finally:
        if service is not None:
            service.unbind()


def authenticate_ldap(username: str, password: str) -> LdapProfile | None:
    """Bind as the directory user, returning profile/groups or None.

    ``None`` means the credentials were rejected. ``LdapUnavailable`` means
    the directory could not be used; callers must fail authentication rather
    than falling back to an unverified account.
    """
    settings = _settings()
    if not settings.ldap_enabled:
        return None
    username = username.strip()
    if not username or not password:
        return None
    if settings.ldap_user_search_filter.count("{username}") != 1:
        raise LdapConfigError("LDAP_USER_SEARCH_FILTER must contain {username} exactly once.")

    server = _server()
    service: Connection | None = None
    try:
        service = _connection(
            server,
            user=settings.ldap_bind_dn or None,
            password=settings.ldap_bind_password or None,
        )
        entry = _search_user(service, username)
        if entry is None:
            return None
        user_dn = str(entry.get("dn") or "")
        attributes = entry.get("attributes") or {}
        email = _first(attributes, settings.ldap_user_email_attribute)
        if not email:
            logger.warning("LDAP user %r has no %s attribute", username, settings.ldap_user_email_attribute)
            return None

        try:
            user_connection = _connection(server, user=user_dn, password=password)
        except LdapInvalidCredentials:
            return None
        else:
            user_connection.unbind()

        groups = _search_groups(service, user_dn)
        return LdapProfile(
            username=username,
            email=email.lower(),
            dn=user_dn,
            display_name=_first(attributes, settings.ldap_user_display_attribute),
            groups=groups,
        )
    finally:
        if service is not None:
            service.unbind()
