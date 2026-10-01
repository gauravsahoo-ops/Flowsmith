"""Model Router and Task-Based Routing Engine.

Routes AI tasks dynamically based on task requirements:
- Planning / IR compilation -> Reasoning / High-capacity models (GLM, Claude, GPT-4o, DeepSeek-R1)
- Intent Extraction / Classification -> Fast low-latency models (GPT-4o-mini, Haiku, Flash)
- Code Generation / Scripting -> Coding specialized models
- Summary / Fast Assist -> Cost-effective models

Allows users to specify provider="auto", model="auto", or override directly.
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from sqlalchemy.orm import Session

from app.credentials import service as credential_service
from app.models import User

logger = logging.getLogger("ai.router")

# Preferred models by capability profile
TASK_MODEL_PREFERENCES: dict[str, list[tuple[str, str]]] = {
    "planning": [
        ("openrouter", "z-ai/glm-5.3"),
        ("openrouter", "anthropic/claude-3.5-sonnet"),
        ("anthropic", "claude-3-5-sonnet-20241022"),
        ("openai", "gpt-4o"),
        ("deepseek", "deepseek-reasoner"),
        ("google", "gemini-1.5-pro"),
    ],
    "intent": [
        ("openrouter", "openai/gpt-4o-mini"),
        ("openai", "gpt-4o-mini"),
        ("anthropic", "claude-3-5-haiku-20241022"),
        ("google", "gemini-1.5-flash"),
        ("groq", "llama-3.3-70b-versatile"),
    ],
    "coding": [
        ("anthropic", "claude-3-5-sonnet-20241022"),
        ("openai", "gpt-4o"),
        ("deepseek", "deepseek-coder"),
        ("openrouter", "anthropic/claude-3.5-sonnet"),
    ],
    "fast": [
        ("openai", "gpt-4o-mini"),
        ("google", "gemini-1.5-flash"),
        ("groq", "llama-3.1-8b-instant"),
        ("openrouter", "meta-llama/llama-3.1-8b-instruct"),
    ],
}


class ModelRouter:
    """Intelligent task-based model routing engine."""

    @classmethod
    def resolve_model(
        cls,
        db: Session,
        user: User,
        task_type: str = "planning",
        requested_provider: Optional[str] = None,
        requested_model: Optional[str] = None,
        credential_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Resolve the optimal LLM configuration and credential for a given task."""
        # 1. Fetch user's configured LLM credentials
        all_creds = [
            m for m in credential_service.list_for_user(db, user.id)
            if m.get("type") in ("llm", "openai", "anthropic", "gemini", "groq", "openrouter", "deepseek", "ollama")
        ]

        if not all_creds:
            raise ValueError("No LLM credentials found. Please configure a provider in Credentials.")

        # 2. If explicit credential ID provided, resolve it directly
        if credential_id and credential_id != "auto":
            try:
                res = credential_service.resolve_credentials(db, user.id, {"llm": credential_id})
                data = res["llm"]
                cred_obj = {"id": credential_id, **data}
                if requested_model and requested_model != "auto":
                    cred_obj["selected_model"] = requested_model
                    cred_obj["model"] = requested_model
                return cred_obj
            except Exception as e:
                logger.warning(f"Could not resolve explicit credential {credential_id}: {e}")

        # 3. Decrypt all available user credentials to inspect provider types
        resolved_creds: list[dict[str, Any]] = []
        for meta in all_creds:
            try:
                decrypted = credential_service.resolve_credentials(db, user.id, {"llm": meta["id"]})
                cred_data = {"id": meta["id"], "name": meta.get("name"), **decrypted["llm"]}
                prov = cred_data.get("provider") or cred_data.get("provider_id") or meta.get("type", "openai")
                cred_data["provider"] = prov
                resolved_creds.append(cred_data)
            except Exception:
                continue

        if not resolved_creds:
            raise ValueError("Could not decrypt any LLM credentials.")

        # 4. If user requested specific provider (not auto)
        if requested_provider and requested_provider != "auto":
            for c in resolved_creds:
                if c.get("provider", "").lower() == requested_provider.lower():
                    if requested_model and requested_model != "auto":
                        c["selected_model"] = requested_model
                        c["model"] = requested_model
                    return c

        # 5. Task-based Auto Routing
        preferences = TASK_MODEL_PREFERENCES.get(task_type, TASK_MODEL_PREFERENCES["planning"])
        for pref_prov, pref_model in preferences:
            for c in resolved_creds:
                if c.get("provider", "").lower() == pref_prov.lower():
                    # Matched preferred provider
                    c_copy = dict(c)
                    # If model is auto or unset, use preferred model
                    if not requested_model or requested_model == "auto":
                        c_copy["selected_model"] = pref_model
                        c_copy["model"] = pref_model
                    else:
                        c_copy["selected_model"] = requested_model
                        c_copy["model"] = requested_model
                    return c_copy

        # 6. Fallback: First available active credential
        first = resolved_creds[0]
        if requested_model and requested_model != "auto":
            first["selected_model"] = requested_model
            first["model"] = requested_model
        return first
