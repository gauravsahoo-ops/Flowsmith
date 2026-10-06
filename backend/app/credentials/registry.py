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


class ElasticsearchCredential(BaseModel):
    base_url: str = Field(default="", description="Cluster URL (https://host:9200).")
    endpoint: str = Field(default="", description="Alias for base_url (import compatibility).")
    api_key: str = Field(default="", description="Elasticsearch API key.")
    bearer_token: str = Field(default="", description="Bearer token for the Authorization header.")
    token: str = Field(default="", description="Alias for bearer_token (import compatibility).")
    username: str = Field(default="", description="Basic-auth username (optional).")
    password: str = Field(default="", description="Basic-auth password (optional).")


class LLMCredential(BaseModel):
    provider: str = Field(default="openai", description="Selected LLM provider ID.")
    variant: str = Field(default="", description="Provider regional or plan variant.")
    base_url: str = Field(
        default="https://api.openai.com/v1",
        description="Base URL for provider endpoint.",
    )
    api_key: str = Field(default="", description="API key or token.")
    model: str = Field(default="gpt-4o-mini", description="Model name or default identifier.")
    selected_model: str = Field(default="", description="Preferred selected model.")
    organization: str = Field(default="", description="Optional organization identifier.")
    api_version: str = Field(default="", description="Optional API version.")
    access_key_id: str = Field(default="", description="AWS Access Key ID for Bedrock.")
    secret_access_key: str = Field(default="", description="AWS Secret Access Key for Bedrock.")
    region: str = Field(default="", description="Cloud region.")
    session_token: str = Field(default="", description="AWS Session Token.")
    deployment: str = Field(default="", description="Azure deployment name.")
    endpoint: str = Field(default="", description="Custom endpoint or instance URL.")
    models_endpoint: str = Field(default="/models", description="Endpoint for model discovery.")
    chat_endpoint: str = Field(default="/chat/completions", description="Endpoint for chat completions.")
    provider_name: str = Field(default="", description="Custom provider display name.")
    default_model: str = Field(default="", description="Custom provider fallback model.")
    custom_headers: dict[str, str] = Field(default_factory=dict, description="Custom HTTP headers.")
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
    allowed_domains: str = Field(default="", description="Allowed HTTP request domains policy.")

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


class DynamicsCrmCredential(BaseModel):
    """Microsoft Dynamics 365 (Dataverse) connection.

    Two authentication methods:
    1. OAuth2 ('Connect Microsoft Dynamics 365'):
       User authorizes via Azure Entra ID; the refresh token is stored encrypted
       and access tokens are minted server-side on demand.
    2. Server-to-Server (Client Credentials):
       Azure App Registration service principal with client_id, client_secret,
       and tenant_id.
    """
    instance_url: str = Field(
        default="",
        description="Microsoft Dynamics 365 org URL, e.g. https://myorg.crm.dynamics.com",
    )
    auth_type: str = Field(
        default="oauth2",
        description="Authentication type: 'oauth2' or 'client_credentials'.",
    )
    tenant_id: str = Field(
        default="common",
        description="Azure AD / Entra ID Tenant ID (or 'common', 'organizations').",
    )
    client_id: str = Field(default="", description="Azure App Registration Application (client) ID.")
    client_secret: str = Field(default="", description="Azure App Registration Client Secret.")
    refresh_token: str = Field(default="", description="OAuth2 refresh token.")
    access_token: str = Field(default="", description="OAuth2 access token.")
    expires_at: float | None = Field(default=None, description="Access token expiry timestamp.")
    user: str = Field(default="", description="Authorizing user email / username (display label).")
    username: str = Field(default="", description="User display name.")
    user_id: str = Field(default="", description="Dataverse User ID (GUID).")
    organization_id: str = Field(default="", description="Dataverse Organization ID (GUID).")
    oauth: bool = Field(default=False, description="True when created via OAuth flow.")

    @model_validator(mode="after")
    def _validate_dynamics_auth(self) -> "DynamicsCrmCredential":
        if not self.instance_url.strip():
            raise ValueError("Microsoft Dynamics 365 credential requires an instance_url (e.g. https://org.crm.dynamics.com).")
        if self.auth_type == "client_credentials":
            if not self.client_id.strip() or not self.client_secret.strip():
                raise ValueError("Client Credentials authentication requires client_id and client_secret.")
        elif self.oauth:
            if not self.refresh_token.strip() and not self.access_token.strip():
                raise ValueError("OAuth authentication requires a refresh_token or access_token.")
        else:
            has_refresh = bool(self.refresh_token.strip())
            has_s2s = bool(self.client_id.strip() and self.client_secret.strip())
            if not has_refresh and not has_s2s:
                raise ValueError("Dynamics 365 credential needs either OAuth tokens or client_id/client_secret.")
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


class MailchimpCredential(BaseModel):
    api_key: str = Field(min_length=1, description="Mailchimp API key (Account > Extras > API keys, ends -usXX).")
    datacenter: str = Field(default="", description="Datacenter override (auto-parsed from key suffix when empty).")


class QuickBooksCredential(BaseModel):
    access_token: str = Field(min_length=1, description="QuickBooks Online OAuth access token.")
    refresh_token: str = Field(default="", description="OAuth refresh token (optional).")
    realm_id: str = Field(min_length=1, description="QuickBooks company realm ID.")
    environment: str = Field(default="sandbox", description="sandbox or production (default sandbox).")


class GoogleDocsCredential(BaseModel):
    """Google Docs connection. OAuth-only ('Connect Google Docs'): the refresh token is stored
    encrypted; access tokens are minted server-side on demand."""

    user: str = Field(default="", description="Authorizing account email (display label).")
    refresh_token: str = Field(min_length=1, description="OAuth2 refresh token from the authorization flow.")
    oauth: bool = Field(
        default=False,
        description="Created via 'Connect Google Docs'.",
    )

    @model_validator(mode="after")
    def _require_auth(self) -> "GoogleDocsCredential":
        if not self.refresh_token.strip():
            raise ValueError("A Google Docs credential needs a refresh_token (use 'Connect Google Docs').")
        return self


class PagerDutyCredential(BaseModel):
    api_token: str = Field(min_length=1, description="PagerDuty API token (Configuration > API Access).")


class ZendeskCredential(BaseModel):
    email: str = Field(min_length=1, description="Zendesk agent email.")
    api_token: str = Field(min_length=1, description="Zendesk API token.")
    subdomain: str = Field(min_length=1, description="Subdomain (acme in acme.zendesk.com).")


class TodoistCredential(BaseModel):
    api_token: str = Field(min_length=1, description="Todoist personal API token (Settings > Integrations).")


class BrevoCredential(BaseModel):
    api_key: str = Field(min_length=1, description="Brevo API key (SMTP & API > API Keys).")


class FreshdeskCredential(BaseModel):
    email: str = Field(min_length=1, description="Freshdesk agent email.")
    api_token: str = Field(min_length=1, description="Freshdesk API key (Profile Settings).")
    domain: str = Field(min_length=1, description="Domain (acme in acme.freshdesk.com).")


class MondayCredential(BaseModel):
    api_token: str = Field(min_length=1, description="Monday.com API token (avatar menu > Developers).")


class FtpCredential(BaseModel):
    host: str = Field(min_length=1, description="FTP server hostname.")
    port: int = Field(default=21, ge=1, le=65535, description="FTP port (21, or 990 for implicit FTPS).")
    username: str = Field(default="", description="FTP username (anonymous if empty and allowed).")
    password: str = Field(default="", description="FTP password.")
    secure: bool = Field(default=False, description="Use explicit FTPS (FTP_TLS).")


class SshCredential(BaseModel):
    host: str = Field(min_length=1, description="SSH server hostname.")
    port: int = Field(default=22, ge=1, le=65535, description="SSH port.")
    username: str = Field(min_length=1, description="SSH username.")
    password: str = Field(default="", description="Password (or leave empty for key auth).")
    private_key: str = Field(default="", description="PEM private key (or leave empty for password auth).")
    passphrase: str = Field(default="", description="Private key passphrase (optional).")

    @model_validator(mode="after")
    def _require_auth(self) -> "SshCredential":
        if not self.password.strip() and not self.private_key.strip():
            raise ValueError("An SSH credential needs a password or a private_key.")
        return self


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


class SupabaseCredential(BaseModel):
    url: str = Field(min_length=1, description="Supabase project URL (e.g. https://xyz.supabase.co).")
    service_role_key: str = Field(min_length=1, description="Supabase service role secret key or anon key.")
    anon_key: str = Field(default="", description="Supabase anon public key (optional).")


class ResendCredential(BaseModel):
    api_key: str = Field(min_length=1, description="Resend API key (re_...).")


class PineconeCredential(BaseModel):
    api_key: str = Field(min_length=1, description="Pinecone API key.")
    host: str = Field(default="", description="Default Pinecone index host URL (optional).")


class SentryCredential(BaseModel):
    auth_token: str = Field(min_length=1, description="Sentry User Auth Token.")
    organization_slug: str = Field(default="", description="Sentry Organization Slug (optional).")


class S3Credential(BaseModel):
    access_key_id: str = Field(min_length=1, description="AWS Access Key ID.")
    secret_access_key: str = Field(min_length=1, description="AWS Secret Access Key.")
    bucket_name: str = Field(default="", description="Default bucket name (optional).")
    region: str = Field(default="us-east-1", description="AWS Region (e.g. us-east-1).")
    endpoint_url: str = Field(default="", description="Custom endpoint URL for MinIO, Wasabi, or Cloudflare R2 (optional).")


# Phase 43 additions — Enterprise & AI Connectors
class ActiveCampaignCredential(BaseModel):
    account: str = Field(min_length=1, description="Account / Subdomain (e.g. myaccount in myaccount.api-us1.com).")
    api_key: str = Field(min_length=1, description="ActiveCampaign API Key (Settings > Developer).")


class AnthropicCredential(BaseModel):
    api_key: str = Field(min_length=1, description="Anthropic API Key (sk-ant-...).")


class BigQueryCredential(BaseModel):
    project_id: str = Field(min_length=1, description="Google Cloud Project ID.")
    access_token: str = Field(min_length=1, description="OAuth2 or Service Account Access Token.")


class BoxCredential(BaseModel):
    access_token: str = Field(min_length=1, description="Box Developer Token or OAuth 2.0 Access Token.")


class CodaCredential(BaseModel):
    api_key: str = Field(min_length=1, description="Coda Personal API Token (coda.io/account).")


class CoinGeckoCredential(BaseModel):
    api_key: str = Field(min_length=1, description="CoinGecko Demo or Pro API Key.")


class DocuSignCredential(BaseModel):
    account_id: str = Field(min_length=1, description="DocuSign API Account ID (GUID).")
    access_token: str = Field(min_length=1, description="OAuth 2.0 Access Token.")
    environment: str = Field(default="demo", description="Environment: demo, na2, na3, na4, eu.")


class FreshsalesCredential(BaseModel):
    domain: str = Field(min_length=1, description="Freshsales Domain Name (e.g. acme in acme.freshsales.io).")
    api_key: str = Field(min_length=1, description="Freshsales API Token.")


class GeminiCredential(BaseModel):
    api_key: str = Field(min_length=1, description="Google AI Studio Gemini API Key (AIzaSy...).")


class IntercomCredential(BaseModel):
    access_token: str = Field(min_length=1, description="Intercom Developer Workspace Access Token.")


class NetSuiteCredential(BaseModel):
    account_id: str = Field(min_length=1, description="Oracle NetSuite Account ID (e.g. 1234567 or TSTDRV1234567).")
    token: str = Field(default="", description="OAuth 2.0 Bearer Token (optional if using TBA).")
    consumer_key: str = Field(default="", description="Token-Based Authentication Consumer Key.")
    consumer_secret: str = Field(default="", description="Token-Based Authentication Consumer Secret.")
    token_id: str = Field(default="", description="Token-Based Authentication Token ID.")
    token_secret: str = Field(default="", description="Token-Based Authentication Token Secret.")


class OpenRouterCredential(BaseModel):
    access_token: str = Field(min_length=1, description="OpenRouter API Key (sk-or-...).")


class SAPCredential(BaseModel):
    base_url: str = Field(min_length=1, description="SAP S/4HANA Instance Base URL (e.g. https://my-s4hana.ondemand.com).")
    username: str = Field(default="", description="Communication / Technical Username.")
    password: str = Field(default="", description="Communication / Technical Password.")
    client: str = Field(default="", description="SAP Client / Mandant (e.g. 100).")
    token: str = Field(default="", description="OAuth 2.0 Bearer Token.")
    api_key: str = Field(default="", description="SAP Business Accelerator Hub API Key.")

    @model_validator(mode="after")
    def _validate_sap(self) -> "SAPCredential":
        if not (self.username and self.password) and not self.token and not self.api_key:
            raise ValueError("SAP requires username and password, token, or api_key.")
        return self


class SendGridCredential(BaseModel):
    api_key: str = Field(min_length=1, description="SendGrid API Key (SG....).")


class ServiceNowCredential(BaseModel):
    instance: str = Field(min_length=1, description="ServiceNow Instance Name or Domain (e.g. dev12345 or acme.service-now.com).")
    username: str = Field(default="", description="Basic Auth Username.")
    password: str = Field(default="", description="Basic Auth Password.")
    access_token: str = Field(default="", description="OAuth 2.0 Bearer Token (alternative to Basic Auth).")


class SnowflakeCredential(BaseModel):
    account: str = Field(min_length=1, description="Snowflake Account Identifier (e.g. xy12345.us-east-1).")
    token: str = Field(default="", description="Snowflake SQL API Bearer Token / Keypair JWT.")
    username: str = Field(default="", description="Snowflake Username.")
    password: str = Field(default="", description="Snowflake Password.")
    warehouse: str = Field(default="", description="Default Warehouse (optional).")
    database: str = Field(default="", description="Default Database (optional).")
    schema_name: str = Field(default="", description="Default Schema (optional).", alias="schema")
    role: str = Field(default="", description="Default Role (optional).")

    @model_validator(mode="after")
    def _validate_snowflake(self) -> "SnowflakeCredential":
        if not self.token and not (self.username and self.password):
            raise ValueError("Snowflake requires either a token or username/password.")
        return self


class TypeformCredential(BaseModel):
    token: str = Field(min_length=1, description="Typeform Personal Access Token.")


class WorkdayCredential(BaseModel):
    host: str = Field(min_length=1, description="Workday Host (e.g. https://wd2-impl-services1.workday.com).")
    tenant: str = Field(min_length=1, description="Workday Tenant Name.")
    token: str = Field(default="", description="OAuth2 Bearer Token.")
    client_id: str = Field(default="", description="Client ID (optional).")
    client_secret: str = Field(default="", description="Client Secret (optional).")


class XeroCredential(BaseModel):
    tenant_id: str = Field(min_length=1, description="Xero Tenant ID (GUID).")
    access_token: str = Field(min_length=1, description="OAuth 2.0 Access Token.")


class ZohoCrmCredential(BaseModel):
    access_token: str = Field(default="", description="Zoho CRM OAuth 2.0 Access Token.")
    refresh_token: str = Field(default="", description="Zoho CRM OAuth 2.0 Refresh Token.")
    client_id: str = Field(default="", description="Zoho OAuth Client ID.")
    client_secret: str = Field(default="", description="Zoho OAuth Client Secret.")
    accounts_server: str = Field(default="https://accounts.zoho.com", description="Accounts server URL.")

    @model_validator(mode="after")
    def _validate_zoho(self) -> "ZohoCrmCredential":
        if not self.access_token and not (self.client_id and self.client_secret and self.refresh_token):
            raise ValueError("Zoho CRM requires either access_token or (client_id, client_secret, refresh_token).")
        return self


class GroqCredential(BaseModel):
    api_key: str = Field(min_length=1, description="Groq API Key (gsk_...).")


class DeepSeekCredential(BaseModel):
    api_key: str = Field(min_length=1, description="DeepSeek API Key (sk-...).")


class SharePointCredential(BaseModel):
    access_token: str = Field(min_length=1, description="Microsoft Graph SharePoint Access Token.")
    site_url: str = Field(default="", description="SharePoint Site URL.")
    tenant_id: str = Field(default="", description="Azure Tenant ID.")
    client_id: str = Field(default="", description="Client ID.")
    client_secret: str = Field(default="", description="Client Secret.")


class OneDriveCredential(BaseModel):
    access_token: str = Field(min_length=1, description="Microsoft Graph OneDrive Access Token.")
    tenant_id: str = Field(default="", description="Azure Tenant ID.")
    client_id: str = Field(default="", description="Client ID.")
    client_secret: str = Field(default="", description="Client Secret.")




CREDENTIAL_TYPES: dict[str, type[BaseModel]] = {
    "smtp": SMTPCredential,
    "imap": IMAPCredential,
    "database": DatabaseCredential,
    "http": HTTPCredential,
    "elasticsearch": ElasticsearchCredential,
    "llm": LLMCredential,
    "salesforce": SalesforceCredential,
    "hubspot": HubSpotCredential,
    "dynamics_crm": DynamicsCrmCredential,
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
    "mailchimp": MailchimpCredential,
    "quickbooks": QuickBooksCredential,
    "google_docs": GoogleDocsCredential,
    "pagerduty": PagerDutyCredential,
    "zendesk": ZendeskCredential,
    "todoist": TodoistCredential,
    "brevo": BrevoCredential,
    "freshdesk": FreshdeskCredential,
    "monday": MondayCredential,
    "ftp": FtpCredential,
    "ssh": SshCredential,
    "supabase": SupabaseCredential,
    "resend": ResendCredential,
    "pinecone": PineconeCredential,
    "sentry": SentryCredential,
    "aws_s3": S3Credential,
    "s3": S3Credential,
    # Phase 43 additions
    "activecampaign": ActiveCampaignCredential,
    "anthropic": AnthropicCredential,
    "bigquery": BigQueryCredential,
    "box": BoxCredential,
    "coda": CodaCredential,
    "coin_gecko": CoinGeckoCredential,
    "docusign": DocuSignCredential,
    "freshsales": FreshsalesCredential,
    "gemini": GeminiCredential,
    "intercom": IntercomCredential,
    "netsuite": NetSuiteCredential,
    "open_router": OpenRouterCredential,
    "sap": SAPCredential,
    "sendgrid": SendGridCredential,
    "servicenow": ServiceNowCredential,
    "snowflake": SnowflakeCredential,
    "typeform": TypeformCredential,
    "workday": WorkdayCredential,
    "xero": XeroCredential,
    "zoho_crm": ZohoCrmCredential,
    "groq": GroqCredential,
    "deepseek": DeepSeekCredential,
    "sharepoint": SharePointCredential,
    "onedrive": OneDriveCredential,
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
    "elasticsearch": frozenset({"api_key", "password", "bearer_token", "token"}),
    "llm": frozenset({"api_key"}),
    "salesforce": frozenset({"client_secret", "password", "refresh_token"}),
    "hubspot": frozenset({"refresh_token", "private_token"}),
    "dynamics_crm": frozenset({"client_secret", "refresh_token", "access_token"}),
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
    "mailchimp": frozenset({"api_key"}),
    "quickbooks": frozenset({"access_token", "refresh_token"}),
    "google_docs": frozenset({"refresh_token"}),
    "pagerduty": frozenset({"api_token"}),
    "zendesk": frozenset({"api_token"}),
    "todoist": frozenset({"api_token"}),
    "brevo": frozenset({"api_key"}),
    "freshdesk": frozenset({"api_token"}),
    "monday": frozenset({"api_token"}),
    "ftp": frozenset({"password"}),
    "ssh": frozenset({"password", "private_key", "passphrase"}),
    "supabase": frozenset({"service_role_key", "anon_key"}),
    "resend": frozenset({"api_key"}),
    "pinecone": frozenset({"api_key"}),
    "sentry": frozenset({"auth_token"}),
    "aws_s3": frozenset({"secret_access_key"}),
    "s3": frozenset({"secret_access_key"}),
    # Phase 43 additions
    "activecampaign": frozenset({"api_key"}),
    "anthropic": frozenset({"api_key"}),
    "bigquery": frozenset({"access_token"}),
    "box": frozenset({"access_token"}),
    "coda": frozenset({"api_key"}),
    "coin_gecko": frozenset({"api_key"}),
    "docusign": frozenset({"access_token"}),
    "freshsales": frozenset({"api_key"}),
    "gemini": frozenset({"api_key"}),
    "intercom": frozenset({"access_token"}),
    "netsuite": frozenset({"token", "consumer_secret", "token_secret"}),
    "open_router": frozenset({"access_token"}),
    "sap": frozenset({"password", "token", "client_secret", "api_key"}),
    "sendgrid": frozenset({"api_key"}),
    "servicenow": frozenset({"password", "access_token"}),
    "snowflake": frozenset({"token"}),
    "typeform": frozenset({"token"}),
    "workday": frozenset({"token", "client_secret", "refresh_token"}),
    "xero": frozenset({"access_token"}),
    "zoho_crm": frozenset({"access_token"}),
    "groq": frozenset({"api_key"}),
    "deepseek": frozenset({"api_key"}),
    "sharepoint": frozenset({"access_token", "client_secret"}),
    "onedrive": frozenset({"access_token", "client_secret"}),
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
    "elasticsearch": {"name": "Elasticsearch", "description": "Elasticsearch / OpenSearch cluster connection for the Elasticsearch node."},
    "llm": {"name": "LLM", "description": "OpenAI-compatible model endpoint for the AI nodes."},
    "salesforce": {"name": "Salesforce", "description": "Salesforce org connection (OAuth2 password or refresh-token grant)."},
    "hubspot": {"name": "HubSpot", "description": "HubSpot CRM connection (Connect HubSpot OAuth or private-app token)."},
    "dynamics_crm": {"name": "Microsoft Dynamics 365", "description": "Microsoft Dynamics 365 CRM (Dataverse) connection."},
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
    "mailchimp": {"name": "Mailchimp", "description": "Mailchimp API key for the Mailchimp connector."},
    "quickbooks": {"name": "QuickBooks", "description": "QuickBooks Online OAuth token + realm for the QuickBooks connector."},
    "google_docs": {"name": "Google Docs", "description": "Google Docs documents (Connect Google Docs OAuth)."},
    "pagerduty": {"name": "PagerDuty", "description": "PagerDuty API token for the PagerDuty connector."},
    "zendesk": {"name": "Zendesk", "description": "Zendesk email + API token + subdomain for the Zendesk connector."},
    "todoist": {"name": "Todoist", "description": "Todoist personal API token for the Todoist connector."},
    "brevo": {"name": "Brevo", "description": "Brevo API key for the Brevo connector."},
    "freshdesk": {"name": "Freshdesk", "description": "Freshdesk email + API key + domain for the Freshdesk connector."},
    "monday": {"name": "Monday.com", "description": "Monday.com API token for the Monday connector."},
    "supabase": {"name": "Supabase", "description": "Supabase project URL and service role / anon API key."},
    "resend": {"name": "Resend", "description": "Resend API key for transactional email sending."},
    "pinecone": {"name": "Pinecone", "description": "Pinecone API key for vector embeddings database."},
    "sentry": {"name": "Sentry", "description": "Sentry Auth Token for error tracking and issue management."},
    "aws_s3": {"name": "AWS S3", "description": "AWS S3 / S3-compatible object storage access credentials."},
    "s3": {"name": "AWS S3 / Storage", "description": "AWS S3, MinIO, or Cloudflare R2 credentials."},
    "activecampaign": {"name": "ActiveCampaign", "description": "ActiveCampaign Marketing API credentials."},
    "anthropic": {"name": "Anthropic Claude", "description": "Anthropic Claude LLM API key."},
    "bigquery": {"name": "Google Cloud BigQuery", "description": "GCP BigQuery project ID and access token."},
    "box": {"name": "Box", "description": "Box cloud storage access token."},
    "coda": {"name": "Coda", "description": "Coda docs and tables API token."},
    "coin_gecko": {"name": "CoinGecko", "description": "CoinGecko cryptocurrency market data API key."},
    "docusign": {"name": "DocuSign", "description": "DocuSign eSignature OAuth access token."},
    "freshsales": {"name": "Freshsales", "description": "Freshsales CRM domain and API key."},
    "gemini": {"name": "Google Gemini", "description": "Google AI Studio / Gemini API key."},
    "intercom": {"name": "Intercom", "description": "Intercom customer messaging workspace token."},
    "netsuite": {"name": "Oracle NetSuite", "description": "Oracle NetSuite ERP TBA or OAuth token."},
    "open_router": {"name": "OpenRouter", "description": "OpenRouter multi-model AI routing API key."},
    "sap": {"name": "SAP S/4HANA", "description": "SAP S/4HANA Enterprise ERP communication credentials."},
    "sendgrid": {"name": "SendGrid", "description": "Twilio SendGrid transactional email API key."},
    "servicenow": {"name": "ServiceNow", "description": "ServiceNow ITSM enterprise credentials."},
    "snowflake": {"name": "Snowflake", "description": "Snowflake cloud data warehouse SQL API token."},
    "typeform": {"name": "Typeform", "description": "Typeform online forms and surveys API token."},
    "workday": {"name": "Workday", "description": "Workday Human Capital Management OAuth2 credentials."},
    "xero": {"name": "Xero", "description": "Xero cloud accounting OAuth2 token."},
    "zoho_crm": {"name": "Zoho CRM", "description": "Zoho CRM REST API v2 OAuth token."},
    "groq": {"name": "Groq", "description": "Groq LPU ultra-fast AI inference API key."},
    "deepseek": {"name": "DeepSeek", "description": "DeepSeek LLM API key."},
    "sharepoint": {"name": "Microsoft SharePoint", "description": "Microsoft Graph SharePoint document library credentials."},
    "onedrive": {"name": "Microsoft OneDrive", "description": "Microsoft Graph OneDrive cloud storage credentials."},
    "ftp": {"name": "FTP", "description": "FTP/FTPS server connection for the FTP node."},
    "ssh": {"name": "SSH", "description": "SSH server connection (password or key) for the SSH node."},
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
    "elasticsearch": "header",
    "salesforce": "salesforce",
    "hubspot": "oauth2",
    "dynamics_crm": "oauth2",
    "google_calendar": "oauth2",
    "google_sheets": "oauth2",
    "gmail": "oauth2",
    "google_drive": "oauth2",
    # Enterprise & AI additions
    "activecampaign": "api_key",
    "anthropic": "api_key",
    "bigquery": "service_account",
    "box": "bearer",
    "coda": "bearer",
    "coin_gecko": "api_key",
    "docusign": "bearer",
    "freshsales": "api_key",
    "gemini": "api_key",
    "intercom": "bearer",
    "netsuite": "client_credentials",
    "open_router": "bearer",
    "sap": "basic",
    "sendgrid": "bearer",
    "servicenow": "basic",
    "snowflake": "bearer",
    "typeform": "bearer",
    "workday": "bearer",
    "xero": "oauth2",
    "zoho_crm": "oauth2",
    "groq": "api_key",
    "deepseek": "api_key",
    "sharepoint": "oauth2",
    "onedrive": "oauth2",
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
    "elasticsearch": True,
    "llm": True,
    "salesforce": True,
    "hubspot": True,
    "dynamics_crm": True,
    "google_calendar": True,
    "google_sheets": True,
    "telegram": True,
    "gmail": True,
    "postgres": True,
    "mysql": True,
    "google_drive": True,
    "microsoft_graph": True,
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
    "mailchimp": True,
    "quickbooks": True,
    "google_docs": True,
    "pagerduty": True,
    "zendesk": True,
    "todoist": True,
    "ftp": True,
    "ssh": True,
    "brevo": True,
    "freshdesk": True,
    "monday": True,
    "supabase": True,
    "resend": True,
    "pinecone": True,
    "sentry": True,
    "aws_s3": True,
    "s3": True,
    # Phase 43 implementations
    "activecampaign": True,
    "anthropic": True,
    "bigquery": True,
    "box": True,
    "coda": True,
    "coin_gecko": True,
    "docusign": True,
    "freshsales": True,
    "gemini": True,
    "intercom": True,
    "netsuite": True,
    "open_router": True,
    "sap": True,
    "sendgrid": True,
    "servicenow": True,
    "snowflake": True,
    "typeform": True,
    "workday": True,
    "xero": True,
    "zoho_crm": True,
    # Backlog connectors pending implementation
    "groq": False,
    "deepseek": False,
    "sharepoint": False,
    "onedrive": False,
}

# Predefined credential registry — exact huge list as requested, all implemented to make them work
PREDEFINED_CREDENTIALS: list[dict[str, Any]] = _HUGE_PREDEFINED if _HUGE_PREDEFINED else [
    {"id": "salesforce-oauth2", "displayName": "Salesforce OAuth2 API", "category": "predefined", "authType": "oauth2", "credentialType": "salesforce", "provider": "salesforce", "implemented": True, "supportsOAuth": True, "supportsRefresh": True, "supportsTest": True},
]


def get_provider_for_type(cred_type: str) -> str | None:
    return CREDENTIAL_PROVIDER.get(cred_type)


def is_implemented(cred_type: str) -> bool:
    # Unknown types are blocked; types registered into CREDENTIAL_TYPES
    # (including dynamically registered connectors) are implemented unless
    # CREDENTIAL_IMPLEMENTED explicitly marks them pending.
    return CREDENTIAL_IMPLEMENTED.get(cred_type, cred_type in CREDENTIAL_TYPES)


def list_types() -> list[dict[str, Any]]:
    """Catalog for GET /api/credentials/types (drives the frontend form)."""
    from app.credentials.auth_metadata import get_connector_auth_metadata, AuthMethod

    oauth_types = frozenset({
        "oauth2", "oauth1", "salesforce", "hubspot", "dynamics_crm",
        "google_calendar", "google_sheets", "gmail", "google_drive", "google_docs",
        "zoho_crm", "xero", "box", "typeform", "sharepoint", "onedrive", "quickbooks",
    })
    refresh_types = frozenset({
        "oauth2", "salesforce", "hubspot", "dynamics_crm",
        "google_calendar", "google_sheets", "gmail", "google_drive", "google_docs",
        "quickbooks", "sharepoint", "onedrive",
    })

    out = []
    for t, schema in CREDENTIAL_TYPES.items():
        meta = TYPE_META.get(t, {"name": t, "description": ""})
        auth_meta = get_connector_auth_metadata(t)
        is_impl = CREDENTIAL_IMPLEMENTED.get(t, True)
        status_val = "available" if is_impl else "coming_soon"

        if auth_meta:
            auth_method_label = auth_meta.auth_method.value if isinstance(auth_meta.auth_method, AuthMethod) else str(auth_meta.auth_method)
        else:
            auth_method_label = (
                "OAuth 2.0" if t in oauth_types
                else "Basic Auth" if t in ("basic_auth", "jira", "bitbucket", "freshdesk", "zendesk", "twilio", "sap", "servicenow")
                else "Bearer Token" if t in ("bearer_auth", "github", "gitlab", "slack", "stripe", "openai", "sendgrid", "resend", "sentry", "intercom", "snowflake", "whatsapp", "calendly", "todoist", "open_router")
                else "API Key"
            )

        out.append({
            "type": t,
            **meta,
            "secret_fields": sorted(SECRET_FIELDS.get(t, frozenset())),
            "parameters_schema": schema.model_json_schema(),
            "provider": CREDENTIAL_PROVIDER.get(t, ""),
            "implemented": is_impl,
            "status": status_val,
            "auth_method": auth_method_label,
            "supportsOAuth": t in oauth_types,
            "supportsRefresh": t in refresh_types,
            "supportsTest": is_impl,
        })
    return out


def validate_data(cred_type: str, data: dict[str, Any]) -> dict[str, Any]:
    """Validate + normalize credential data for a type; raises ValueError."""
    schema = CREDENTIAL_TYPES.get(cred_type)
    if schema is None:
        raise ValueError(f"Unknown credential type '{cred_type}'.")
    return schema.model_validate(data).model_dump(mode="json")


def is_known_type(cred_type: str) -> bool:
    return cred_type in CREDENTIAL_TYPES


def redact_data(cred_type: str, data: dict[str, Any]) -> dict[str, Any]:
    """Redact secret fields from credential data dict for safe display."""
    secrets = SECRET_FIELDS.get(cred_type, frozenset())
    out = dict(data)
    for f in secrets:
        if f in out and out[f]:
            out[f] = "••••••••"
    return out
