# Flowsmith Master User Manual (Complete A to Z Guide)

> **Who is this guide for?**  
> **Everyone!** Whether you are a **business owner, sales rep, operations manager, IT administrator, or software engineer**, this master manual covers every single feature of Flowsmith from **A to Z** in simple, plain English—with visual diagrams, click-by-click instructions, and real-world examples. **No coding experience is required.**

---

## Master Table of Contents

1. [Flowsmith in 60 Seconds (The Big Picture)](#1-flowsmith-in-60-seconds-the-big-picture)
2. [Everyday Real-World Examples](#2-everyday-real-world-examples)
3. [The Flowsmith Interface (Complete Screen Tour)](#3-the-flowsmith-interface-complete-screen-tour)
4. [The 4 Basic Building Blocks (The "Lego" Pieces)](#4-the-4-basic-building-blocks-the-lego-pieces)
5. [5-Minute Quick Start: Building Your First Automation](#5-5-minute-quick-start-building-your-first-automation)
6. [Using AI to Build Workflows For You ("From AI ✨")](#6-using-ai-to-build-workflows-for-you-from-ai-)
7. [The Complete Card Catalog (Every Node Explained)](#7-the-complete-card-catalog-every-node-explained)
   - [7.1. Triggers (Starting Events)](#71-triggers-starting-events)
   - [7.2. App Connectors (Salesforce, Google, Slack, Stripe, etc.)](#72-app-connectors-salesforce-google-slack-stripe-etc)
   - [7.3. Logic & Routing (Decisions, Splits & Merges)](#73-logic--routing-decisions-splits--merges)
   - [7.4. Data Transforms (Calculations, Filtering, Code, Token Manager)](#74-data-transforms-calculations-filtering-code-token-manager)
   - [7.5. AI & Knowledge (Autonomous Agents, Summarizers, RAG)](#75-ai--knowledge-autonomous-agents-summarizers-rag)
8. [Connecting Your Accounts (Credentials & 1-Click OAuth)](#8-connecting-your-accounts-credentials--1-click-oauth)
   - [8.1. How to Connect an Account (Salesforce, Google, Slack)](#81-how-to-connect-an-account-salesforce-google-slack)
   - [8.2. Dynamic Session Status (Connected vs. Session Expired)](#82-dynamic-session-status-connected-vs-session-expired)
   - [8.3. 1-Click Reconnect (Instant Session Renewal)](#83-1-click-reconnect-instant-session-renewal)
   - [8.4. Enterprise Security & Encryption Guarantee](#84-enterprise-security--encryption-guarantee)
9. [Passing Information Between Steps (The "Mail Merge" Engine)](#9-passing-information-between-steps-the-mail-merge-engine)
10. [Workspace Environment Variables & Encrypted Secrets (`/variables`)](#10-workspace-environment-variables--encrypted-secrets-variables)
11. [Built-In Relational Data Tables (`/data-tables`)](#11-built-in-relational-data-tables-data-tables)
12. [Human Approvals & Review Gates (`/approvals`)](#12-human-approvals--review-gates-approvals)
13. [AI & RAG Knowledge Base (`/knowledge`)](#13-ai--rag-knowledge-base-knowledge)
14. [Templates, Sharing, Importing & Exporting (`/templates`)](#14-templates-sharing-importing--exporting-templates)
15. [Testing, Debugging & Monitoring](#15-testing-debugging--monitoring)
    - [15.1. Testing Single Steps vs. Full Canvas](#151-testing-single-steps-vs-full-canvas)
    - [15.2. Data Pinning (Mocking Data for Risk-Free Testing)](#152-data-pinning-mocking-data-for-risk-free-testing)
    - [15.3. Console Drawer & Step Execution Logs](#153-console-drawer--step-execution-logs)
    - [15.4. Version History & 1-Click Rollback](#154-version-history--1-click-rollback)
    - [15.5. System Health, Telemetry & Disaster Recovery](#155-system-health-telemetry--disaster-recovery)
16. [Custom Connectors & OpenAPI / cURL Importer (`/connectors`)](#16-custom-connectors--openapi--curl-importer-connectors)
17. [White-Labeling & Brand Change (Make It Your Own Platform)](#17-white-labeling--brand-change-make-it-your-own-platform)
18. [Keyboard Shortcuts & Canvas Navigation](#18-keyboard-shortcuts--canvas-navigation)
19. [A to Z Complete Glossary (Every Tech Term Defined)](#19-a-to-z-complete-glossary-every-tech-term-defined)
20. [Frequently Asked Questions & Troubleshooting (FAQ)](#20-frequently-asked-questions--troubleshooting-faq)

---

## 1. Flowsmith in 60 Seconds (The Big Picture)

Think of Flowsmith like a **super-smart digital conveyor belt** connecting all of your company's software. 

Whenever something happens in one app (like a customer submitting a form on your website), Flowsmith automatically picks up that data, checks your business rules, and performs actions across your other apps (like saving the record in Salesforce, notifying your team in Slack, and emailing the customer).

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                HOW FLOWSMITH WORKS                                     │
├─────────────────────────┬──────────────────────────────┬───────────────────────────────┤
│  1. EVENT (Trigger)     │  2. DECISION (Logic)         │  3. ACTION (Integrations)     │
│  "A customer fills out  │  "Is their budget over       │  "Add to Salesforce, notify   │
│   a contact form"       │   $5,000?"                   │   Slack, send welcome email"  │
│                         │                              │                               │
│  [ 🚪 Webhook Form ] ──►│  [ 🔍 IF Budget > 5000 ] ───►│  [ 🔵 Salesforce Lead ]       │
│                         │             │ (No)           │  [ 💬 Slack Channel Alert ]   │
│                         │             ▼                │  [ ✉️ Welcome Email ]         │
│                         │  [ ✉️ Send Brochure ]        │                               │
└─────────────────────────┴──────────────────────────────┴───────────────────────────────┘
```

### Why Companies Use Flowsmith:
- **No More Manual Data Entry**: Stop copying and pasting customer emails, order numbers, and ticket notes between tools.
- **Visual & Intuitive**: Build everything by dragging cards on a canvas and connecting them with wires—just like drawing a flowchart.
- **Zero Coding Required**: Over 95% of automations can be built purely with point-and-click settings.
- **100% Private & Secure**: Self-hosted on your own infrastructure with zero per-run fees and military-grade encryption at rest.

---

## 2. Everyday Real-World Examples

Here are 3 detailed examples of how organizations use Flowsmith every day:

### Example 1: Sales Lead Capture & Instant Follow-Up
```
[ Webhook / Form ] ──► [ Filter: Business Email ] ──► [ Salesforce: Create Lead ] ──► [ Slack Alert ] ──► [ Welcome Email ]
```
- **Trigger**: A website visitor submits a demo request.
- **Step 1 (Filter)**: Checks that the email is not a disposable address.
- **Step 2 (Salesforce)**: Instantly creates a Lead with the prospect's company name and phone.
- **Step 3 (Slack)**: Posts a message in `#sales-leads`: *"🔥 New Lead from Acme Corp! Value: $25,000"*.
- **Step 4 (Email)**: Sends a calendar invite to the prospect.

### Example 2: Weekly Automated KPI Report
```
[ Schedule: Mon 9am ] ──► [ Query Data Table ] ──► [ Format HTML Summary ] ──► [ Email to Leadership ]
```
- **Trigger**: Every Monday morning at 9:00 AM sharp.
- **Step 1 (Query)**: Pulls closed-won sales figures and support ticket metrics from the past 7 days.
- **Step 2 (Format)**: Formats the numbers into a clean summary table.
- **Step 3 (Email)**: Automatically emails the weekly dashboard report to executives and department heads.

### Example 3: Customer Refund with Manager Approval Gate
```
[ Refund Request ] ──► [ IF Amount > $200 ] ──► [ 🛡️ Human Approval Gate ] ──► [ Stripe Refund ] ──► [ Receipt Email ]
```
- **Trigger**: Customer service receives a refund request.
- **Step 1 (Decision)**: If the refund is under $200, it processes immediately. If it is over $200, it pauses.
- **Step 2 (Approval)**: The workflow safely freezes. An alert appears on the manager's **Approvals** screen.
- **Step 3 (Review)**: The manager inspects the customer's history and clicks **"Approve"**.
- **Step 4 (Fulfillment)**: Flowsmith automatically wakes up, issues the refund in Stripe, updates the accounting records, and sends a confirmation email.

---

## 3. The Flowsmith Interface (Complete Screen Tour)

When you log in to Flowsmith, you are greeted by an uncluttered, modern dashboard:

```
┌─────────────────┬────────────────────────────────────────────────────────────────────────┐
│  Flowsmith      │  [Workflow Name]    [▶ Run]   [● Active]   [📋 Console]   [⚙ Settings]  │
├─────────────────┼────────────────────────────────────────────────────────────────────────┤
│ ⚡ Workflows     │                                                                        │
│ 🔑 Credentials   │                         VISUAL CANVAS                                  │
│ 📊 Data Tables   │                  (Drag & Drop Whiteboard Area)                         │
│ 🌍 Variables     │                                                                        │
│ 🛡️ Approvals     │   [ Trigger ] ────────► [ Logic / IF ] ────────► [ Action App ]         │
│ 📚 Knowledge     │                                                                        │
│ 🎨 Templates     │                                                                        │
└─────────────────┴────────────────────────────────────────────────────────────────────────┘
```

### 1. Left Navigation Sidebar
- **Workflows (`⚡`)**: The home of all your automation pipelines. Create, edit, clone, or organize them.
- **Credentials (`🔑`)**: Connect third-party tools (Salesforce, Google, Slack, HubSpot) with 1 click.
- **Data Tables (`📊`)**: In-app spreadsheet database to store, query, and edit records without external SQL databases.
- **Variables (`🌍`)**: Manage shared workspace variables and encrypted secrets (`{{ $env.KEY }}`).
- **Approvals (`🛡️`)**: The management review portal for workflows paused awaiting human authorization.
- **Knowledge (`📚`)**: Upload PDF, Markdown, and text documents for AI vector search (RAG).
- **Templates (`🎨`)**: Pre-built starter recipes ready to clone into your workspace with 1 click.
- **Settings (`⚙️`)**: Workspace configuration, user management, and white-label branding.
- **User Profile Pill**: Positioned at the bottom of the sidebar displaying your authenticated name, email address, initials avatar, and a live green status beacon (`● Online`).

### 2. Top Bar Controls
- **Workflow Name**: Click to rename your workflow (e.g. *"Salesforce Lead Sync"*).
- **Command Palette (`Ctrl + K` / `⌘K`)**: Instant search button to quickly summon any card or run quick actions without leaving the keyboard.
- **Run (`▶`)**: Tests your workflow manually right now using test inputs.
- **Active / Inactive Switch**: When flipped to **Active** (green), your workflow is live and listening 24/7. When **Inactive**, it only runs when you click "Run".
- **Console (`📋`)**: Opens the slide-out drawer showing real-time execution logs, per-step timing, and data payloads.
- **Versions (`🕒`)**: Every save creates an immutable backup. Click here to rollback to any past version.

### 3. Visual Canvas & Floating Studio Dock
- **Interactive Whiteboard**: Click and drag cards, connect them with wires, pan around freely with spacebar drag, or pinch-to-zoom on laptops and tablets.
- **Floating Studio Dock (Bottom-Left Toolbar)**:
  - **Undo / Redo (`↶ / ↷`)**: Revert or replay recent canvas modifications.
  - **Auto-Layout (`⚡`)**: Automatically repositions all cards into a clean, readable diagram.
  - **Add Sticky Note (`📝`)**: Drop colorful annotation notes onto the canvas to explain logic to teammates.
  - **Frame / Group (`🖼️`)**: Visually boundary-box related steps together.
  - **Fit View (`⛶`) & MiniMap (`🗺️`)**: Instantly re-center the canvas or toggle the bottom-right bird's-eye map.
  - **Zoom Controls (`+ / -`)**: Precision zoom in or out.

### 4. Clamped 3-Panel & Responsive 1-Panel Node Editor
- Double-clicking any card opens the centered **Node Editor Modal**:
  - **Left Panel (Inputs)**: Inspect upstream ancestor data, preview incoming JSON, and copy expression tags with 1 click.
  - **Center Panel (Parameters)**: Configure the node's settings, credentials, field mappings, and options.
  - **Right Panel (Output)**: View output payloads generated from test executions.
- **Adaptive Screen Responsiveness**: On laptops, tablets, or split-screen windows (below `1150px`), the editor automatically switches into streamlined single-panel tabs (`Input`, `Parameters`, `Output`), guaranteeing zero clipping and persistent action buttons (`✨ AI Auto-Repair`, `▶ Execute Step`, and `✕ Close`).

---

## 4. The 4 Basic Building Blocks (The "Lego" Pieces)

Every automation in Flowsmith is built using just 4 simple types of cards:

```
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│  🟡 TRIGGER      │    │  🔵 ACTION / APP │    │  🟣 LOGIC        │    │  🔷 AI ASSISTANT │
│  "When event     │    │  "Do something   │    │  "Make decision  │    │  "Think, analyze │
│   occurs"        │    │   in an app"     │    │   or branch"     │    │   or summarize"  │
│  (Doorbell)      │    │  (Worker)        │    │  (Traffic Light) │    │  (Smart Analyst) │
└──────────────────┘    └──────────────────┘    └──────────────────┘    └──────────────────┘
```

| Category | Badge Color | What It Does | Real-World Examples |
|---|---|---|---|
| **Trigger** | 🟡 **Amber** | **Starts the workflow.** Waits for an event or a time schedule. | Webhook, Schedule Timer, Salesforce Record Created, Incoming Email. |
| **Connector / Action** | 🔵 **Blue** | **Does work in an external app.** | Salesforce, Slack, Gmail, Google Sheets, Stripe, Jira, HubSpot. |
| **Logic & Filter** | 🟣 **Purple** | **Controls the path of data.** Makes choices or splits data. | IF Condition, Switch, Merge, Split In Batches, Wait/Delay. |
| **AI Assistant** | 🔷 **Cyan** | **Reasons and analyzes.** Reads text, extracts details, or searches docs. | AI Agent, RAG Knowledge Retriever, Sentiment Classifier, Text Summarizer. |

---

## 5. 5-Minute Quick Start: Building Your First Automation

Let's build a real, working automation in under 5 minutes:

```
[ Webhook / Form ]  ──────────────────►  [ Salesforce / Action ]
  (Trigger card)        (Drag line)           (Action card)
```

### Step 1: Create a Blank Workflow
1. Click **Workflows** (`⚡`) in the left navigation.
2. Click the blue button: **"＋ Create workflow"**.
3. You now have a fresh, blank canvas ready for your cards.

### Step 2: Add Your Trigger
1. Click the **"＋ Add Node"** button on the left (or press `Ctrl+K`).
2. Search for **Webhook** and drag it onto the canvas.
3. This creates a secure, unique URL where external apps or website forms can send data.

### Step 3: Add an Action Card
1. Open the card menu again (`Ctrl+K`).
2. Search for **Salesforce** (or **Slack**, or **Email**).
3. Drag the card onto the canvas to the right of your Webhook card.

### Step 4: Wire the Cards Together
1. Find the small circular dot (**handle**) on the right side of the Webhook card.
2. Click and hold that dot, then drag a line to the dot on the left side of the Salesforce card.
3. Release the mouse. You have connected the two steps!

### Step 5: Configure Your Action Card
1. Double-click your Salesforce card. The **3-Panel Node Editor** opens:
   - **Left Panel (Inputs)**: Displays all data received from previous cards.
   - **Center Panel (Parameters)**: Select your connected Salesforce account and pick an action (e.g. *"Create Lead"*).
   - **Right Panel (Output)**: Shows the result when tested.
2. Click **"▶ Execute Step"** to test it with a sample run.
3. Click the **"✕"** button in the top right to close the editor.

### Step 6: Save and Turn It ON!
1. Press `Ctrl+S` (or click **"Save"** in the top bar).
2. Look at the switch in the top bar that says **"Inactive"**. Click it to switch to **"Active"** (it turns green).
3. **Congratulations!** Your automation is now live and working 24/7.

---

## 6. Using AI to Build Workflows For You ("From AI ✨")

If you don't want to drag cards manually, you can simply tell Flowsmith what you want in plain English:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              AI WORKFLOW GENERATOR                                     │
├────────────────────────────────────────────────────────────────────────────────────────┤
│  Prompt: [ When a customer submits a contact request, check if their budget is       ] │
│          [ over $10,000. If yes, add a Lead in Salesforce and notify Slack.          ] │
│          [ Otherwise, send our standard brochure email.                              ] │
│                                                                                        │
│                                              [ ✨ Generate Workflow ]                  │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

### How to Use the AI Builder:
1. On the **Workflows** page, click the button that says **"From AI ✨"**.
2. Type your requirement in normal, conversational English.
3. Click **"Generate Workflow"**.
4. In just 3 seconds, Flowsmith's AI will:
   - Pick the exact cards needed (Webhook, IF Condition, Salesforce, Slack, Email).
   - Place them on the canvas in the correct order.
   - Wire the connections and configure the branching rules.
5. You can inspect any card, make adjustments, and activate it immediately!

---

## 7. The Complete Card Catalog (Every Node Explained)

### 7.1. Triggers (Starting Events)
- **Webhook**: Gives you a unique web URL. External forms, Shopify stores, or Stripe webhooks can send data here instantly. Supports synchronous responses (`respond_to_webhook`).
- **Schedule**: An automated timer. Run your workflow every 15 minutes, every morning at 8:00 AM, or on specific calendar dates using a visual picker or standard Cron syntax (`0 9 * * 1` = Every Monday at 9 AM).
- **Salesforce Trigger**: Fires automatically whenever an Object (Lead, Contact, Opportunity, Case) is created or updated in Salesforce.
- **Email Trigger (IMAP)**: Listens to any corporate inbox (Gmail, Outlook, IMAP) and triggers when a new email arrives matching your sender or subject filters.
- **Error Trigger**: Listens for failures across your other workflows. If any workflow encounters an error, this card fires automatically to page your engineering team on PagerDuty or alert Slack.

### 7.2. App Connectors (Salesforce, Dynamics 365, Google, Slack, Stripe, etc.)
Flowsmith includes **45+ native connectors**:
- **Salesforce**: Search records with SOQL, Create, Update, Upsert, Get, and Delete records across standard or custom objects.
- **Microsoft Dynamics 365 (Dataverse)**: Query records with OData filters or FetchXML, Create, Update, Upsert, Get, and Delete Accounts, Contacts, Leads, Opportunities, Incidents (Cases), and custom tables with dual support for 1-Click OAuth2 and Azure Entra ID Service Principal (S2S).
- **Google Sheets**: Read rows, append new customer rows, update cells, or clear spreadsheets.
- **Google Docs**: Create new documents from templates or append text dynamically.
- **Gmail & Outlook**: Send rich HTML emails, attach documents, search inbox threads.
- **Slack & Microsoft Teams**: Post formatted messages, adaptive cards, and channel alerts.
- **HubSpot & Pipedrive**: Create and update CRM contacts, deals, and pipeline stages.
- **Stripe**: Manage customers, inspect invoices, verify charges, and issue refunds.
- **Jira, GitHub, GitLab, Bitbucket**: Create issues, manage pull requests, and comment on tickets.
- **Twilio & WhatsApp**: Send SMS alerts or Meta Cloud API WhatsApp template messages.
- **Airtable & Notion**: Query bases, insert records, and create workspace pages.
- **HTTP Request**: The universal connector! Connect to **any REST API on the internet** with full support for GET, POST, PUT, DELETE, headers, and authentication.

### 7.3. Logic & Routing (Decisions, Splits & Merges)
- **IF Condition**: Evaluates rules (`equals`, `contains`, `greater than`, `regex`). Sends data through either the **true** (top) or **false** (bottom) wire.
- **Switch**: Multi-way routing. Directs data down 4+ different paths based on category, department, or tier.
- **Merge**: Combines data arriving from two separate branches into a single unified stream.
- **Split In Batches**: Takes large lists (e.g. 5,000 records) and processes them in smaller batches (e.g. 50 at a time) to prevent API rate-limit errors.
- **Wait / Delay**: Pauses execution for a specific duration (e.g. "Wait 2 days before sending follow-up email").

### 7.4. Data Transforms (Calculations, Filtering, Code, Token Manager)
- **Set Variables**: Define or overwrite fields on your data items.
- **Filter**: Drop records that don't match specific criteria (e.g. only keep records where `status == 'active'`).
- **Code (JavaScript & Python)**: A built-in Monaco (VS Code) editor where you can write custom scripts for complex math, data scrubbing, or custom transformations.
- **Token Manager**: A smart card with dual handles (`🟢 valid` vs `🟠 login`) that manages access tokens, reuses valid sessions, and prevents redundant login calls.

### 7.5. AI & Knowledge (Autonomous Agents, Summarizers, RAG)
- **AI Agent**: An autonomous reasoning engine that can use external tools (search web, query database, run calculations) to complete tasks.
- **RAG Knowledge Retriever**: Queries your uploaded company documents and passes relevant excerpts to AI prompts.
- **Text Summarizer & Classifier**: Classifies incoming customer tickets (e.g. "Billing", "Bug", "Feature Request") or summarizes long email threads.

---

## 8. Connecting Your Accounts (Credentials & 1-Click OAuth)

Flowsmith features a **1-click frictionless OAuth connection experience**:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              CONNECTED CREDENTIALS TABLE                               │
├──────────────────────┬─────────────┬──────────────────┬────────────────────────────────┤
│ Name                 │ Type        │ Status           │ Actions                        │
├──────────────────────┼─────────────┼──────────────────┼────────────────────────────────┤
│ Salesforce (Sales)   │ salesforce  │ ● Connected      │ [ Test ]  [ Reconnect ] [ 🗑️ ] │
│ Google Workspace     │ google      │ ● Session Expired│ [ Test ]  [ Reconnect ] [ 🗑️ ] │
│ Slack (Alerts Bot)   │ slack       │ ● Connected      │ [ Test ]  [ Reconnect ] [ 🗑️ ] │
└──────────────────────┴─────────────┴──────────────────┴────────────────────────────────┤
```

### 8.1. How to Connect an Account (Salesforce, Google, Slack)
1. Click **Credentials** (`🔑`) in the left navigation.
2. Under **New Credential**, select the app you want to connect (e.g. **Salesforce**).
3. (Optional) Customize the connection settings:
   - **Custom Login URL**: Connect to a Salesforce Sandbox (`https://test.salesforce.com`) or custom My Domain.
   - **Custom Client ID & Secret**: Provide your own Connected App credentials or use the system defaults.
   - **Credential Name**: Give the account a friendly nickname (e.g., *"Salesforce EMEA Production"*).
4. Click the blue button: **`[ Connect Salesforce ]`**.
5. A secure popup opens. Simply log into your account and click **Allow / Approve**.
6. The popup self-closes, and your account appears in the **Connected Credentials** table!

#### Connecting Microsoft Dynamics 365 (Dataverse)
Microsoft Dynamics 365 supports two enterprise authentication modes:
- **Interactive OAuth2 (1-Click)**: Enter your Dynamics 365 Org URL (e.g. `https://myorg.crm.dynamics.com`) and click **Sign in with Microsoft 365**. Log into your corporate Microsoft account, grant permissions, and Flowsmith securely stores encrypted tokens with automatic background renewal.
- **Service Principal (Server-to-Server / Daemon)**: For headless enterprise automations with no human login required, switch to the **Service Principal (S2S)** tab. Provide your Azure Entra ID Application (Client) ID, Client Secret, Tenant ID, and Dynamics Org URL. Flowsmith validates connectivity via `/api/data/v9.2/WhoAmI` and caches tokens thread-safely with automated refresh.
- **Azure App Setup Guide**: The built-in Azure App Setup tab gives you the exact Redirect URI and API permissions (`Dynamics CRM -> user_impersonation`) needed in your Azure Portal.

### 8.2. Dynamic Session Status (Connected vs. Session Expired)
- 🟢 **`● Connected`**: Active and valid. Workflows can use this credential freely.
- 🟡 **`● Session Expired`**: The service requires a token renewal.

### 8.3. 1-Click Reconnect (Instant Session Renewal)
If a third-party token ever expires:
1. Click the **`🔄 Reconnect`** button on that row.
2. Flowsmith automatically renews the session in the background without asking for login credentials.
3. If interactive re-approval is required, the popup smoothly navigates directly to the login prompt. Click approve, and you're done!

### 8.4. Enterprise Security & Encryption Guarantee
- All passwords, API keys, OAuth tokens, and transient authorization states are **100% encrypted at rest** in PostgreSQL using **AES-256 Fernet** ciphertexts (`k0:...`).
- Credentials are never stored in plain text files, never touch `.env`, and cannot be read by anyone over the API.
- Transient OAuth PKCE state tokens are automatically encrypted and purged after authorization completes or expires.

---

## 9. Passing Information Between Steps (The "Mail Merge" Engine)

Flowsmith uses double curly braces (`{{ ... }}`) to pass information dynamically between cards—just like **Mail Merge** in Microsoft Word or email templates:

| What You Type | What Flowsmith Fills In Live |
|---|---|
| `{{ $json.name }}` | `"Acme Corp"` (Value from the immediate previous card) |
| `{{ $json.email }}` | `"contact@acme.com"` |
| `{{ $('Webhook').item.json.phone }}` | `"+1-555-0199"` (Value from a specific named card) |
| `{{ $env.SALES_EMAIL }}` | `"sales@yourcompany.com"` (Workspace variable) |

### 💡 Pro Tip: Never Type Expressions Manually!
1. Double-click any card to open the editor.
2. In the **Left Panel (Inputs)**, you will see all data from earlier steps.
3. **Just click on any field** (e.g. click on `email`). Flowsmith will automatically copy its exact expression tag!
4. Paste it right into your parameter field.

---

## 10. Workspace Environment Variables & Encrypted Secrets (`/variables`)

Use workspace variables for values you want to reuse across multiple workflows:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                           WORKSPACE ENVIRONMENT VARIABLES                              │
├─────────────────────┬───────────────────────────┬──────────┬───────────────────────────┤
│ Variable Name       │ Value                     │ Secret?  │ In Workflows              │
├─────────────────────┼───────────────────────────┼──────────┼───────────────────────────┤
│ API_BASE_URL        │ https://api.mycompany.com │ No       │ {{ $env.API_BASE_URL }}   │
│ STRIPE_SECRET_KEY   │ ••••••••••••••••••••••••• │ Yes 🔒   │ {{ $env.STRIPE_SECRET_KEY}}│
│ SUPPORT_EMAIL       │ support@mycompany.com     │ No       │ {{ $env.SUPPORT_EMAIL }}  │
└─────────────────────┴───────────────────────────┴──────────┴───────────────────────────┘
```

1. Click **Variables** (`🌍`) in the left navigation.
2. Click **"Add Variable"**.
3. Enter the key name (e.g. `SUPPORT_EMAIL`) and value (`support@mycompany.com`).
4. **Secret Variables**: Check the **"Secret"** box for sensitive passwords or tokens. Secrets are encrypted in the database and masked with asterisks (`••••••••`) in the interface.
5. In any workflow node, reference it as: `{{ $env.SUPPORT_EMAIL }}`.

---

## 11. Built-In Relational Data Tables (`/data-tables`)

Flowsmith has a built-in spreadsheet database so you can store, edit, and query records without spinning up an external database:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        DATA TABLE: "VIP_Prospects" (Spreadsheet View)                  │
├──────┬──────────────────────┬───────────────────────┬────────────┬─────────────────────┤
│ ID   │ Company Name         │ Contact Email         │ Deal Value │ Status              │
├──────┼──────────────────────┼───────────────────────┼────────────┼─────────────────────┤
│ 1    │ Acme Corporation     │ john@acme.com         │ $45,000    │ Active Lead         │
│ 2    │ Starlight Logistics  │ sarah@starlight.io    │ $12,500    │ Proposal Sent       │
│ 3    │ Apex Global          │ alex@apex.com         │ $85,000    │ Closed Won          │
└──────┴──────────────────────┴───────────────────────┴────────────┴─────────────────────┤
│ [＋ Add Row]  [ Filter ]  [ Sort ]  [ Export CSV ]                                     │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

1. Click **Data Tables** (`📊`) in the left navigation.
2. Click **"Create Table"** (e.g. `VIP_Prospects`, `Inventory`, `SupportTickets`).
3. Define your columns with strict types: `Text`, `Number`, `Boolean`, `Date`, or `JSON`.
4. Add or edit rows directly in the spreadsheet view, sort by columns, and search instantly.
5. **In Workflows**: Add the **Data Table** card to search records, insert rows, or update status automatically.

---

## 12. Human Approvals & Review Gates (`/approvals`)

For high-risk operations (e.g. refunds over $500, bulk customer deletions, production deployments):

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                         PENDING APPROVALS DASHBOARD                                    │
├──────────────┬────────────────────────────────┬──────────────┬─────────────────────────┤
│ Workflow     │ Requested Action               │ Initiator    │ Actions                 │
├──────────────┼────────────────────────────────┼──────────────┼─────────────────────────┤
│ Refund Flow  │ Refund $450 to customer #88412 │ Support Bot  │ [✓ Approve]  [✕ Reject] │
│ Deploy Sync  │ Push 1,200 leads to Salesforce │ Marketing    │ [✓ Approve]  [✕ Reject] │
└──────────────┴────────────────────────────────┴──────────────┴─────────────────────────┘
```

1. Drag the **Human Approval** card into your workflow right before the critical step.
2. When a workflow execution reaches this step, it **pauses safely**.
3. Authorized reviewers open **Approvals** (`🛡️`) in the left menu.
4. They can inspect the full customer payload, notes, and requested action.
5. Click **"Approve"** (resumes the workflow) or **"Reject"** (halts the flow). Every action is logged in an immutable audit trail.

---

## 13. AI & RAG Knowledge Base (`/knowledge`)

Empower your automations with your company's private documents:

1. Click **Knowledge** (`📚`) in the left navigation.
2. Create a collection (e.g. `ProductManuals`, `CompanyPolicies`, `SupportFAQs`).
3. Upload documents (PDF, TXT, Markdown, CSV). Flowsmith automatically chunks and embeds them into a vector database (`pgvector`).
4. In your workflows, use the **RAG Knowledge Retriever** card. When a customer asks a question, the AI retrieves relevant excerpts from your documents to generate 100% accurate, factual answers!

---

## 14. Templates, Sharing, Importing & Exporting (`/templates`)

### Templates Gallery (`/templates`)
- Browse dozens of pre-built starter automations.
- Click **"Use Template →"** on any template to instantly clone it into your workspace.

### Exporting & Sharing
- In any workflow, click the **"..."** menu in the top bar and click **"Export JSON"**.
- This downloads a clean `.json` file containing your workflow definition.
- You can share this file with colleagues or import it into another Flowsmith instance by clicking **"Import Workflow"**.

---

## 15. Testing, Debugging & Monitoring

### 15.1. Testing Single Steps vs. Full Canvas
- **Two Ways to Test a Single Node**:
  1. **Right-Click Context Menu**: Right-click any card on the visual canvas and click **"Test Step"**.
  2. **Inside Node Editor**: Double-click any card and click the **"▶ Execute Step"** button in the modal header.
- **Automatic Upstream Data Inheritance**:
  - When testing an individual node, Flowsmith automatically finds your latest execution and **seeds the test with real outputs from predecessor nodes**.
  - You test live transformations, API requests, and conditional rules against **authentic upstream data** without re-executing earlier steps or making duplicate external calls!
- **Interactive Input / Output Inspection**:
  - **Left Panel (Inputs)**: Shows the exact output of immediate parent nodes and upstream ancestors in structured Table and JSON Tree views (`$input`, `$json`).
  - **Right Panel (Output)**: Shows the resulting items generated by the node test, complete with timing (e.g. `12ms`) and status indicators.
- **Canvas Trace Preservation**:
  - Single-step tests seamlessly merge with your existing canvas execution trace.
  - Previous upstream steps retain their status badges (`● Success`), and only the tested node's output and preview update.
- **Test the Full Canvas**: Click **"Run"** (`▶`) in the top bar to run every step sequentially from start to finish.

### 15.2. Data Pinning (Mocking Data for Risk-Free Testing)
- Don't want to call your real CRM or credit card processor while designing a flow?
- Click the **📌 Pin** button on any card to lock its output.
- When pinned, Flowsmith uses that mock data for downstream steps without making real external API calls!

### 15.3. Console Drawer & Step Execution Logs
- Click **"Console"** (`📋`) in the top bar.
- Shows every run in chronological order with duration (e.g. `24ms`), status, and node-by-node execution logs.
- Click **"Retry"** on any failed execution to re-run it from the exact step that failed.

### 15.4. Version History & 1-Click Rollback
- Every time you save (`Ctrl+S`), Flowsmith creates an immutable version snapshot.
- Click **"Versions"** in the top bar to view past save points.
- Made a mistake? Click **"Rollback"** to restore any previous version with a single click.

### 15.5. System Health, Telemetry & High Performance
- **Live Readiness & Status Probe (`/api/readyz`)**:
  - Point your monitoring tools or load balancers to `http://localhost:8000/api/readyz`.
  - Returns real-time health checks for PostgreSQL and Redis (`status: ready`, `postgres: ok`, `redis: ok`).
- **High-Performance Architecture**:
  - **64% Lighter Initial Bundle**: Route code-splitting reduces the initial JavaScript chunk to just **113 kB** for instant dashboard and editor loading.
  - **Deferred Query Deserialization**: Execution histories load up to 80% faster by deferring heavy execution trace blobs during table listings.
  - **Adaptive WebSocket Live Streaming**: Event streaming automatically backs off during idle pauses, cutting database load by up to 87.5% while delivering sub-50ms execution updates.
- **Disaster Recovery Drills**:
  - Flowsmith includes automated backup streaming (`.sql.gz`) and recovery simulation via `app.dr.run_drill()`.
  - Restores verify data integrity and encryption key pairing (`CREDENTIALS_ENCRYPTION_KEY`) so your business data is always safe, encrypted, and recoverable.

---

## 16. Custom Connectors & OpenAPI / cURL Importer (`/connectors`)

Need to connect to an API that doesn't have a pre-built card?

### OpenAPI 3.0 / Swagger Importer:
1. Navigate to `/connectors`.
2. Paste any OpenAPI or Swagger specification URL (or paste raw JSON/YAML).
3. Flowsmith automatically parses all endpoints, authentication schemes, and parameters.
4. Click **"Import"**, and Flowsmith instantly generates first-class, native connector cards for that service!

### cURL Importer:
1. In the **HTTP Request** card, click **"Import cURL"**.
2. Paste any standard `curl` command from an API's documentation.
3. Flowsmith automatically extracts the URL, HTTP method, headers, query parameters, and body!

---

## 17. White-Labeling & Brand Change (Make It Your Own Platform)

Flowsmith has a built-in **100% White-Labeling Engine**. If you want your team, clients, or partners to see **your company's logo, brand colors, custom name, and support links** instead of Flowsmith, you can rebrand the entire platform in just 2 minutes!

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        BRANDING & WHITE-LABELING SETTINGS                              │
├─────────────────────────────────────────┬──────────────────────────────────────────────┤
│  Customization Form                     │  Live Preview Window                         │
│  ├── Company Name: [ Acme Corp        ] │  ┌────────────────────────────────────────┐  │
│  ├── Tagline:      [ Enterprise Ops   ] │  │ [Acme Logo] Acme Corp                  │  │
│  ├── Logo:         [📁 Upload Image   ] │  │ ⚡ Workflows  📊 Data Tables            │  │
│  ├── Brand Color:  [🔵 Indigo / Hex   ] │  │ Button: [ Save Lead ] (Acme Blue)      │  │
│  ├── Support Email:[ it@acme.com      ] │  └────────────────────────────────────────┘  │
│  └── Copyright:    [ © 2026 Acme Corp ] │  Real-time preview updates as you type!      │
└─────────────────────────────────────────┴──────────────────────────────────────────────┘
```

### What You Can Customize:

1. **Software / Company Name**:
   - Replaces "Flowsmith" everywhere: in the left sidebar, the top bar, browser window titles, and the login page.
   - *Example*: Name it `"Acme Automations"` or `"Nexus Ops"`.
2. **Tagline / Subtitle**:
   - Customizes the slogan displayed beneath your logo on the login page.
   - *Example*: `"Internal Enterprise Automation Suite"`.
3. **Company Logo**:
   - **Upload an Image**: Click **"📁 Upload Logo Image"** and choose any PNG, SVG, JPG, or WebP image from your computer (max 2MB).
   - **Or Paste a URL**: Enter any direct web link to your logo (`https://mycompany.com/logo.png`).
   - Your custom logo immediately appears in the navigation bar, sidebar, and login page.
4. **Brand Accent Color**:
   - Choose from pre-configured one-click color swatches (Indigo, Cyan, Emerald, Rose, Amber, Purple), or click the color picker to enter your exact corporate hex code (e.g. `#0ea5e9` or `#10b981`).
   - All primary buttons, active toggles, icons, and focus rings will immediately adapt to your brand color.
5. **Documentation & Runbook URL**:
   - Replaces the default help links with your company's internal wiki, Notion, or Confluence guide (e.g. `https://wiki.yourcompany.com`).
6. **Support & Helpdesk Email**:
   - Displays your internal support email (e.g. `helpdesk@yourcompany.com`) so your team knows who to contact.
7. **Footer Copyright Notice**:
   - Custom copyright text displayed at the bottom of the platform (e.g. `© 2026 Your Company Inc. All rights reserved.`).
8. **Custom CSS Overrides (Advanced)**:
   - For complete design control, you can paste custom CSS rules to adjust fonts, background patterns, or specific interface styles.

---

### Step-by-Step: How to Change Your Brand

1. Click the **Settings** gear icon (`⚙️`) in the left navigation bar.
2. Scroll down to the **"Branding & White-Labeling"** section.
3. Fill in your **Company Name**, **Tagline**, and upload your **Logo**.
4. Pick your **Brand Color**.
5. Look at the **Live Brand Preview** box on the right—it updates in real time so you can see exactly how your brand will look!
6. Click the blue button: **"✓ Save Branding"**.
7. **Done!** The changes take effect instantly across the entire application for all logged-in users.

> ↺ **Want to switch back?**  
> If you ever want to revert to the original Flowsmith look, simply click **"↺ Reset to Defaults"** at any time.

---

## 18. Keyboard Shortcuts & Canvas Navigation

| Shortcut | Action |
|---|---|
| `Ctrl + K` / `Cmd + K` | **Command Palette**: Quickly search and add any card onto the canvas without leaving the keyboard. |
| `Ctrl + S` / `Cmd + S` | **Save**: Save your workflow and create an immutable backup version snapshot. |
| `Ctrl + Z` / `Cmd + Z` | **Undo**: Revert your last canvas modification. |
| `Ctrl + Y` / `Cmd + Shift + Z` | **Redo**: Reapply your undone canvas modification. |
| `Ctrl + D` / `Cmd + D` | **Duplicate**: Make an instant copy of the selected card. |
| `Delete` / `Backspace` | **Delete**: Remove the selected card or connection wire. |
| `Esc` | **Dismiss / Close**: Close any open modal, dialog, or the Command Palette. |
| `Shift + Click` | **Multi-Select**: Select multiple cards together to drag or group them as a frame. |
| `Space + Click & Drag` | **Pan**: Move smoothly across your canvas whiteboard. |
| `Mouse Wheel` / `Pinch` | **Zoom**: Zoom in for fine details or zoom out for the big picture. |
| `Auto-Layout` | Click `⚡` in the Floating Studio Dock to neatly align all cards automatically. |

---

## 19. A to Z Complete Glossary (Every Tech Term Defined)

Here is every key term you will encounter in Flowsmith, explained in plain English:

- **Action**: A card that performs a task in an external app (e.g. creating a lead in Salesforce, sending an email).
- **Active / Inactive**: The master on/off switch for a workflow. When **Active** (green), triggers listen 24/7. When **Inactive**, it only runs when you click "Run".
- **AI Agent**: A smart card that can reason through problems, query documents, and decide which tools to call autonomously.
- **Approval Gate**: A checkpoint that pauses workflow execution until an authorized human reviews and clicks "Approve".
- **Canvas**: The visual whiteboard where you place cards and connect them with wires.
- **Connection (Edge)**: The line drawn between two cards that guides data from upstream to downstream.
- **Console**: The execution drawer where you view live run logs, timings, and data inputs/outputs.
- **Credential**: Your stored account login (e.g. your connected Salesforce or Google account), encrypted securely at rest.
- **Data Table**: A built-in spreadsheet database inside Flowsmith for storing rows and columns of data.
- **DukPy**: The embedded sandboxed JavaScript runtime used to safely run custom scripts.
- **Error Trigger**: A specialized trigger card that fires whenever another workflow encounters an error, allowing you to build automated incident alerts.
- **Expression**: A dynamic tag (like `{{ $json.email }}`) that automatically inserts live data from earlier steps.
- **Handle**: The circular port on the side of a card that you click to drag connection wires.
- **IF Condition**: A logic card that splits a workflow into two paths (True or False) based on a rule.
- **JSON**: A universal format for organizing data as labeled fields (e.g. `{"name": "Sarah", "role": "Manager"}`).
- **Knowledge Base (RAG)**: A repository of uploaded documents (PDFs, text files) used by AI to answer questions factually.
- **Merge**: A card that joins data from multiple separate branches back into one stream.
- **Node**: An individual card on the canvas representing one step in your automation.
- **OAuth2**: The secure standard used by Salesforce, Google, and Slack allowing you to connect accounts with 1-click without sharing your password.
- **Pinned Data (📌)**: Mocked output data saved directly on a card for rapid testing without making real external API calls.
- **Reconnect**: The 1-click button in Credentials that automatically renews an expired session.
- **Rollback**: Restoring a workflow to a previous version snapshot with one click.
- **Schedule Trigger**: A trigger that runs a workflow on a recurring timer (e.g. every Monday at 9 AM).
- **Split in Batches**: A utility card that breaks a large list of items into smaller chunks to prevent rate-limit errors.
- **Switch**: A logic card that routes data down multiple different paths based on conditions.
- **Token Manager**: A lifecycle card with dual handles (`valid` vs `login`) that handles authentication tokens automatically.
- **Trigger**: The starting card (alarm clock / doorbell) that begins a workflow.
- **Upstream / Downstream**: Upstream refers to cards that ran before the current card; downstream refers to cards that will run after.
- **Variables ($env)**: Workspace-level settings and encrypted secrets accessible across all workflows as `{{ $env.KEY }}`.
- **Version History**: Immutable snapshots created every time you save, allowing risk-free experimentation.
- **Webhook**: A unique web address that listens for incoming data sent by external apps or website forms.
- **Workspace**: A shared team environment containing workflows, credentials, variables, and Data Tables.

---

## 20. Frequently Asked Questions & Troubleshooting (FAQ)

### Q: Why didn't my Webhook or Schedule trigger fire automatically?
**A:** Check the switch in the top bar of your workflow. It must be set to **"Active"** (green). When set to "Inactive", workflows will only run when you manually click the "Run" button.

### Q: My Salesforce connection says "Session Expired"—how do I fix it?
**A:** Go to **Credentials** (`🔑`) in the left navigation and click **`🔄 Reconnect`**. Flowsmith will immediately renew your session in the background or prompt you to approve with a single click.

### Q: Can I test my workflow without affecting live customer records?
**A:** Yes! You have two great options:
1. Click **"▶ Execute Step"** inside any card to test only that step.
2. Click the **📌 Pin** icon on any card to lock mock data, so downstream steps test against sample data without calling live external APIs!

### Q: Where do I see error details if something fails?
**A:** Click **"Console"** (`📋`) in the top bar. You will see every execution listed. Click on the failed run to see the exact card that failed, the error message, and the data it received.

### Q: Can I run custom Python or JavaScript scripts?
**A:** Yes! Add a **Code** card to your canvas. It provides a full Monaco (VS Code) editor supporting both Python and JavaScript with secure sandboxed execution.

### Q: How do I backup or move my workflows to another server?
**A:** Click the **"..."** menu in the top bar of your workflow and select **"Export JSON"**. You can import this file into any Flowsmith instance using the **"Import Workflow"** button.

---

*Need additional assistance or want to request a feature? Contact your workspace administrator or visit the [Flowsmith GitHub Repository](https://github.com/gauravsahoo-ops/Flowsmith).*
