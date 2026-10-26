"""Native REST connectors for catalog conversion batch 12.

Each connector uses a fixed vendor host and an explicit auth contract. Microsoft
Graph connectors use ``https://graph.microsoft.com`` with a bearer access token,
matching the n8n Microsoft nodes in this batch. Dataverse and Dynamics CRM keep
the environment-specific hosts that their n8n nodes build from credential
values; those hosts are still template-driven (never an arbitrary endpoint_url).

Keys whose n8n node is a local transform, a platform-internal action, or a
protocol the shared :class:`~app.connectors.vendor_rest.VendorRESTConnector`
cannot speak are listed in :data:`UNSUPPORTED_BATCH12_KEYS` with the specific
reason instead of being given invented endpoints. Operations that only accept
or return raw binary content are omitted because the shared connector sends
JSON bodies and parses JSON responses.
"""

from __future__ import annotations

from typing import Any

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)
from app.connectors.vendor_rest import VendorOperation, VendorRESTConnector, VendorSpec


GRAPH_V1 = "https://graph.microsoft.com/v1.0"

BATCH12_CATALOG_KEYS = frozenset({
    "microsoft_dataverse",
    "microsoft_dynamics_crm",
    "microsoft_entra",
    "microsoft_excel",
    "microsoft_excel_share_point",
    "microsoft_graph_security",
    "microsoft_one_drive",
    "microsoft_outlook",
    "microsoft_sharepoint",
    "microsoft_sql",
})


VENDOR_SPECS: dict[str, VendorSpec] = {
    "microsoft_dataverse": VendorSpec(
        key="microsoft_dataverse",
        display_name="Microsoft Dataverse",
        description=(
            "Microsoft Dataverse table rows through the Web API. Provide the "
            "environment host (for example, yourorg.crm.dynamics.com) without a URL scheme."
        ),
        category="database",
        base_url="https://{environment_host}/api/data/v9.2",
        auth_kind="bearer",
        credential_fields=("access_token",),
        extra_required=("environment_host",),
        operations={
            "create_row": VendorOperation(
                "create_row", "Create Row", "POST", "/{entity_set}",
                ("entity_set",), retryable=False, idempotency="non_idempotent",
                description="Create a row; the body is the Dataverse record payload.",
            ),
            "delete_row": VendorOperation(
                "delete_row", "Delete Row", "DELETE", "/{entity_set}({record_id})",
                ("entity_set", "record_id"),
            ),
            "get_row": VendorOperation(
                "get_row", "Get Row", "GET", "/{entity_set}({record_id})",
                ("entity_set", "record_id"),
            ),
            "list_rows": VendorOperation(
                "list_rows", "List Rows", "GET", "/{entity_set}", ("entity_set",),
                description="List rows; pass OData options such as $select, $filter, or $top as query params.",
            ),
            "update_row": VendorOperation(
                "update_row", "Update Row", "PATCH", "/{entity_set}({record_id})",
                ("entity_set", "record_id"),
                description="Update a row; the body is the Dataverse record payload.",
            ),
            "upsert_row": VendorOperation(
                "upsert_row", "Upsert Row", "PATCH", "/{entity_set}({record_id})",
                ("entity_set", "record_id"),
                description="Upsert a row by record ID; the body is the Dataverse record payload.",
            ),
        },
    ),
    "microsoft_dynamics_crm": VendorSpec(
        key="microsoft_dynamics_crm",
        display_name="Microsoft Dynamics CRM",
        description=(
            "Microsoft Dynamics CRM accounts through the Web API. Provide the "
            "tenant subdomain and region (for example, crm.dynamics.com)."
        ),
        category="crm",
        base_url="https://{subdomain}.{region}/api/data/v9.2",
        auth_kind="bearer",
        credential_fields=("access_token",),
        extra_required=("subdomain", "region"),
        operations={
            "create_account": VendorOperation(
                "create_account", "Create Account", "POST", "/accounts", (),
                retryable=False, idempotency="non_idempotent",
            ),
            "delete_account": VendorOperation(
                "delete_account", "Delete Account", "DELETE", "/accounts({account_id})",
                ("account_id",),
            ),
            "get_account": VendorOperation(
                "get_account", "Get Account", "GET", "/accounts({account_id})",
                ("account_id",),
            ),
            "list_accounts": VendorOperation(
                "list_accounts", "List Accounts", "GET", "/accounts", (),
                description="List accounts; pass OData options such as $select or $filter as query params.",
            ),
            "update_account": VendorOperation(
                "update_account", "Update Account", "PATCH", "/accounts({account_id})",
                ("account_id",),
                description="Update an account; the body is the Dynamics account payload.",
            ),
        },
    ),
    "microsoft_entra": VendorSpec(
        key="microsoft_entra",
        display_name="Microsoft Entra ID",
        description="Microsoft Entra ID users and groups through Microsoft Graph.",
        category="developer",
        base_url=GRAPH_V1,
        auth_kind="bearer",
        credential_fields=("access_token",),
        operations={
            "add_user_to_group": VendorOperation(
                "add_user_to_group", "Add User to Group", "POST",
                "/groups/{group_id}/members/$ref", ("group_id",),
                retryable=False, idempotency="non_idempotent",
                description="Add a user to a group; the body must contain @odata.id for the user.",
            ),
            "create_group": VendorOperation(
                "create_group", "Create Group", "POST", "/groups", (),
                retryable=False, idempotency="non_idempotent",
            ),
            "create_user": VendorOperation(
                "create_user", "Create User", "POST", "/users", (),
                retryable=False, idempotency="non_idempotent",
            ),
            "delete_group": VendorOperation(
                "delete_group", "Delete Group", "DELETE", "/groups/{group_id}", ("group_id",),
            ),
            "delete_user": VendorOperation(
                "delete_user", "Delete User", "DELETE", "/users/{user_id}", ("user_id",),
            ),
            "get_group": VendorOperation(
                "get_group", "Get Group", "GET", "/groups/{group_id}", ("group_id",),
            ),
            "get_user": VendorOperation(
                "get_user", "Get User", "GET", "/users/{user_id}", ("user_id",),
            ),
            "list_groups": VendorOperation(
                "list_groups", "List Groups", "GET", "/groups",
                description="List groups; pass $select, $filter, or $search as query params.",
            ),
            "list_users": VendorOperation(
                "list_users", "List Users", "GET", "/users",
                description="List users; pass $select, $filter, or $top as query params.",
            ),
            "remove_user_from_group": VendorOperation(
                "remove_user_from_group", "Remove User from Group", "DELETE",
                "/groups/{group_id}/members/{user_id}/$ref", ("group_id", "user_id"),
            ),
            "update_group": VendorOperation(
                "update_group", "Update Group", "PATCH", "/groups/{group_id}", ("group_id",),
            ),
            "update_user": VendorOperation(
                "update_user", "Update User", "PATCH", "/users/{user_id}", ("user_id",),
            ),
        },
    ),
    "microsoft_excel": VendorSpec(
        key="microsoft_excel",
        display_name="Microsoft Excel",
        description="Microsoft Excel workbooks in the signed-in user's OneDrive through Microsoft Graph.",
        category="productivity",
        base_url=f"{GRAPH_V1}/me",
        auth_kind="bearer",
        credential_fields=("access_token",),
        operations={
            "add_worksheet": VendorOperation(
                "add_worksheet", "Add Worksheet", "POST",
                "/drive/items/{workbook_id}/workbook/worksheets/add", ("workbook_id",),
                retryable=False, idempotency="non_idempotent",
            ),
            "append_table_rows": VendorOperation(
                "append_table_rows", "Append Table Rows", "POST",
                "/drive/items/{workbook_id}/workbook/worksheets/{worksheet_id}/tables/{table_id}/rows/add",
                ("workbook_id", "worksheet_id", "table_id"),
                retryable=False, idempotency="non_idempotent",
                description="Append rows to a table; the body accepts a values array.",
            ),
            "clear_range": VendorOperation(
                "clear_range", "Clear Range", "POST",
                "/drive/items/{workbook_id}/workbook/worksheets/{worksheet_id}/range(address='{range}')/clear",
                ("workbook_id", "worksheet_id", "range"),
                retryable=False, idempotency="non_idempotent",
                description="Clear a worksheet range; the body accepts applyTo.",
            ),
            "create_table": VendorOperation(
                "create_table", "Create Table", "POST",
                "/drive/items/{workbook_id}/workbook/worksheets/{worksheet_id}/tables/add",
                ("workbook_id", "worksheet_id"),
                retryable=False, idempotency="non_idempotent",
                description="Create a table; the body accepts address and hasHeaders.",
            ),
            "delete_workbook": VendorOperation(
                "delete_workbook", "Delete Workbook", "DELETE",
                "/drive/items/{workbook_id}", ("workbook_id",),
            ),
            "delete_worksheet": VendorOperation(
                "delete_worksheet", "Delete Worksheet", "DELETE",
                "/drive/items/{workbook_id}/workbook/worksheets/{worksheet_id}",
                ("workbook_id", "worksheet_id"),
            ),
            "get_table_rows": VendorOperation(
                "get_table_rows", "Get Table Rows", "GET",
                "/drive/items/{workbook_id}/workbook/worksheets/{worksheet_id}/tables/{table_id}/rows",
                ("workbook_id", "worksheet_id", "table_id"),
            ),
            "list_tables": VendorOperation(
                "list_tables", "List Tables", "GET",
                "/drive/items/{workbook_id}/workbook/worksheets/{worksheet_id}/tables",
                ("workbook_id", "worksheet_id"),
            ),
            "list_workbooks": VendorOperation(
                "list_workbooks", "List Workbooks", "GET", "/drive/root/search(q='.xlsx')",
                description="Search the user's drive for .xlsx workbooks.",
            ),
            "list_worksheets": VendorOperation(
                "list_worksheets", "List Worksheets", "GET",
                "/drive/items/{workbook_id}/workbook/worksheets", ("workbook_id",),
            ),
            "read_range": VendorOperation(
                "read_range", "Read Range", "GET",
                "/drive/items/{workbook_id}/workbook/worksheets/{worksheet_id}/range(address='{range}')",
                ("workbook_id", "worksheet_id", "range"),
            ),
            "update_range": VendorOperation(
                "update_range", "Update Range", "PATCH",
                "/drive/items/{workbook_id}/workbook/worksheets/{worksheet_id}/range(address='{range}')",
                ("workbook_id", "worksheet_id", "range"),
                description="Update a worksheet range; the body accepts values.",
            ),
        },
    ),
    "microsoft_excel_share_point": VendorSpec(
        key="microsoft_excel_share_point",
        display_name="Microsoft Excel (SharePoint)",
        description=(
            "Microsoft Excel workbooks stored in a SharePoint document library "
            "through Microsoft Graph."
        ),
        category="productivity",
        base_url=GRAPH_V1,
        auth_kind="bearer",
        credential_fields=("access_token",),
        operations={
            "add_worksheet": VendorOperation(
                "add_worksheet", "Add Worksheet", "POST",
                "/sites/{site_id}/drives/{drive_id}/items/{workbook_id}/workbook/worksheets/add",
                ("site_id", "drive_id", "workbook_id"),
                retryable=False, idempotency="non_idempotent",
            ),
            "append_table_rows": VendorOperation(
                "append_table_rows", "Append Table Rows", "POST",
                "/sites/{site_id}/drives/{drive_id}/items/{workbook_id}/workbook/tables/{table_id}/rows/add",
                ("site_id", "drive_id", "workbook_id", "table_id"),
                retryable=False, idempotency="non_idempotent",
                description="Append rows to a table; the body accepts a values array.",
            ),
            "clear_range": VendorOperation(
                "clear_range", "Clear Range", "POST",
                "/sites/{site_id}/drives/{drive_id}/items/{workbook_id}/workbook/worksheets/{worksheet_id}"
                "/range(address='{range}')/clear",
                ("site_id", "drive_id", "workbook_id", "worksheet_id", "range"),
                retryable=False, idempotency="non_idempotent",
                description="Clear a worksheet range; the body accepts applyTo.",
            ),
            "create_table": VendorOperation(
                "create_table", "Create Table", "POST",
                "/sites/{site_id}/drives/{drive_id}/items/{workbook_id}/workbook/worksheets/{worksheet_id}"
                "/tables/add",
                ("site_id", "drive_id", "workbook_id", "worksheet_id"),
                retryable=False, idempotency="non_idempotent",
                description="Create a table; the body accepts address and hasHeaders.",
            ),
            "delete_workbook": VendorOperation(
                "delete_workbook", "Delete Workbook", "DELETE",
                "/sites/{site_id}/drives/{drive_id}/items/{workbook_id}",
                ("site_id", "drive_id", "workbook_id"),
            ),
            "delete_worksheet": VendorOperation(
                "delete_worksheet", "Delete Worksheet", "DELETE",
                "/sites/{site_id}/drives/{drive_id}/items/{workbook_id}/workbook/worksheets/{worksheet_id}",
                ("site_id", "drive_id", "workbook_id", "worksheet_id"),
            ),
            "get_table_rows": VendorOperation(
                "get_table_rows", "Get Table Rows", "GET",
                "/sites/{site_id}/drives/{drive_id}/items/{workbook_id}/workbook/tables/{table_id}/rows",
                ("site_id", "drive_id", "workbook_id", "table_id"),
            ),
            "list_tables": VendorOperation(
                "list_tables", "List Tables", "GET",
                "/sites/{site_id}/drives/{drive_id}/items/{workbook_id}/workbook/tables",
                ("site_id", "drive_id", "workbook_id"),
            ),
            "list_workbooks": VendorOperation(
                "list_workbooks", "List Workbooks", "GET",
                "/sites/{site_id}/drives/{drive_id}/root/search(q='.xlsx')",
                ("site_id", "drive_id"),
                description="Search a SharePoint drive for .xlsx workbooks.",
            ),
            "list_worksheets": VendorOperation(
                "list_worksheets", "List Worksheets", "GET",
                "/sites/{site_id}/drives/{drive_id}/items/{workbook_id}/workbook/worksheets",
                ("site_id", "drive_id", "workbook_id"),
            ),
            "read_range": VendorOperation(
                "read_range", "Read Range", "GET",
                "/sites/{site_id}/drives/{drive_id}/items/{workbook_id}/workbook/worksheets/{worksheet_id}"
                "/range(address='{range}')",
                ("site_id", "drive_id", "workbook_id", "worksheet_id", "range"),
            ),
            "update_range": VendorOperation(
                "update_range", "Update Range", "PATCH",
                "/sites/{site_id}/drives/{drive_id}/items/{workbook_id}/workbook/worksheets/{worksheet_id}"
                "/range(address='{range}')",
                ("site_id", "drive_id", "workbook_id", "worksheet_id", "range"),
                description="Update a worksheet range; the body accepts values.",
            ),
        },
    ),
    "microsoft_graph_security": VendorSpec(
        key="microsoft_graph_security",
        display_name="Microsoft Graph Security",
        description="Microsoft Graph Security secure scores and secure score control profiles.",
        category="developer",
        base_url=f"{GRAPH_V1}/security",
        auth_kind="bearer",
        credential_fields=("access_token",),
        operations={
            "get_secure_score": VendorOperation(
                "get_secure_score", "Get Secure Score", "GET",
                "/secureScores/{secure_score_id}", ("secure_score_id",),
            ),
            "get_secure_score_control_profile": VendorOperation(
                "get_secure_score_control_profile", "Get Secure Score Control Profile", "GET",
                "/secureScoreControlProfiles/{secure_score_control_profile_id}",
                ("secure_score_control_profile_id",),
            ),
            "list_secure_score_control_profiles": VendorOperation(
                "list_secure_score_control_profiles", "List Secure Score Control Profiles", "GET",
                "/secureScoreControlProfiles",
                description="List control profiles; pass $filter or $top as query params.",
            ),
            "list_secure_scores": VendorOperation(
                "list_secure_scores", "List Secure Scores", "GET", "/secureScores",
                description="List secure scores; pass $filter or $top as query params.",
            ),
            "update_secure_score_control_profile": VendorOperation(
                "update_secure_score_control_profile", "Update Secure Score Control Profile", "PATCH",
                "/secureScoreControlProfiles/{secure_score_control_profile_id}",
                ("secure_score_control_profile_id",),
                description="Update a control profile; the body accepts vendorInformation and control state fields.",
            ),
        },
    ),
    "microsoft_one_drive": VendorSpec(
        key="microsoft_one_drive",
        display_name="Microsoft OneDrive",
        description="Microsoft OneDrive files and folders through Microsoft Graph.",
        category="productivity",
        base_url=f"{GRAPH_V1}/me",
        auth_kind="bearer",
        credential_fields=("access_token",),
        operations={
            "copy_file": VendorOperation(
                "copy_file", "Copy File", "POST", "/drive/items/{file_id}/copy", ("file_id",),
                retryable=False, idempotency="non_idempotent",
                description="Copy a file; the body accepts parentReference and name.",
            ),
            "create_folder": VendorOperation(
                "create_folder", "Create Folder", "POST",
                "/drive/items/{parent_id}/children", ("parent_id",),
                retryable=False, idempotency="non_idempotent",
                description="Create a folder; the body accepts name and folder.",
            ),
            "delete_file": VendorOperation(
                "delete_file", "Delete File", "DELETE", "/drive/items/{file_id}", ("file_id",),
            ),
            "delete_folder": VendorOperation(
                "delete_folder", "Delete Folder", "DELETE",
                "/drive/items/{folder_id}", ("folder_id",),
            ),
            "get_file": VendorOperation(
                "get_file", "Get File", "GET", "/drive/items/{file_id}", ("file_id",),
            ),
            "list_folder_children": VendorOperation(
                "list_folder_children", "List Folder Children", "GET",
                "/drive/items/{folder_id}/children", ("folder_id",),
            ),
            "move_file": VendorOperation(
                "move_file", "Move File", "PATCH", "/drive/items/{file_id}", ("file_id",),
                description="Move a file; the body accepts parentReference and name.",
            ),
            "rename_file": VendorOperation(
                "rename_file", "Rename File", "PATCH", "/drive/items/{file_id}", ("file_id",),
                description="Rename a file; the body accepts name.",
            ),
            "search_files": VendorOperation(
                "search_files", "Search Files", "GET",
                "/drive/root/search(q='{query}')", ("query",),
            ),
            "share_file": VendorOperation(
                "share_file", "Share File", "POST",
                "/drive/items/{file_id}/createLink", ("file_id",),
                retryable=False, idempotency="non_idempotent",
                description="Create a sharing link; the body accepts type and scope.",
            ),
            "share_folder": VendorOperation(
                "share_folder", "Share Folder", "POST",
                "/drive/items/{folder_id}/createLink", ("folder_id",),
                retryable=False, idempotency="non_idempotent",
                description="Create a sharing link; the body accepts type and scope.",
            ),
        },
    ),
    "microsoft_outlook": VendorSpec(
        key="microsoft_outlook",
        display_name="Microsoft Outlook",
        description="Microsoft Outlook mail, calendars, contacts, and folders through Microsoft Graph.",
        category="communication",
        base_url=f"{GRAPH_V1}/me",
        auth_kind="bearer",
        credential_fields=("access_token",),
        operations={
            "add_attachment": VendorOperation(
                "add_attachment", "Add Attachment", "POST",
                "/messages/{message_id}/attachments", ("message_id",),
                retryable=False, idempotency="non_idempotent",
                description="Add an attachment; the body accepts @odata.type, name, and contentBytes.",
            ),
            "create_contact": VendorOperation(
                "create_contact", "Create Contact", "POST", "/contacts", (),
                retryable=False, idempotency="non_idempotent",
            ),
            "create_draft": VendorOperation(
                "create_draft", "Create Draft", "POST", "/messages", (),
                retryable=False, idempotency="non_idempotent",
            ),
            "create_event": VendorOperation(
                "create_event", "Create Event", "POST",
                "/calendars/{calendar_id}/events", ("calendar_id",),
                retryable=False, idempotency="non_idempotent",
                description="Create an event; the body is the Graph event payload.",
            ),
            "create_reply": VendorOperation(
                "create_reply", "Create Reply Draft", "POST",
                "/messages/{message_id}/createReply", ("message_id",),
                retryable=False, idempotency="non_idempotent",
                description="Create a reply draft; the body accepts comment.",
            ),
            "create_reply_all": VendorOperation(
                "create_reply_all", "Create Reply-All Draft", "POST",
                "/messages/{message_id}/createReplyAll", ("message_id",),
                retryable=False, idempotency="non_idempotent",
                description="Create a reply-all draft; the body accepts comment.",
            ),
            "delete_contact": VendorOperation(
                "delete_contact", "Delete Contact", "DELETE", "/contacts/{contact_id}", ("contact_id",),
            ),
            "delete_event": VendorOperation(
                "delete_event", "Delete Event", "DELETE",
                "/calendar/events/{event_id}", ("event_id",),
            ),
            "delete_message": VendorOperation(
                "delete_message", "Delete Message", "DELETE", "/messages/{message_id}", ("message_id",),
            ),
            "get_attachment": VendorOperation(
                "get_attachment", "Get Attachment", "GET",
                "/messages/{message_id}/attachments/{attachment_id}", ("message_id", "attachment_id"),
            ),
            "get_contact": VendorOperation(
                "get_contact", "Get Contact", "GET", "/contacts/{contact_id}", ("contact_id",),
            ),
            "get_event": VendorOperation(
                "get_event", "Get Event", "GET", "/calendar/events/{event_id}", ("event_id",),
            ),
            "get_message": VendorOperation(
                "get_message", "Get Message", "GET", "/messages/{message_id}", ("message_id",),
            ),
            "list_attachments": VendorOperation(
                "list_attachments", "List Attachments", "GET",
                "/messages/{message_id}/attachments", ("message_id",),
            ),
            "list_calendars": VendorOperation(
                "list_calendars", "List Calendars", "GET", "/calendars",
            ),
            "list_contacts": VendorOperation(
                "list_contacts", "List Contacts", "GET", "/contacts",
                description="List contacts; pass $filter, $select, or $top as query params.",
            ),
            "list_events": VendorOperation(
                "list_events", "List Events", "GET", "/calendars/{calendar_id}/events", ("calendar_id",),
                description="List events; pass $filter, $select, or $top as query params.",
            ),
            "list_folder_messages": VendorOperation(
                "list_folder_messages", "List Folder Messages", "GET",
                "/mailFolders/{folder_id}/messages", ("folder_id",),
                description="List messages in a mail folder; pass $filter or $top as query params.",
            ),
            "list_mail_folders": VendorOperation(
                "list_mail_folders", "List Mail Folders", "GET", "/mailFolders",
            ),
            "list_messages": VendorOperation(
                "list_messages", "List Messages", "GET", "/messages",
                description="List messages; pass $filter, $search, or $top as query params.",
            ),
            "move_message": VendorOperation(
                "move_message", "Move Message", "POST", "/messages/{message_id}/move", ("message_id",),
                retryable=False, idempotency="non_idempotent",
                description="Move a message; the body accepts destinationId.",
            ),
            "send_message": VendorOperation(
                "send_message", "Send Message", "POST", "/sendMail", (),
                retryable=False, idempotency="non_idempotent",
                description="Send a message; the body accepts message and saveToSentItems.",
            ),
            "update_contact": VendorOperation(
                "update_contact", "Update Contact", "PATCH", "/contacts/{contact_id}", ("contact_id",),
            ),
            "update_event": VendorOperation(
                "update_event", "Update Event", "PATCH", "/calendar/events/{event_id}", ("event_id",),
            ),
            "update_message": VendorOperation(
                "update_message", "Update Message", "PATCH", "/messages/{message_id}", ("message_id",),
            ),
        },
    ),
    "microsoft_sharepoint": VendorSpec(
        key="microsoft_sharepoint",
        display_name="Microsoft SharePoint",
        description="Microsoft SharePoint lists, list items, and document-library files through Microsoft Graph.",
        category="productivity",
        base_url=GRAPH_V1,
        auth_kind="bearer",
        credential_fields=("access_token",),
        operations={
            "create_item": VendorOperation(
                "create_item", "Create Item", "POST",
                "/sites/{site_id}/lists/{list_id}/items", ("site_id", "list_id"),
                retryable=False, idempotency="non_idempotent",
                description="Create a list item; the body accepts fields.",
            ),
            "delete_item": VendorOperation(
                "delete_item", "Delete Item", "DELETE",
                "/sites/{site_id}/lists/{list_id}/items/{item_id}", ("site_id", "list_id", "item_id"),
            ),
            "get_item": VendorOperation(
                "get_item", "Get Item", "GET",
                "/sites/{site_id}/lists/{list_id}/items/{item_id}", ("site_id", "list_id", "item_id"),
            ),
            "get_list": VendorOperation(
                "get_list", "Get List", "GET",
                "/sites/{site_id}/lists/{list_id}", ("site_id", "list_id"),
            ),
            "list_items": VendorOperation(
                "list_items", "List Items", "GET",
                "/sites/{site_id}/lists/{list_id}/items", ("site_id", "list_id"),
                description="List items; pass $expand=fields, $filter, or $top as query params.",
            ),
            "list_lists": VendorOperation(
                "list_lists", "List Lists", "GET", "/sites/{site_id}/lists", ("site_id",),
            ),
            "update_file": VendorOperation(
                "update_file", "Update File Metadata", "PATCH",
                "/sites/{site_id}/drive/items/{file_id}", ("site_id", "file_id"),
                description="Update file metadata; the body accepts name.",
            ),
            "update_item": VendorOperation(
                "update_item", "Update Item", "PATCH",
                "/sites/{site_id}/lists/{list_id}/items/{item_id}/fields",
                ("site_id", "list_id", "item_id"),
                description="Update item fields; the body is the SharePoint fields payload.",
            ),
        },
    ),
}


# Keys intentionally left out of build_batch12_connectors(). Keeping the reasons
# next to the spec table makes each gap explicit instead of publishing a
# connector whose operations cannot authenticate or have no REST host at all.
UNSUPPORTED_BATCH12_KEYS: dict[str, str] = {
    "microsoft_sql": (
        "The Microsoft SQL node connects directly to a SQL Server database over "
        "TDS/TCP using the mssql driver (host, port, database, and user/password or "
        "domain credentials). It has no REST API, no fixed HTTP host, and no "
        "request/response JSON contract, so VendorRESTConnector cannot execute its "
        "queries. Use the dedicated native Microsoft SQL Server connector instead."
    ),
}


def _build_definition(spec: VendorSpec) -> ConnectorDefinitionV1:
    operations = {
        key: ConnectorOperationV1(
            connector_key=spec.key,
            connector_version="1.0.0",
            operation_key=key,
            operation_version="1.0.0",
            display_name=op.display_name,
            description=op.description or f"{op.display_name} for {spec.display_name}.",
            input_schema={
                "type": "object",
                "properties": {
                    "params": {"type": "object"},
                    "body": {"type": "object"},
                },
                "required": list(op.requires),
            },
            output_schema={"type": "object"},
            credential_require=spec.key,
            retryable=op.retryable,
            idempotency=op.idempotency,
            node_types=[spec.key],
        )
        for key, op in spec.operations.items()
    }
    credential_properties: dict[str, Any] = {
        field: {"type": "string", "title": field.replace("_", " ").title()}
        for field in spec.credential_fields
    }
    return ConnectorDefinitionV1(
        connector_key=spec.key,
        display_name=spec.display_name,
        description=spec.description,
        category=spec.category,
        connector_version="1.0.0",
        lifecycle_status=ConnectorLifecycle.BETA.value,
        operations=operations,
        triggers={},
        credential_types={
            spec.key: CredentialTypeV1(
                type_key=spec.key,
                display_name=f"{spec.display_name} Credentials",
                description=f"Credentials for {spec.display_name}.",
                secret_fields=list(spec.credential_fields),
                validation_schema={"type": "object", "properties": credential_properties},
                encryption_required=True,
            )
        },
        metadata={
            "implementation": "native",
            "batch": "catalog_conversion_12",
        },
    )


def build_batch12_connectors() -> list[tuple[VendorRESTConnector, ConnectorDefinitionV1]]:
    """Build the batch 12 connector instances and their definitions."""
    return [
        (VendorRESTConnector(spec), _build_definition(spec))
        for spec in VENDOR_SPECS.values()
    ]
