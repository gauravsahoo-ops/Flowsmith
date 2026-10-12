"""Authentication Recovery State Machine Definitions and Capabilities.

Defines the explicit states, valid transitions, recovery modes, and provider
capabilities across the Flowsmith platform.
"""

from __future__ import annotations

from enum import Enum
from typing import Set


class ConnectionState(str, Enum):
    """Explicit lifecycle states for integration credentials."""

    CONNECTED = "CONNECTED"
    EXPIRING_SOON = "EXPIRING_SOON"
    REFRESH_PENDING = "REFRESH_PENDING"
    REFRESHING = "REFRESHING"
    RECOVERY_PENDING = "RECOVERY_PENDING"
    REAUTHORIZATION_REQUIRED = "REAUTHORIZATION_REQUIRED"
    MANUAL_ACTION_REQUIRED = "MANUAL_ACTION_REQUIRED"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    DISCONNECTED = "DISCONNECTED"
    REVOKED = "REVOKED"


class RecoveryMode(str, Enum):
    """User- or administrator-configured credential recovery policy."""

    AUTOMATIC = "automatic"
    MANUAL = "manual"
    AUTOMATIC_WITH_NOTIFICATIONS = "automatic_with_notifications"


class AuthErrorCode(str, Enum):
    """Standardized classification of authentication and provider errors."""

    ACCESS_TOKEN_EXPIRED = "ACCESS_TOKEN_EXPIRED"
    REFRESH_TOKEN_EXPIRED = "REFRESH_TOKEN_EXPIRED"
    REFRESH_TOKEN_REVOKED = "REFRESH_TOKEN_REVOKED"
    INVALID_CLIENT_CREDENTIALS = "INVALID_CLIENT_CREDENTIALS"
    CONSENT_REQUIRED = "CONSENT_REQUIRED"
    INSUFFICIENT_PERMISSIONS = "INSUFFICIENT_PERMISSIONS"
    PROVIDER_RATE_LIMIT = "PROVIDER_RATE_LIMIT"
    NETWORK_TIMEOUT = "NETWORK_TIMEOUT"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    INVALID_API_KEY = "INVALID_API_KEY"
    TENANT_DISABLED = "TENANT_DISABLED"
    MFA_REQUIRED = "MFA_REQUIRED"
    MANUAL_MODE_LOCKED = "MANUAL_MODE_LOCKED"
    UNKNOWN = "UNKNOWN"


# Legal state transitions for the centralized recovery state machine
LEGAL_STATE_TRANSITIONS: dict[ConnectionState, Set[ConnectionState]] = {
    ConnectionState.CONNECTED: {
        ConnectionState.EXPIRING_SOON,
        ConnectionState.REFRESH_PENDING,
        ConnectionState.REFRESHING,
        ConnectionState.MANUAL_ACTION_REQUIRED,
        ConnectionState.REAUTHORIZATION_REQUIRED,
        ConnectionState.AUTHENTICATION_FAILED,
        ConnectionState.PROVIDER_UNAVAILABLE,
        ConnectionState.DISCONNECTED,
        ConnectionState.REVOKED,
    },
    ConnectionState.EXPIRING_SOON: {
        ConnectionState.REFRESH_PENDING,
        ConnectionState.REFRESHING,
        ConnectionState.MANUAL_ACTION_REQUIRED,
        ConnectionState.REAUTHORIZATION_REQUIRED,
        ConnectionState.CONNECTED,
        ConnectionState.DISCONNECTED,
        ConnectionState.REVOKED,
    },
    ConnectionState.REFRESH_PENDING: {
        ConnectionState.REFRESHING,
        ConnectionState.MANUAL_ACTION_REQUIRED,
        ConnectionState.DISCONNECTED,
        ConnectionState.REVOKED,
    },
    ConnectionState.REFRESHING: {
        ConnectionState.CONNECTED,
        ConnectionState.REAUTHORIZATION_REQUIRED,
        ConnectionState.MANUAL_ACTION_REQUIRED,
        ConnectionState.AUTHENTICATION_FAILED,
        ConnectionState.PROVIDER_UNAVAILABLE,
        ConnectionState.RECOVERY_PENDING,
        ConnectionState.DISCONNECTED,
        ConnectionState.REVOKED,
    },
    ConnectionState.RECOVERY_PENDING: {
        ConnectionState.REFRESHING,
        ConnectionState.MANUAL_ACTION_REQUIRED,
        ConnectionState.REAUTHORIZATION_REQUIRED,
        ConnectionState.PROVIDER_UNAVAILABLE,
        ConnectionState.DISCONNECTED,
        ConnectionState.REVOKED,
    },
    ConnectionState.PROVIDER_UNAVAILABLE: {
        ConnectionState.RECOVERY_PENDING,
        ConnectionState.REFRESHING,
        ConnectionState.CONNECTED,
        ConnectionState.AUTHENTICATION_FAILED,
        ConnectionState.MANUAL_ACTION_REQUIRED,
        ConnectionState.DISCONNECTED,
        ConnectionState.REVOKED,
    },
    ConnectionState.MANUAL_ACTION_REQUIRED: {
        ConnectionState.REFRESHING,  # when user triggers explicit reconnect
        ConnectionState.CONNECTED,
        ConnectionState.DISCONNECTED,
        ConnectionState.REVOKED,
    },
    ConnectionState.REAUTHORIZATION_REQUIRED: {
        ConnectionState.REFRESHING,  # user authorized new consent flow
        ConnectionState.CONNECTED,
        ConnectionState.DISCONNECTED,
        ConnectionState.REVOKED,
    },
    ConnectionState.AUTHENTICATION_FAILED: {
        ConnectionState.REFRESHING,
        ConnectionState.REAUTHORIZATION_REQUIRED,
        ConnectionState.MANUAL_ACTION_REQUIRED,
        ConnectionState.CONNECTED,
        ConnectionState.DISCONNECTED,
        ConnectionState.REVOKED,
    },
    ConnectionState.DISCONNECTED: {
        ConnectionState.CONNECTED,  # explicit user reconnection only
        ConnectionState.REFRESHING,
    },
    ConnectionState.REVOKED: {
        ConnectionState.CONNECTED,  # explicit user reauthorization only
        ConnectionState.REFRESHING,
    },
}


def can_transition(current: ConnectionState | str, target: ConnectionState | str) -> bool:
    """Validate whether target state is legally reachable from current state."""
    curr_enum = ConnectionState(current) if isinstance(current, str) else current
    target_enum = ConnectionState(target) if isinstance(target, str) else target
    if curr_enum == target_enum:
        return True
    allowed = LEGAL_STATE_TRANSITIONS.get(curr_enum, set())
    return target_enum in allowed
