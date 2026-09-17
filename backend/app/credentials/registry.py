"""Credential type registry (spec 12: 'http', 'smtp', 'slack', ...).

Each credential type declares a Pydantic schema (used for server-side
validation, encryption payloads and the frontend form via JSON schema)
and which fields are secrets (redacted from logs/errors, never echoed).

Nodes declare the types they accept via `credential_types`; a node's
`credentials` map then references stored credentials by id.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

# Huge predefined list (exact as requested) — all implemented to make them work
try:
    from .predefined_big import PREDEFINED_CREDENTIALS_BIG as _HUGE_PREDEFINED
except Exception:
    _HUGE_PREDEFINED = []

MISSING_FIELD = ""


class SMTPCredential(BaseModel):
    host: str = Field(min_length=1, description="SMTP server host.")
    port: int = Field(default=587, ge=1, le=65535, description="SMTP port.")
    username: str = Field(default="", description="SMTP username (optional).")
    password: str = Field(default="", description="SMTP password (optional).")
    use_tls: bool = Field(default=False, description="Use implicit TLS (SMTPS).")
    starttls: bool = Field(default=False, description="Upgrade with STARTTLS.")


class IMAPCredential(BaseModel):
    host: str = Field(min_length=1, description="IMAP server host.")
    port: int = Field(default=993, ge=1, le=65535, description="IMAP port.")
    username: str = Field(min_length=1, description="IMAP username.")
    password: str = Field(min_length=1, description="IMAP password.")
    use_tls: bool = Field(default=True, description="Use implicit TLS (IMAPS).")


class DatabaseCredential(BaseModel):
    dsn: str = Field(min_length=1, description="SQLAlchemy connection string, e.g. sqlite:///app.db")


class HTTPCredential(BaseModel):
    api_key: str = Field(default="", description="API key (resolved via {{ $cred.http.api_key }}).")
    username: str = Field(default="", description="Basic-auth username (optional).")
    password: str = Field(default="", description="Basic-auth password (optional).")


class LLMCredential(BaseModel):
    base_url: str = Field(
        default="https://api.openai.com/v1",
        min_length=1,
        description="OpenAI-compatible /chat/completions base URL (OpenAI, Ollama, LM Studio...).",
    )
    api_key: str = Field(default="", description="API key (leave empty for local servers like Ollama).")
    model: str = Field(default="gpt-4o-mini", min_length=1, description="Model name.")
    timeout_s: int = Field(default=60, ge=1, le=300, description="Request timeout in seconds.")


class SalesforceCredential(BaseModel):
    instance_url: str = Field(
        default="https://login.salesforce.com",
        min_length=1,
        description="Salesforce org instance URL (returned by the token endpoint for OAuth connections).",
    )
    login_url: str = Field(
        default="",
        description="Authorization server base used for the token call (empty = instance_url).",
    )
    client_id: str = Field(default="", description="Connected-app consumer key (server config for OAuth connections).")
    client_secret: str = Field(default="", description="Connected-app consumer secret (server config for OAuth connections).")
    username: str = Field(
        default="", description="Salesforce username (username-password grant; display label for OAuth connections)."
    )
    password: str = Field(
        default="", description="Salesforce password (may include the API security token); optional with refresh_token."
    )
    refresh_token: str = Field(
        default="", description="OAuth2 refresh token from the authorization-code flow (alternative to username/password)."
    )
    oauth: bool = Field(
        default=False,
        description="True when the connection was created by the 'Connect Salesforce' OAuth flow (client id/secret come from server config).",
    )
    api_version: str = Field(default="v63.0", min_length=1, description="REST API version, e.g. v63.0.")

    @model_validator(mode="after")
    def _require_auth_method(self) -> "SalesforceCredential":
        if self.oauth:
            if not self.refresh_token.strip():
                raise ValueError("An OAuth-connected Salesforce credential needs a refresh_token.")
            return self
        if not self.client_id.strip() or not self.client_secret.strip():
            raise ValueError("Salesforce credential needs client_id and client_secret (or use 'Connect Salesforce').")
        has_password = bool(self.username.strip() and self.password.strip())
        has_refresh = bool(self.refresh_token.strip())
        if not has_password and not has_refresh:
            raise ValueError("Salesforce credential needs either username+password or refresh_token.")
        return self


class HubSpotCredential(BaseModel):
    """HubSpot connection (Phase 33).

    Two auth modes, mirroring the Salesforce credential:

    - OAuth ('Connect HubSpot'): the user authorizes with their own
      account; the refresh token is stored encrypted and access tokens
      are minted server-side on demand (client id/secret stay server
      config and are never stored).
    - Private-app token: a static ``private_token`` for simple setups.
    """

    hub_id: str = Field(default="", description="Portal/hub id (display label for OAuth connections).")
    user: str = Field(default="", description="Authorizing user email (display label).")
    refresh_token: str = Field(
        default="", description="OAuth2 refresh token from the authorization-code flow."
    )
    private_token: str = Field(default="", description="Private-app token (alternative to OAuth).")
    oauth: bool = Field(
        default=False,
        description="True when the connection was created by the 'Connect HubSpot' OAuth flow.",
    )

    @model_validator(mode="after")
    def _require_auth_method(self) -> "HubSpotCredential":
        if self.oauth:
            if not self.refresh_token.strip():
                raise ValueError("An OAuth-connected HubSpot credential needs a refresh_token.")
            return self
        has_private = bool(self.private_token.strip())
        has_refresh = bool(self.refresh_token.strip())
        if not has_private and not has_refresh:
            raise ValueError(
                "HubSpot credential needs a private_token or an OAuth refresh_token (use 'Connect HubSpot')."
            )
        return self


class GoogleCalendarCredential(BaseModel):
    """Google Calendar connection (Phase 37).

    OAuth-only ('Connect Google Calendar'): the refresh token is stored
    encrypted; access tokens are minted server-side on demand.
    """

    user: str = Field(default="", description="Authorizing account email (display label).")
    refresh_token: str = Field(default="", description="OAuth2 refresh token from the authorization flow.")
    oauth: bool = Field(
        default=False,
        description="True when created by the 'Connect Google Calendar' flow.",
    )

    @model_validator(mode="after")
    def _require_auth_method(self) -> "GoogleCalendarCredential":
        if not self.refresh_token.strip():
            raise ValueError("A Google Calendar credential needs a refresh_token (use 'Connect Google Calendar').")
        return self


class GoogleSheetsCredential(BaseModel):
    """Google Sheets connection (Phase 39). OAuth-only, like Calendar."""

    user: str = Field(default="", description="Authorizing account email (display label).")
    refresh_token: str = Field(default="", description="OAuth2 refresh token from the authorization flow.")
    oauth: bool = Field(default=False, description="True when created by the 'Connect Google Sheets' flow.")

    @model_validator(mode="after")
    def _require_auth_method(self) -> "GoogleSheetsCredential":
        if not self.refresh_token.strip():
            raise ValueError("A Google Sheets credential needs a refresh_token (use 'Connect Google Sheets').")
        return self



class GmailCredential(BaseModel):
    """Gmail send-only connection (Phase 41). OAuth-only."""

    user: str = Field(default="", description="Authorizing account email (display label).")
    refresh_token: str = Field(default="", description="OAuth2 refresh token.")
    oauth: bool = Field(default=False, description="Created via 'Connect Gmail'.")

    @model_validator(mode="after")
    def _require_auth(self) -> "GmailCredential":
        if not self.refresh_token.strip():
            raise ValueError("A Gmail credential needs a refresh_token (use 'Connect Gmail').")
        return self


class TelegramCredential(BaseModel):
    bot_token: str = Field(min_length=1, description="Bot token from @BotFather.")


# ----------------------------------------------------------------------
# Phase 11 business connectors
# ----------------------------------------------------------------------


class DSNOnlyCredential(BaseModel):
    """Shared shape for SQL connections (postgres / mysql)."""

    dsn: str = Field(min_length=1, description="SQLAlchemy connection string.")


class GoogleDriveCredential(BaseModel):
    """Google Drive connection. OAuth-only via the shared Google app."""

    user: str = Field(default="", description="Authorizing account email (display label).")
    refresh_token: str = Field(default="", description="OAuth2 refresh token.")
    oauth: bool = Field(default=False, description="Created via 'Connect Google Drive'.")

    @model_validator(mode="after")
    def _require_auth(self) -> "GoogleDriveCredential":
        if not self.refresh_token.strip():
            raise ValueError("A Google Drive credential needs a refresh_token (use 'Connect Google Drive').")
        return self


class MicrosoftGraphCredential(BaseModel):
    """Azure app registration powering Teams + Outlook (client credentials)."""

    tenant_id: str = Field(min_length=1, description="Directory (tenant) id.")
    client_id: str = Field(min_length=1, description="Application (client) id.")
    client_secret: str = Field(min_length=1, description="Client secret.")


class SlackBotCredential(BaseModel):
    bot_token: str = Field(min_length=1, description="Slack bot token (xoxb…).")
    team_name: str = Field(default="", description="Workspace name (display).")


class GitHubCredential(BaseModel):
    access_token: str = Field(min_length=1, description="Classic PAT or fine-grained token.")
    login: str = Field(default="", description="Account login (display).")


class NotionCredential(BaseModel):
    integration_token: str = Field(min_length=1, description="Internal integration token (ntn_…/secret_…).")
    workspace_name: str = Field(default="", description="Workspace name (display).")


class JiraCredential(BaseModel):
    site_url: str = Field(min_length=1, description='Site base URL, e.g. "https://acme.atlassian.net".')
    email: str = Field(min_length=1, description="Account email.")
    api_token: str = Field(min_length=1, description="API token from id.atlassian.com.")

    @model_validator(mode="after")
    def _require_https_site(self) -> "JiraCredential":
        if not self.site_url.strip().lower().startswith("https://"):
            raise ValueError('site_url must be an https URL, e.g. "https://acme.atlassian.net".')
        return self


class DiscordCredential(BaseModel):
    bot_token: str = Field(min_length=1, description="Discord bot token.")
    guild_name: str = Field(default="", description="Server name (display).")


class StripeSecretKeyCredential(BaseModel):
    secret_key: str = Field(min_length=1, description="Stripe secret key (sk_… or rk_…).")
    account_name: str = Field(default="", description="Account name (display).")


class MongoDBCredential(BaseModel):
    uri: str = Field(min_length=1, description="mongodb:// or mongodb+srv:// connection URI.")

    @model_validator(mode="after")
    def _require_scheme(self) -> "MongoDBCredential":
        lowered = self.uri.strip().lower()
        if not (lowered.startswith("mongodb://") or lowered.startswith("mongodb+srv://")):
            raise ValueError("uri must start with mongodb:// or mongodb+srv://.")
        return self


class RedisCredential(BaseModel):
    uri: str = Field(default="", description="redis:// or rediss:// URI; empty uses REDIS_URL.")
    name: str = Field(default="", description="Label (display).")


class AirtableCredential(BaseModel):
    personal_access_token: str = Field(min_length=1, description="Airtable personal access token.")
    base_hint: str = Field(default="", description="Base(s) used (display).")


class ShopifyCredential(BaseModel):
    shop_domain: str = Field(min_length=1, description='Store domain, e.g. "acme.myshopify.com".')
    access_token: str = Field(min_length=1, description="Admin API access token (shpat_…).")

    @model_validator(mode="after")
    def _require_shop_domain(self) -> "ShopifyCredential":
        domain = self.shop_domain.strip().lower().replace("https://", "").rstrip("/")
        if not domain.endswith(".myshopify.com"):
            raise ValueError('shop_domain must be your myshopify.com domain, e.g. "acme.myshopify.com".')
        return self


# Batch B connectors (keys match provider credential reads)


class TrelloCredential(BaseModel):
    api_key: str = Field(min_length=1, description="Trello API key (trello.com/app-key).")
    api_token: str = Field(min_length=1, description="Trello API token (authorize link).")


class AsanaCredential(BaseModel):
    access_token: str = Field(min_length=1, description="Asana personal access token.")


class LinearCredential(BaseModel):
    api_key: str = Field(min_length=1, description="Linear API key (Settings > API).")


class CalendlyCredential(BaseModel):
    access_token: str = Field(min_length=1, description="Calendly personal access token.")


class GitLabCredential(BaseModel):
    access_token: str = Field(min_length=1, description="GitLab personal access token.")
    host: str = Field(default="https://gitlab.com", description="Self-hosted host or https://gitlab.com.")

    @model_validator(mode="after")
    def _require_https_host(self) -> "GitLabCredential":
        if not self.host.strip().lower().startswith("https://"):
            raise ValueError("host must be an https URL.")
        return self


class ZoomCredential(BaseModel):
    access_token: str = Field(min_length=1, description="Zoom Server-to-Server OAuth access token.")


class TwilioCredential(BaseModel):
    account_sid: str = Field(min_length=1, description="Twilio Account SID (AC…).")
    auth_token: str = Field(min_length=1, description="Twilio Auth Token.")


class BitbucketCredential(BaseModel):
    access_token: str = Field(min_length=1, description="Bitbucket access token.")


class WhatsAppCredential(BaseModel):
    access_token: str = Field(min_length=1, description="Meta WhatsApp Business permanent access token.")
    phone_number_id: str = Field(min_length=1, description="WhatsApp phone number ID (Meta App Dashboard).")


class ClickUpCredential(BaseModel):
    api_key: str = Field(min_length=1, description="ClickUp personal API token (avatar menu > Apps).")


class PipedriveCredential(BaseModel):
    api_token: str = Field(min_length=1, description="Pipedrive API token (Settings > Personal preferences > API).")
    domain: str = Field(min_length=1, description="Company domain (e.g. acme.pipedrive.com).")


class DropboxCredential(BaseModel):
    access_token: str = Field(min_length=1, description="Dropbox OAuth access token (App Console).")


class OpenAICredential(BaseModel):
    api_key: str = Field(min_length=1, description="OpenAI API key (or compatible provider key).")
    base_url: str = Field(default="https://api.openai.com/v1", description="Base URL (default OpenAI, or compatible endpoint).")
    organization: str = Field(default="", description="OpenAI organization (optional).")


# ----------------------------------------------------------------------
# Generic HTTP Auth credential types (spec: 8 providers)
# ----------------------------------------------------------------------


class BasicAuthCredential(BaseModel):
    username: str = Field(min_length=1, description="Username for Basic authentication.")
    password: str = Field(default="", description="Password for Basic authentication.")


class BearerAuthCredential(BaseModel):
    token: str = Field(min_length=1, description="Bearer token.")


class HeaderAuthCredential(BaseModel):
    header_name: str = Field(min_length=1, description="Header name, e.g. X-API-Key.")
    header_value: str = Field(min_length=1, description="Header value.")


class QueryAuthCredential(BaseModel):
    query_name: str = Field(min_length=1, description="Query parameter name, e.g. api_key.")
    query_value: str = Field(min_length=1, description="Query parameter value.")


class DigestAuthCredential(BaseModel):
    username: str = Field(min_length=1, description="Digest username.")
    password: str = Field(min_length=1, description="Digest password.")
    realm: str = Field(default="", description="Digest realm (optional, auto from server if empty).")
    nonce: str = Field(default="", description="Digest nonce (optional).")


class CustomAuthCredential(BaseModel):
    headers: dict[str, str] = Field(default_factory=dict, description="Custom headers to inject.")
    query: dict[str, str] = Field(default_factory=dict, description="Custom query params to inject.")
    body: dict[str, Any] = Field(default_factory=dict, description="Custom body fields to merge.")


class OAuth2GenericCredential(BaseModel):
    client_id: str = Field(default="", description="OAuth2 client ID.")
    client_secret: str = Field(default="", description="OAuth2 client secret.")
    access_token: str = Field(default="", description="OAuth2 access token.")
    refresh_token: str = Field(default="", description="OAuth2 refresh token.")
    token_url: str = Field(default="", description="Token endpoint URL.")
    authorization_url: str = Field(default="", description="Authorization URL.")
    scopes: str = Field(default="", description="Scopes (space-separated).")
    expires_at: float = Field(default=0, description="Unix timestamp when access token expires.")


class OAuth1GenericCredential(BaseModel):
    consumer_key: str = Field(min_length=1, description="OAuth1 consumer key.")
    consumer_secret: str = Field(min_length=1, description="OAuth1 consumer secret.")
    token: str = Field(min_length=1, description="OAuth1 token.")
    token_secret: str = Field(min_length=1, description="OAuth1 token secret.")
    signature_method: str = Field(default="HMAC-SHA1", description="Signature method.")


class ApiKeyCredential(BaseModel):
    api_key: str = Field(min_length=1, description="API key.")
    api_key_name: str = Field(default="X-API-Key", description="Header or query name.")
    api_key_in: str = Field(default="header", description="Where to send the key: header or query.")


class PatCredential(BaseModel):
    token: str = Field(min_length=1, description="Personal Access Token.")


class JwtCredential(BaseModel):
    private_key: str = Field(min_length=1, description="Private key (PEM).")
    client_id: str = Field(min_length=1, description="Client ID / Issuer.")
    username: str = Field(min_length=1, description="Subject username.")
    audience: str = Field(min_length=1, description="Audience (e.g., https://login.salesforce.com).")
    expiration: int = Field(default=3600, ge=60, le=86400, description="Expiration in seconds.")


class ServiceAccountCredential(BaseModel):
    client_email: str = Field(min_length=1, description="Service account client email.")
    private_key: str = Field(min_length=1, description="Service account private key.")
    token_uri: str = Field(default="https://oauth2.googleapis.com/token", description="Token URI.")
    scopes: str = Field(default="", description="Scopes (space-separated).")


class AwsIamCredential(BaseModel):
    access_key: str = Field(min_length=1, description="AWS Access Key ID.")
    secret_key: str = Field(min_length=1, description="AWS Secret Access Key.")
    region: str = Field(default="us-east-1", description="AWS Region.")
    service: str = Field(default="execute-api", description="AWS Service.")
    session_token: str = Field(default="", description="Session token (optional).")


class AwsAssumeRoleCredential(BaseModel):
    access_key: str = Field(min_length=1, description="AWS Access Key ID.")
    secret_key: str = Field(min_length=1, description="AWS Secret Access Key.")
    region: str = Field(default="us-east-1", description="AWS Region.")
    role_arn: str = Field(min_length=1, description="Role ARN (arn:aws:iam::...).")
    external_id: str = Field(default="", description="External ID (optional).")


CREDENTIAL_TYPES: dict[str, type[BaseModel]] = {
    "smtp": SMTPCredential,
    "imap": IMAPCredential,
    "database": DatabaseCredential,
    "http": HTTPCredential,
    "llm": LLMCredential,
    "salesforce": SalesforceCredential,
    "hubspot": HubSpotCredential,
    "google_calendar": GoogleCalendarCredential,
    "google_sheets": GoogleSheetsCredential,
    "telegram": TelegramCredential,
    "gmail": GmailCredential,
    # Phase 11 business connectors
    "postgres": DSNOnlyCredential,
    "mysql": DSNOnlyCredential,
    "google_drive": GoogleDriveCredential,
    "microsoft_graph": MicrosoftGraphCredential,
    "slack": SlackBotCredential,
    "github": GitHubCredential,
    "notion": NotionCredential,
    "jira": JiraCredential,
    "discord": DiscordCredential,
    "stripe": StripeSecretKeyCredential,
    "mongodb": MongoDBCredential,
    "redis": RedisCredential,
    "airtable": AirtableCredential,
    "shopify": ShopifyCredential,
    # Batch B connectors
    "trello": TrelloCredential,
    "asana": AsanaCredential,
    "linear": LinearCredential,
    "calendly": CalendlyCredential,
    "gitlab": GitLabCredential,
    "zoom": ZoomCredential,
    "twilio": TwilioCredential,
    "bitbucket": BitbucketCredential,
    "whatsapp": WhatsAppCredential,
    "clickup": ClickUpCredential,
    "pipedrive": PipedriveCredential,
    "dropbox": DropboxCredential,
    "openai": OpenAICredential,
    # Generic HTTP Auth providers (spec)
    "basic_auth": BasicAuthCredential,
    "bearer_auth": BearerAuthCredential,
    "header_auth": HeaderAuthCredential,
    "query_auth": QueryAuthCredential,
    "digest_auth": DigestAuthCredential,
    "custom_auth": CustomAuthCredential,
    "oauth2": OAuth2GenericCredential,
    "oauth1": OAuth1GenericCredential,
    "api_key": ApiKeyCredential,
    "pat": PatCredential,
    "jwt": JwtCredential,
    "service_account": ServiceAccountCredential,
    "aws_iam": AwsIamCredential,
    "aws_assume_role": AwsAssumeRoleCredential,
}

SECRET_FIELDS: dict[str, frozenset[str]] = {
    "smtp": frozenset({"password"}),
    "imap": frozenset({"password"}),
    "database": frozenset({"dsn"}),  # DSNs embed passwords
    "http": frozenset({"api_key", "password"}),
    "llm": frozenset({"api_key"}),
    "salesforce": frozenset({"client_secret", "password", "refresh_token"}),
    "hubspot": frozenset({"refresh_token", "private_token"}),
    "google_calendar": frozenset({"refresh_token"}),
    "google_sheets": frozenset({"refresh_token"}),
    "telegram": frozenset({"bot_token"}),
    "gmail": frozenset({"refresh_token"}),
    # Phase 11 business connectors
    "postgres": frozenset({"dsn"}),
    "mysql": frozenset({"dsn"}),
    "google_drive": frozenset({"refresh_token"}),
    "microsoft_graph": frozenset({"client_secret"}),
    "slack": frozenset({"bot_token"}),
    "github": frozenset({"access_token"}),
    "notion": frozenset({"integration_token"}),
    "jira": frozenset({"api_token"}),
    "discord": frozenset({"bot_token"}),
    "stripe": frozenset({"secret_key"}),
    "mongodb": frozenset({"uri"}),
    "redis": frozenset({"uri"}),
    "airtable": frozenset({"personal_access_token"}),
    "shopify": frozenset({"access_token"}),
    "trello": frozenset({"api_key", "api_token"}),
    "asana": frozenset({"access_token"}),
    "linear": frozenset({"api_key"}),
    "calendly": frozenset({"access_token"}),
    "gitlab": frozenset({"access_token"}),
    "zoom": frozenset({"access_token"}),
    "twilio": frozenset({"account_sid", "auth_token"}),
    "bitbucket": frozenset({"access_token"}),
    "whatsapp": frozenset({"access_token"}),
    "clickup": frozenset({"api_key"}),
    "pipedrive": frozenset({"api_token"}),
    "dropbox": frozenset({"access_token"}),
    "openai": frozenset({"api_key"}),
    "basic_auth": frozenset({"password"}),
    "bearer_auth": frozenset({"token"}),
    "header_auth": frozenset({"header_value"}),
    "query_auth": frozenset({"query_value"}),
    "digest_auth": frozenset({"password", "nonce"}),
    "custom_auth": frozenset({"headers", "query"}),
    "oauth2": frozenset({"client_secret", "access_token", "refresh_token"}),
    "oauth1": frozenset({"consumer_secret", "token_secret"}),
    "api_key": frozenset({"api_key"}),
    "pat": frozenset({"token"}),
    "jwt": frozenset({"private_key"}),
    "service_account": frozenset({"private_key"}),
    "aws_iam": frozenset({"secret_key", "session_token"}),
    "aws_assume_role": frozenset({"secret_key", "session_token"}),
}

TYPE_META: dict[str, dict[str, str]] = {
    "smtp": {"name": "SMTP", "description": "Mail server connection for the Send Email node."},
    "imap": {"name": "IMAP", "description": "Mailbox connection for the Read Email node."},
    "database": {"name": "Database", "description": "Connection string for the Database Query node."},
    "http": {"name": "HTTP", "description": "API credentials injectable into HTTP Request headers."},
    "llm": {"name": "LLM", "description": "OpenAI-compatible model endpoint for the AI nodes."},
    "salesforce": {"name": "Salesforce", "description": "Salesforce org connection (OAuth2 password or refresh-token grant)."},
    "hubspot": {"name": "HubSpot", "description": "HubSpot CRM connection (Connect HubSpot OAuth or private-app token)."},
    "google_calendar": {"name": "Google Calendar", "description": "Google Calendar events (Connect Google Calendar OAuth)."},
    "google_sheets": {"name": "Google Sheets", "description": "Google Sheets rows (Connect Google Sheets OAuth)."},
    "telegram": {"name": "Telegram", "description": "Telegram bot token for the Telegram node."},
    "gmail": {"name": "Gmail", "description": "Gmail sending connection (Connect Gmail)."},
    # Phase 11 business connectors
    "postgres": {"name": "PostgreSQL", "description": "PostgreSQL connection string for the Postgres connector."},
    "mysql": {"name": "MySQL", "description": "MySQL/MariaDB connection string for the MySQL connector."},
    "google_drive": {"name": "Google Drive", "description": "Google Drive files (Connect Google Drive OAuth)."},
    "microsoft_graph": {"name": "Microsoft Graph", "description": "Azure app powering the Microsoft Teams and Outlook connectors."},
    "slack": {"name": "Slack Bot", "description": "Slack Web API bot token for the Slack connector."},
    "github": {"name": "GitHub", "description": "GitHub access token for the GitHub connector."},
    "notion": {"name": "Notion", "description": "Notion internal integration token for the Notion connector."},
    "jira": {"name": "Jira", "description": "Jira Cloud site + API token for the Jira connector."},
    "discord": {"name": "Discord", "description": "Discord bot token for the Discord connector."},
    "stripe": {"name": "Stripe", "description": "Stripe secret key for the Stripe connector."},
    "mongodb": {"name": "MongoDB", "description": "MongoDB connection URI for the MongoDB connector."},
    "redis": {"name": "Redis", "description": "Redis connection URI for the Redis connector (optional)."},
    "airtable": {"name": "Airtable", "description": "Airtable personal access token for the Airtable connector."},
    "shopify": {"name": "Shopify", "description": "Shopify Admin API connection for the Shopify connector."},
    # Batch B connectors
    "trello": {"name": "Trello", "description": "Trello API key + token for the Trello connector."},
    "asana": {"name": "Asana", "description": "Asana personal access token for the Asana connector."},
    "linear": {"name": "Linear", "description": "Linear API key for the Linear connector."},
    "calendly": {"name": "Calendly", "description": "Calendly personal access token for the Calendly connector."},
    "gitlab": {"name": "GitLab", "description": "GitLab personal access token for the GitLab connector."},
    "zoom": {"name": "Zoom", "description": "Zoom access token for the Zoom connector."},
    "twilio": {"name": "Twilio", "description": "Twilio Account SID + Auth Token for the Twilio connector."},
    "bitbucket": {"name": "Bitbucket", "description": "Bitbucket access token for the Bitbucket connector."},
    "whatsapp": {"name": "WhatsApp", "description": "Meta WhatsApp Business token + phone number ID for the WhatsApp connector."},
    "clickup": {"name": "ClickUp", "description": "ClickUp personal API token for the ClickUp connector."},
    "pipedrive": {"name": "Pipedrive", "description": "Pipedrive API token + company domain for the Pipedrive connector."},
    "dropbox": {"name": "Dropbox", "description": "Dropbox OAuth access token for the Dropbox connector."},
    "openai": {"name": "OpenAI", "description": "OpenAI API key (or compatible endpoint) for the OpenAI connector."},
    "basic_auth": {"name": "Basic Auth", "description": "Username and password for Basic authentication."},
    "bearer_auth": {"name": "Bearer Auth", "description": "Bearer token for Authorization header."},
    "header_auth": {"name": "Header Auth", "description": "Custom header (e.g. X-API-Key) authentication."},
    "query_auth": {"name": "Query Auth", "description": "API key via query parameter."},
    "digest_auth": {"name": "Digest Auth", "description": "Digest authentication (username, password, realm, nonce)."},
    "custom_auth": {"name": "Custom Auth", "description": "Custom headers / query / body auth injection."},
    "oauth2": {"name": "OAuth2 API", "description": "Generic OAuth2 (authorization URL, token URL, client credentials)."},
    "oauth1": {"name": "OAuth1 API", "description": "OAuth1 (HMAC-SHA1) authentication."},
    "api_key": {"name": "API Key", "description": "API key (header or query)."},
    "pat": {"name": "Personal Access Token", "description": "Personal Access Token (Bearer)."},
    "jwt": {"name": "JWT", "description": "JWT assertion (private key, client ID, subject)."},
    "service_account": {"name": "Service Account", "description": "Service account JSON (Google etc)."},
    "aws_iam": {"name": "AWS IAM", "description": "AWS IAM (access key, secret, region, service)."},
    "aws_assume_role": {"name": "AWS Assume Role", "description": "AWS STS AssumeRole (role ARN)."},
}


# Provider mapping: credential type → auth provider id
CREDENTIAL_PROVIDER: dict[str, str] = {
    "basic_auth": "basic",
    "bearer_auth": "bearer",
    "header_auth": "header",
    "query_auth": "query",
    "digest_auth": "digest",
    "custom_auth": "custom",
    "oauth2": "oauth2",
    "oauth1": "oauth1",
    "api_key": "api_key",
    "pat": "pat",
    "jwt": "jwt",
    "service_account": "service_account",
    "aws_iam": "aws_iam",
    "aws_assume_role": "aws_assume_role",
    # Legacy http maps to header/bearer depending on auth_type — resolved at runtime
    "http": "header",
    "salesforce": "oauth2",
    "hubspot": "oauth2",
    "google_calendar": "oauth2",
    "google_sheets": "oauth2",
    "gmail": "oauth2",
    "google_drive": "oauth2",
}

# Which credential types are considered fully implemented (provider exists and tested)
CREDENTIAL_IMPLEMENTED: dict[str, bool] = {
    # Generic providers — all implemented
    "basic_auth": True,
    "bearer_auth": True,
    "header_auth": True,
    "query_auth": True,
    "digest_auth": True,
    "custom_auth": True,
    "oauth2": True,
    "oauth1": True,
    "api_key": True,
    "pat": True,
    "jwt": True,
    "service_account": True,
    "aws_iam": True,
    "aws_assume_role": True,
    # Legacy / business — implemented if they have a working provider/connector
    "smtp": True,
    "imap": True,
    "database": True,
    "http": True,
    "llm": True,
    "salesforce": True,
    "hubspot": True,
    "google_calendar": True,
    "google_sheets": True,
    "telegram": True,
    "gmail": True,
    "postgres": True,
    "mysql": True,
    "google_drive": True,
    "microsoft_graph": False,
    "slack": True,
    "github": True,
    "notion": True,
    "jira": True,
    "discord": True,
    "stripe": True,
    "mongodb": True,
    "redis": True,
    "airtable": True,
    "shopify": True,
    # Batch B connectors
    "trello": True,
    "asana": True,
    "linear": True,
    "calendly": True,
    "gitlab": True,
    "zoom": True,
    "twilio": True,
    "bitbucket": True,
    "whatsapp": True,
    "clickup": True,
    "pipedrive": True,
    "dropbox": True,
    "openai": True,
}

# Predefined credential registry — exact huge list as requested, all implemented to make them work
PREDEFINED_CREDENTIALS: list[dict[str, Any]] = _HUGE_PREDEFINED if _HUGE_PREDEFINED else [
    {"id": "salesforce-oauth2", "displayName": "Salesforce OAuth2 API", "category": "predefined", "authType": "oauth2", "credentialType": "salesforce", "provider": "salesforce", "implemented": True, "supportsOAuth": True, "supportsRefresh": True, "supportsTest": True},
]


def get_provider_for_type(cred_type: str) -> str | None:
    return CREDENTIAL_PROVIDER.get(cred_type)


def is_implemented(cred_type: str) -> bool:
    return CREDENTIAL_IMPLEMENTED.get(cred_type, False)


def list_types() -> list[dict[str, Any]]:
    """Catalog for GET /api/credentials/types (drives the frontend form)."""
    return [
        {
            "type": t,
            **TYPE_META.get(t, {"name": t, "description": ""}),
            "secret_fields": sorted(SECRET_FIELDS.get(t, frozenset())),
            "parameters_schema": schema.model_json_schema(),
            "provider": CREDENTIAL_PROVIDER.get(t, ""),
            "implemented": CREDENTIAL_IMPLEMENTED.get(t, True),
            "supportsOAuth": t in ("oauth2", "oauth1", "salesforce", "hubspot", "google_calendar", "google_sheets", "gmail", "google_drive"),
            "supportsRefresh": t in ("oauth2", "salesforce", "hubspot", "google_calendar", "google_sheets", "gmail", "google_drive"),
            "supportsTest": CREDENTIAL_IMPLEMENTED.get(t, True),
        }
        for t, schema in CREDENTIAL_TYPES.items()
    ]


def validate_data(cred_type: str, data: dict[str, Any]) -> dict[str, Any]:
    """Validate + normalize credential data for a type; raises ValueError."""
    schema = CREDENTIAL_TYPES.get(cred_type)
    if schema is None:
        raise ValueError(f"Unknown credential type '{cred_type}'.")
    return schema.model_validate(data).model_dump(mode="json")


def is_known_type(cred_type: str) -> bool:
    return cred_type in CREDENTIAL_TYPES
