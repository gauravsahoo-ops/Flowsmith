"""The node registry (spec 7: "NODE_REGISTRY = {type: class}").

Importing this module triggers registration of all built-in nodes via
the `register` decorator. Custom nodes can register themselves the same
way --- no core changes required.
"""

from __future__ import annotations

from app.engine.node_base import IDEMPOTENCY_LEVELS, BaseNode

NODE_REGISTRY: dict[str, type[BaseNode]] = {}


def register(cls: type[BaseNode]) -> type[BaseNode]:
    """Decorator that adds a node class to the registry."""
    if not cls.node_type:
        raise ValueError(f"Node class {cls.__name__} has no node_type.")
    if cls.idempotency not in IDEMPOTENCY_LEVELS:
        raise ValueError(
            f"Node {cls.node_type!r} has invalid idempotency {cls.idempotency!r}; "
            f"use one of {sorted(IDEMPOTENCY_LEVELS)} (spec 35)."
        )
    NODE_REGISTRY[cls.node_type] = cls
    return cls


_ALIASES: dict[str, str] = {
    "auth_fetch": "token_fetch",
    "auth_store": "token_store",
    "sub_workflow_trigger": "execute_workflow_trigger",
    "when_executed_by_another_workflow": "execute_workflow_trigger",
    "execute_sub_workflow": "sub_workflow",
}



def get(node_type: str) -> type[BaseNode] | None:
    target = _ALIASES.get(node_type, node_type)
    return NODE_REGISTRY.get(target)


_list_cache: list[dict] | None = None
_list_cache_ts: float = 0.0


def list_nodes() -> list[dict]:
    """Metadata for the API sidebar / docs (spec 26.1). Cached 60s."""
    global _list_cache, _list_cache_ts
    import time
    now = time.monotonic()
    if _list_cache is not None and now - _list_cache_ts < 60:
        return _list_cache
    seen_types: set[str] = set()
    items: list[dict] = []
    for cls in NODE_REGISTRY.values():
        if cls.node_type in seen_types:
            continue
        seen_types.add(cls.node_type)
        items.append({
            "type": cls.node_type,
            "version": cls.version,
            "display_name": cls.display_name,
            "description": cls.description,
            "category": cls.category,
            "icon": cls.icon,
            "credential_types": cls.credential_types,
            "input_handles": cls.input_handles,
            "output_handles": cls.output_handles,
            "idempotency": cls.idempotency,  # spec 35
            "parameters_schema": cls.parameters_schema.model_json_schema(),
        })
    _list_cache = items
    _list_cache_ts = now
    return _list_cache


def _load_builtin_nodes() -> None:
    from app.nodes import (  # noqa: F401
        aggregate,
        ai,
        ai_agent,
        chat_trigger,
        code,
        compare_datasets,
        crypto_tools,
        csv_json_transform,
        data_table,
        database_query,
        date_time,
        embeddings,
        email_read,
        execute_workflow_trigger,
        file_io,
        filter,
        form_trigger,
        ftp,
        git,
        graphql,
        html_extract,
        http_request,
        human_approval,
        if_condition,
        item_lists,
        loop,
        loop_over_items,
        loop_while,
        manual_trigger,
        markdown_text,
        memory,
        merge,
        noop,
        output_parser,
        pagination,
        rag_pipeline,
        respond_to_webhook,
        rss_feed,
        salesforce_trigger,
        schedule,
        send_email,
        set_data,
        slack,
        split,
        ssh,
        stop_and_error,
        sub_workflow,
        switch,
        telegram,
        text_splitter,
        token_fetch,
        token_manager,
        token_store,
        wait,
        webhook,
        websocket,
        xml_ops,
    )


_load_builtin_nodes()
