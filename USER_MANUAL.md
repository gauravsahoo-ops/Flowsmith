# Flowsmith User Manual

Welcome to **Flowsmith**! This guide is designed to help you quickly understand and master the platform in just a few minutes—whether you are automating simple notifications or orchestrating enterprise data pipelines.

---

## Table of Contents

1. [30-Second Overview](#1-30-second-overview)
2. [5-Minute Quick Start](#2-5-minute-quick-start)
3. [Core Concepts](#3-core-concepts)
4. [Connecting Your Accounts (OAuth & Credentials)](#4-connecting-your-accounts-oauth--credentials)
5. [Using Variables & Expressions](#5-using-variables--expressions)
6. [Logic, Routing & Error Handling](#6-logic-routing--error-handling)
7. [Testing, Debugging & Monitoring](#7-testing-debugging--monitoring)
8. [Data Tables & Approvals](#8-data-tables--approvals)
9. [Keyboard Shortcuts & Pro Tips](#9-keyboard-shortcuts--pro-tips)
10. [Troubleshooting & FAQ](#10-troubleshooting--faq)

---

## 1. 30-Second Overview

Flowsmith lets you connect your apps and automate processes using a visual canvas:

```
[ Trigger Node ]  ──────►  [ Logic / Filter ]  ──────►  [ Action / CRM ]
(e.g. Inbound Webhook)     (e.g. If status == 'new')    (e.g. Salesforce Lead)
```

- **Triggers**: Events that kick off your workflow (e.g. Schedule cron, Webhook, Salesforce update).
- **Nodes**: Individual steps that fetch data, transform fields, execute code, or call external APIs.
- **Connections (Edges)**: Wires connecting outputs of one node to inputs of downstream nodes.
- **Data Flow**: Data flows from left to right as clean JSON items.

---

## 2. 5-Minute Quick Start

### Step 1: Create a Workflow
1. Log in to Flowsmith (`http://localhost:5173`).
2. In the left navigation, click **Workflows** (`⚡`).
3. Click **"＋ Create workflow"** (or click **"From AI ✨"** and type what you want in plain English).

### Step 2: Add Nodes
1. Open the node drawer on the left (or press `Ctrl+K` for the Command Palette).
2. Drag a **Webhook** trigger onto the canvas.
3. Drag an **HTTP Request** or **Salesforce** action node next to it.

### Step 3: Wire Them Together
- Click and drag from the right handle (circle) of the Webhook node to the left handle of your action node.

### Step 4: Configure & Test
1. Double-click the action node to open the **Node Editor**.
2. Set your parameters (e.g. select your connected credential, specify endpoint or object).
3. Click **"▶ Execute Step"** to test this node with real or sample data.
4. Click **"✕"** to close the editor.

### Step 5: Save & Activate
1. Click **"Save"** (`Ctrl+S`) in the top bar.
2. Toggle the switch in the top bar from **"Inactive"** to **"Active"**.
3. **Done!** Your workflow is live and listening for events.

---

## 3. Core Concepts

### Node Color Coding
Nodes on the canvas are visually color-coded by category:
- 🟡 **Amber**: **Triggers** (Webhook, Schedule, Salesforce Trigger, Email Trigger).
- 🔵 **Blue**: **Connectors & External APIs** (Salesforce, HTTP Request, Slack, Google Sheets).
- 🟣 **Indigo / Purple**: **Control Flow & Logic** (IF Condition, Switch, Merge, Split In Batches).
- 🟢 **Teal**: **Data Transforms** (Set Variables, Filter, Code, Token Manager).
- 🔷 **Cyan**: **AI & Agents** (AI Agent, RAG Knowledge Retriever, Text Classifier).

### The 3-Panel Node Editor
Double-clicking any node opens the centered editor:
1. **Left Panel (Inputs)**: Shows real data received from all upstream parent nodes. Click any field to automatically copy its expression!
2. **Center Panel (Parameters)**: Configure the node's settings, endpoints, credentials, and mapping rules.
3. **Right Panel (Output)**: View the exact JSON emitted by this node during test executions.

---

## 4. Connecting Your Accounts (OAuth & Credentials)

Flowsmith features a **1-click frictionless OAuth connection experience**:

### Connecting an App (Salesforce, Google, HubSpot, etc.)
1. Click **Credentials** (`🔑`) in the left navigation.
2. Select your provider under **New Credential** (e.g. *Salesforce*).
3. Click **`[ Connect Salesforce ]`**.
4. A secure login popup opens. Log in, grant permissions, and approve.
5. The popup self-closes, and your account appears in the **Connected Credentials** table.

### Dynamic Session Status
- 🟢 **`● Connected`**: Active and valid. Workflows can use this credential freely.
- 🟡 **`● Session Expired`**: Session or token needs renewal.

### 1-Click Reconnect
If a third-party token expires or is revoked:
- Simply click **`🔄 Reconnect`** on the credential row.
- Flowsmith automatically renews the session in the background without asking for login credentials.
- If interactive re-approval is required, the popup smoothly navigates directly to the login prompt.

> 🔒 **Security Guarantee**: All passwords, API keys, and OAuth tokens are **100% encrypted at rest** in PostgreSQL using AES-256 Fernet ciphertext. No tokens are ever hardcoded or exposed in `.env` files.

---

## 5. Using Variables & Expressions

You can reference data dynamically between nodes using double-curly braces:

| Expression | Description | Example |
|---|---|---|
| `{{ $json.fieldName }}` | Value from the immediate upstream node | `{{ $json.email }}` |
| `{{ $('Node Name').item.json.field }}` | Value from a specific named upstream node | `{{ $('Webhook').item.json.user.id }}` |
| `{{ $env.VAR_NAME }}` | Workspace environment variable | `{{ $env.API_BASE_URL }}` |
| `{{ $cred.apiKey }}` | Stored credential field | `{{ $cred.secret_token }}` |

### Workspace Environment Variables
1. Go to **Variables** (`🌍`) in the left navigation (`/variables`).
2. Add variables like `BASE_URL` or `DEFAULT_REGION`.
3. Check **"Secret"** for sensitive tokens—they will be encrypted in the database and masked in the UI.

---

## 6. Logic, Routing & Error Handling

### Branching (IF & Switch)
- **IF Condition**: Evaluates boolean conditions (`equals`, `contains`, `greater than`, `matches regex`). Sends items out of either the `true` (top) or `false` (bottom) output handle.
- **Switch**: Multi-way routing (up to 4+ rules) based on category, status, or customer tier.

### Batch Processing
- **Split In Batches**: Splits large lists (e.g. 5,000 records) into manageable batches (e.g. 50 at a time) to prevent API rate-limit errors.

### Universal Token Manager
- Use the **Token Manager** node when working with APIs requiring dynamic bearer tokens.
- **Dual Outputs**:
  - `🟢 valid`: Emits existing valid token directly downstream (skips login API).
  - `🟠 login`: Routes to your login API only when the token is missing or expired.

### Automated Error Alerts
- Every workflow has an optional **"Error Workflow"** setting.
- If any node fails in production, the dedicated **Error Trigger** receives failure context (`error_message`, `failed_node`, `execution_id`) to automatically ping Slack, email, or PagerDuty.

---

## 7. Testing, Debugging & Monitoring

### Manual Testing
- Click **"Run"** (`▶`) in the top bar to run the canvas with test inputs.
- Completed nodes show a green checkmark (`✔`), running nodes pulse (`⏳`), and errors show a red highlight (`✖`).

### Debugger Drawer
- Click **"Console"** (`📋`) in the top bar to slide out the execution inspector.
- View step execution time (e.g. `18ms`), per-step input payloads, and output results.
- Click **"Retry"** to replay a failed execution from the exact step that failed.

### Version History & Rollback
- Every time you save (`Ctrl+S`), Flowsmith creates an immutable version snapshot.
- Click **"Versions"** in the editor header to view past versions and restore any previous release with one click.

---

## 8. Data Tables & Approvals

### Relational Data Tables (`📊 /data-tables`)
- Built-in, persistent spreadsheet storage inside Flowsmith.
- Create custom tables (e.g. `Prospects`, `Inventory`, `SyncLog`) with typed columns (`string`, `number`, `boolean`, `date`, `json`).
- Use the **Data Table** node in workflows to insert, update, or query rows without an external SQL database.

### Human-in-the-Loop Approvals (`🛡️ /approvals`)
- Add the **Human Approval** node before sensitive operations (e.g. refunds over $500, bulk deletes).
- Workflow execution pauses automatically.
- Reviewers visit the **Approvals** tab, inspect the payload, and click **Approve** or **Reject** to resume the flow.

---

## 9. Keyboard Shortcuts & Pro Tips

| Shortcut | Action |
|---|---|
| `Ctrl + K` / `Cmd + K` | Open Command Palette & Quick Node Inserter |
| `Ctrl + S` / `Cmd + S` | Save workflow snapshot |
| `Ctrl + D` / `Cmd + D` | Duplicate selected node |
| `Delete` / `Backspace` | Delete selected node or connection |
| `Space + Drag` | Pan around the canvas |
| `Ctrl + MouseWheel` | Zoom in / Zoom out |

### 💡 Pro Tips:
1. **Pin Data for Fast Testing**: Click the 📌 icon on any node to pin its output. Downstream nodes can test against this mock data without making real external API calls!
2. **Click to Copy Expressions**: In the Node Editor's left panel, click on any JSON property to immediately copy its exact expression path (e.g. `{{ $json.customer.email }}`).
3. **Auto-Layout**: If your canvas gets messy, click **Auto-Layout** in the bottom left canvas toolbar to automatically align all nodes cleanly.

---

## 10. Troubleshooting & FAQ

### Q: Why didn't my Webhook or Schedule trigger run?
**A:** Check the toggle switch in the top bar. Workflows must be set to **"Active"** for background triggers to run. Inactive workflows only execute when you manually click "Run".

### Q: My Salesforce connection says "Session Expired"—what do I do?
**A:** Go to `/credentials` and click **`🔄 Reconnect`**. Flowsmith will instantly renew the session in the background or prompt you to re-authorize with one click.

### Q: Can I run custom Python or JavaScript?
**A:** Yes! Add a **Code** node. It provides a full Monaco (VS Code) editor supporting both Python and JavaScript with sandboxed execution.

### Q: How do I export or backup my workflows?
**A:** In any workflow, click the **"..."** menu in the top bar and select **Export JSON**. You can import this file into any other Flowsmith instance.

---

*Need help or want to report an issue? Check your organization's support channels or visit the [GitHub Repository](https://github.com/gauravsahoo-ops/Flowsmith).*
