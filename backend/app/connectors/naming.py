"""Canonical connector/operation naming rules.

Connector keys are stable public identifiers and must never be renamed.  This
module only controls what users see: display names, hidden catalog aliases, and
human-readable operation labels.  Keeping these rules in one place prevents
the generated parity inventory from leaking reference-node labels such as
"Background Color" or "Timeout" into the product.
"""

from __future__ import annotations

from typing import Final

# Reference-inventory test fixtures. They remain registered for compatibility,
# but must not appear in discovery or node catalogs.
INTERNAL_CONNECTOR_KEYS: Final[frozenset[str]] = frozenset({
    "e2e_test",
    "e2e_test_polling_trigger",
})

# Catalog-only aliases which duplicate a native connector/node.  The keys stay
# registered so existing workflows and credentials continue to resolve, but
# they are omitted from user-facing discovery to avoid duplicate names.
CATALOG_ALIAS_TARGETS: Final[dict[str, str]] = {
    "active_campaign": "activecampaign",
    "click_up": "clickup",
    "google_big_query": "bigquery",
    "monday_com": "monday",
    "mongo_db": "mongodb",
    "my_sql": "mysql",
    "rabbit_m_q": "rabbitmq",
    "microsoft_outlook": "outlook",
    "microsoft_teams": "msteams",
    "pager_duty": "pagerduty",
    "service_now": "servicenow",
    "aws_s3": "s3",
    # These are represented by first-class workflow nodes.
    "crypto": "crypto_tools",
    "graph_q_l": "graphql",
    "graphql": "graphql",
    "if": "if_condition",
    "markdown": "markdown_text",
    "xml": "xml_ops",
    "email_send": "send_email",
    "schedule_trigger": "schedule",
    "ftp": "ftp",
    "split": "split_out",
    "split_out": "split_out",
}

HIDDEN_CATALOG_KEYS: Final[frozenset[str]] = frozenset(
    INTERNAL_CONNECTOR_KEYS | set(CATALOG_ALIAS_TARGETS)
)

# User-facing names for reference-inventory entries whose source label was a
# node/operation label rather than the vendor or node name.
DISPLAY_NAME_OVERRIDES: Final[dict[str, str]] = {
    "aws_s3": "AWS S3",
    "bamboo_hr": "BambooHR",
    "data_table": "Data Table",
    "debug_helper": "Debug Helper",
    "edit_image": "Edit Image",
    "egoi": "E-goi",
    "execute_workflow": "Execute Workflow",
    "form": "Form",
    "ftp": "FTP",
    "github_trigger": "GitHub Trigger",
    "google_sheets_trigger": "Google Sheets Trigger",
    "html": "HTML",
    "move_binary_data": "Move Binary Data",
    "open_meteo_air": "Open-Meteo Air Quality",
    "open_meteo_climate": "Open-Meteo Climate",
    "open_meteo_elevation": "Open-Meteo Elevation",
    "open_meteo_ensemble": "Open-Meteo Ensemble",
    "open_meteo_flood": "Open-Meteo Flood",
    "open_meteo_historical_weather": "Open-Meteo Historical Weather",
    "open_meteo_marine": "Open-Meteo Marine",
    "open_meteo_seasonal": "Open-Meteo Seasonal",
    "read_p_d_f": "Read PDF",
    "respond_to_webhook": "Respond to Webhook",
    "the_hive_project": "TheHive 5",
    "travis_ci": "Travis CI",
    "wordpress": "WordPress",
    "yourls": "YOURLS",
}

OPERATION_DISPLAY_OVERRIDES: Final[dict[tuple[str, str], str]] = {
    ("frankfurter", "get_start_date"): "Get rates for a start date",
    ("frankfurter", "get_start_date_end_date"): "Get rates for a date range",
    ("wise_trigger", "tranferstatechange"): "Transfer State Change",
    ("extract_from_file", "binarytopropery"): "Binary to Property",
}

_OPERATION_PREFIXES: Final[tuple[str, ...]] = (
    "update",
    "execute",
    "search",
    "create",
    "delete",
    "remove",
    "list",
    "fetch",
    "read",
    "write",
    "send",
    "run",
    "get",
    "add",
)

# Common words used to humanize concatenated reference-node operation keys
# such as ``generatehtmltemplate`` or ``localfile``.  Longest tokens win.
_OPERATION_WORDS: Final[tuple[str, ...]] = tuple(sorted({
    "absolute", "account", "accounts", "activate", "active", "add", "ad", "all",
    "analyze", "analyzes", "and", "api", "application", "area", "artists",
    "aspect", "auth", "automatically", "balance", "binary", "blur", "border",
    "both",
    "branch", "business", "by", "cart", "carts", "case", "cases",
    "certificate", "change", "channel", "channels", "chat", "client",
    "comment", "complete", "completed", "completion", "composite", "config",
    "configuration", "contact", "contacts", "content", "convert", "create",
    "credential", "credit", "crop", "currency", "currencies", "current",
    "currently", "cursor", "data", "database", "date", "delete", "delivery",
    "describe", "detect", "directory", "display", "do", "document",
    "dominant", "draft", "draw", "email", "end", "entities", "entity",
    "entra", "event", "events", "execute", "execution", "extract", "failed",
    "fetch", "field", "fields", "file", "files", "finishes", "first", "flood",
    "folder", "form", "from", "generate", "get", "html", "id", "if", "ignore",
    "image", "images", "include", "incoming", "independently", "interval",
    "item", "items", "job", "json", "language", "larger", "last", "later",
    "latest", "library", "limit", "line", "list", "local", "mail", "markdown",
    "maximum", "member", "message", "messages", "microsoft", "minimum",
    "multiple", "music", "name", "native", "new", "next", "node", "nodes",
    "queue", "related", "releases", "song",
    "nothing", "number", "oauth", "oauth2", "of", "offset", "on", "once",
    "only", "option", "options", "or", "page", "pages", "parameter",
    "password", "payload", "pdf", "period", "phone", "pipeline", "played",
    "playing", "post", "posts", "predefined", "previous", "principal",
    "product", "products", "propery", "publish", "push", "python", "query",
    "quote", "quotes", "random", "rate", "rates", "ratio", "read", "recently",
    "record", "records", "redirect", "remove", "request", "response",
    "return", "rotate", "run", "search", "secret", "security", "send",
    "sentiment", "service", "setup", "shear", "show", "sms", "song", "spam",
    "specific", "sql", "standard", "start", "started", "state", "status",
    "stop", "succeeded", "successfully", "subscription", "switch", "table",
    "tags", "team", "template", "text", "the", "time", "to", "token", "todo",
    "todos", "transfer", "transparency", "transparent", "translate",
    "trigger", "type", "types", "unlink", "update", "url", "user", "users",
    "version", "webhook", "whatsapp", "with", "without", "workflow",
    "workplace", "write", "xml",
}, key=len, reverse=True))

_OPERATION_ACRONYMS: Final[dict[str, str]] = {
    "api": "API",
    "csv": "CSV",
    "graphql": "GraphQL",
    "html": "HTML",
    "id": "ID",
    "javascript": "JavaScript",
    "json": "JSON",
    "oauth": "OAuth",
    "oauth2": "OAuth2",
    "pdf": "PDF",
    "sms": "SMS",
    "sql": "SQL",
    "url": "URL",
    "whatsapp": "WhatsApp",
    "xml": "XML",
}


def _split_concatenated_key(key: str) -> list[str] | None:
    """Backtracking dictionary split for machine-generated concatenated labels."""
    if not key or not key.islower():
        return None

    from functools import lru_cache

    @lru_cache(maxsize=None)
    def split_from(index: int) -> tuple[str, ...] | None:
        if index == len(key):
            return ()
        for token in _OPERATION_WORDS:
            if key.startswith(token, index):
                rest = split_from(index + len(token))
                if rest is not None:
                    return (token, *rest)
        return None

    tokens = split_from(0)
    return list(tokens) if tokens and len(tokens) > 1 else None


def display_name_for(connector_key: str, fallback: str) -> str:
    """Return the canonical user-facing name for a connector."""
    return DISPLAY_NAME_OVERRIDES.get(connector_key, fallback or connector_key)


def is_internal(connector_key: str) -> bool:
    return connector_key in INTERNAL_CONNECTOR_KEYS


def alias_target(connector_key: str) -> str | None:
    return CATALOG_ALIAS_TARGETS.get(connector_key)


def is_hidden_in_catalog(connector_key: str) -> bool:
    return connector_key in HIDDEN_CATALOG_KEYS


def humanize_operation_key(operation_key: str) -> str:
    """Turn snake_case or concatenated reference labels into readable text."""
    key = (operation_key or "").strip().lower()
    if not key:
        return "Execute"
    if "_" in key:
        return key.replace("_", " ").title()
    tokens = _split_concatenated_key(key)
    if tokens:
        return " ".join(
            _OPERATION_ACRONYMS.get(token, token.title()) for token in tokens
        )
    for prefix in _OPERATION_PREFIXES:
        if key.startswith(prefix) and len(key) > len(prefix):
            rest = key[len(prefix):]
            return f"{prefix.title()} {rest.title()}"
    return _OPERATION_ACRONYMS.get(key, key.title())


def operation_display_name(
    connector_key: str,
    operation_key: str,
    fallback: str = "",
) -> str:
    """Return a readable operation label, preferring explicit overrides."""
    override = OPERATION_DISPLAY_OVERRIDES.get((connector_key, operation_key))
    if override:
        return override
    if connector_key == "httpbin":
        return humanize_operation_key(operation_key)
    # The generated parity labels are often the raw operation key; normalise
    # them even if the inventory supplied a title-cased fallback.
    return humanize_operation_key(operation_key) if operation_key else (fallback or "Execute")


def normalize_definition_names(definition: object) -> None:
    """Apply canonical names to a definition before it enters the registry.

    Generated OpenAPI connectors and catalog-only parity entries carry labels
    copied from their source documents.  Normalize those here so every API,
    manifest, and UI consumer sees the same corrected names.  Native vendor
    operation labels are preserved; only duplicate labels are disambiguated.
    """
    key = str(getattr(definition, "connector_key", "") or "")
    if not key:
        return
    display = getattr(definition, "display_name", "") or key
    canonical = display_name_for(key, display)
    if canonical != display:
        setattr(definition, "display_name", canonical)

    metadata = getattr(definition, "metadata", None) or {}
    generated = metadata.get("source") == "openapi-import" or key.startswith("gen_")
    catalog = metadata.get("implementation") == "catalog_only"
    used: set[str] = set()
    for op_key, op in (getattr(definition, "operations", None) or {}).items():
        original = getattr(op, "display_name", "") or humanize_operation_key(op_key)
        override = OPERATION_DISPLAY_OVERRIDES.get((key, op_key))
        machine_label = (
            original == op_key
            or original == op_key.replace("_", " ").title()
            or (
                " " not in original
                and original.lower() == original
                and len(original) > 3
            )
        )
        if override:
            name = override
        elif generated or catalog or machine_label:
            name = humanize_operation_key(op_key)
        else:
            name = original
        if name in used:
            name = f"{name} ({humanize_operation_key(op_key)})"
        used.add(name)
        if name != original:
            setattr(op, "display_name", name)
