# Flowsmith Complete User Manual (A to Z Guide)

> **Who is this guide for?**  
> Everyone! Whether you are a **business owner, sales rep, operations manager, IT specialist, or software engineer**, this manual covers everything in Flowsmith from **A to Z** in simple, plain English—with no coding experience required.

---

## Master Table of Contents

1. [Flowsmith in 60 Seconds (The Big Picture)](#1-flowsmith-in-60-seconds-the-big-picture)
2. [Everyday Real-World Examples](#2-everyday-real-world-examples)
3. [The Flowsmith Interface (Screen Tour)](#3-the-flowsmith-interface-screen-tour)
4. [The 4 Basic Building Blocks (The "Lego" Pieces)](#4-the-4-basic-building-blocks-the-lego-pieces)
5. [5-Minute Quick Start: Building Your First Automation](#5-5-minute-quick-start-building-your-first-automation)
6. [Using AI to Build Workflows For You ("From AI ✨")](#6-using-ai-to-build-workflows-for-you-from-ai-)
7. [The Complete Card Catalog (Every Node Explained)](#7-the-complete-card-catalog-every-node-explained)
   - [Triggers (Starting Points)](#71-triggers-starting-points)
   - [App Connectors (Salesforce, Google, Slack, etc.)](#72-app-connectors-salesforce-google-slack-etc)
   - [Logic & Routing (Decisions, Splits & Merges)](#73-logic--routing-decisions-splits--merges)
   - [Data Transforms (Calculations, Filtering, Code)](#74-data-transforms-calculations-filtering-code)
   - [AI & Knowledge (Agents, Summarizers, RAG)](#75-ai--knowledge-agents-summarizers-rag)
8. [Connecting Your Accounts (Credentials & 1-Click OAuth)](#8-connecting-your-accounts-credentials--1-click-oauth)
   - [1-Click Connecting](#81-1-click-connecting)
   - [Checking Status (Connected vs. Expired)](#82-checking-status-connected-vs-expired)
   - [1-Click Reconnect](#83-1-click-reconnect)
   - [Security Guarantee](#84-security-guarantee)
9. [Passing Information Between Steps (The "Mail Merge" Engine)](#9-passing-information-between-steps-the-mail-merge-engine)
10. [Environment Variables & Secrets (`/variables`)](#10-environment-variables--secrets-variables)
11. [Built-In Relational Data Tables (`/data-tables`)](#11-built-in-relational-data-tables-data-tables)
12. [Human Approvals & Review Gates (`/approvals`)](#12-human-approvals--review-gates-approvals)
13. [AI & RAG Knowledge Base (`/knowledge`)](#13-ai--rag-knowledge-base-knowledge)
14. [Templates, Sharing, Importing & Exporting](#14-templates-sharing-importing--exporting)
15. [Testing, Debugging & Monitoring](#15-testing-debugging--monitoring)
    - [Testing Single Steps vs. Full Canvas](#151-testing-single-steps-vs-full-canvas)
    - [Data Pinning (Mocking Data)](#152-data-pinning-mocking-data)
    - [Console Drawer & Execution Traces](#153-console-drawer--execution-traces)
    - [Version History & 1-Click Rollback](#154-version-history--1-click-rollback)
16. [Custom Connectors & OpenAPI / cURL Importer](#16-custom-connectors--openapi--curl-importer)
17. [White-Labeling & Company Branding (`/settings/branding`)](#17-white-labeling--company-branding-settingsbranding)
18. [Keyboard Shortcuts & Canvas Navigation](#18-keyboard-shortcuts--canvas-navigation)
19. [A to Z Complete Glossary (Every Tech Term Defined)](#19-a-to-z-complete-glossary-every-tech-term-defined)
20. [Frequently Asked Questions & Troubleshooting (FAQ)](#20-frequently-asked-questions--troubleshooting-faq)

---

## 1. Flowsmith in 60 Seconds (The Big Picture)

Think of Flowsmith like a **super-smart digital conveyor belt** connecting all of your company's software. 

Whenever something happens in one app (like a customer submitting a form on your website), Flowsmith automatically picks up that data, checks your business rules, and performs actions across your other apps (like saving the record in Salesforce, notifying your team in Slack, and emailing the customer).

```
   [ 🚪 Doorbell rings ]        ──────►     [ 🔍 Check Rule ]      ──────►    [ 🤖 Robot Helper ]
"A new lead fills out a form"              "Is order > $100?"               "Add to Salesforce & send email"
```

- **Visual Canvas**: You build everything by dragging visual cards onto a canvas and connecting them with lines—just like drawing a flowchart.
- **Zero Coding Required**: Over 95% of workflows can be built purely with point-and-click settings.
- **Unlimited & Private**: Self-hosted on your own servers with zero per-run fees and 100% encrypted data security.

---

## 2. Everyday Real-World Examples

### Example 1: Sales Lead Capture & Instant Follow-Up
- **What happens**: A prospect fills out the "Contact Us" form on your website.
- **What Flowsmith does**:
  1. Captures the form submission immediately via a **Webhook**.
  2. Creates or updates a Lead record inside **Salesforce**.
  3. Sends an instant notification to `#sales-leads` in **Slack** with a direct link to the Salesforce record.
  4. Automatically sends a personalized confirmation email to the prospect via **Gmail** or **Outlook**.

### Example 2: Weekly KPI Report Automation
- **What happens**: Every Monday morning at 9:00 AM.
- **What Flowsmith does**:
  1. A **Schedule** trigger wakes up.
  2. Queries your **Data Table** or CRM for closed deals and revenue from the past 7 days.
  3. Formats the data into a clean HTML table.
  4. Emails the executive summary to leadership and management.

### Example 3: Order Refund with Manager Approval
- **What happens**: A customer service agent requests a refund over $200.
- **What Flowsmith does**:
  1. Hits a **Human Approval** card and safely pauses.
  2. Sends an approval alert to the manager.
  3. The manager opens Flowsmith, inspects the customer history, and clicks **"Approve"**.
  4. Flowsmith automatically wakes up, issues the refund via **Stripe**, updates the CRM, and emails the customer a receipt.

---

## 3. The Flowsmith Interface (Screen Tour)

When you log in to Flowsmith, you have a sleek, clean interface divided into 3 main areas:

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

1. **Left Navigation Bar**:
   - **Workflows (`⚡`)**: View, create, and organize your automation pipelines.
   - **Credentials (`🔑`)**: Connect and manage your accounts (Salesforce, Google, Slack, etc.).
   - **Data Tables (`📊`)**: In-app spreadsheet database for storing records.
   - **Variables (`🌍`)**: Manage environment variables and encrypted secrets (`{{ $env.KEY }}`).
   - **Approvals (`🛡️`)**: Review and approve workflows paused for human inspection.
   - **Knowledge (`📚`)**: Upload PDF, text, and doc files for AI vector search (RAG).
   - **Templates (`🎨`)**: Pre-built starter workflows ready to clone in one click.
2. **Top Bar**:
   - **Workflow Title**: Click to rename your workflow.
   - **Run (`▶`)**: Click to manually run and test the canvas with sample inputs.
   - **Active / Inactive Toggle**: Turns your workflow live (green) so triggers run 24/7.
   - **Console (`📋`)**: Opens the execution history drawer to inspect live step logs and outputs.
   - **Versions (`🕒`)**: View past save points and rollback anytime.
3. **The Canvas**:
   - The central visual whiteboard where you add cards, wire them together, and arrange your business logic.

---

## 4. The 4 Basic Building Blocks (The "Lego" Pieces)

Every automation in Flowsmith is made of just 4 simple types of cards (called **Nodes**):

| Card Category | Badge Color | What It Does | Real-World Analogy |
|---|---|---|---|
| **Trigger** | 🟡 **Amber** | **Starts the workflow.** Listens for an event, inbound form, or schedule. | An **alarm clock** or a **doorbell**. |
| **Connector / Action** | 🔵 **Blue** | **Does work in an app.** (e.g. Salesforce, Slack, Gmail, Sheets, Stripe). | A **postal worker** or helper doing a task. |
| **Logic & Filter** | 🟣 **Purple** | **Makes decisions.** (IF condition, Switch, Merge, Split into Batches). | A **fork in the road** or traffic light. |
| **AI Assistant** | 🔷 **Cyan** | **Analyzes and thinks.** Summarizes emails, extracts fields, answers questions. | A **smart assistant** reading a document. |

---

## 5. 5-Minute Quick Start: Building Your First Automation

Let's build a real, working automation in under 5 minutes:

### Step 1: Create a Workflow
1. Click **Workflows** (`⚡`) in the left navigation.
2. Click the blue **"＋ Create workflow"** button.
3. You will see an empty canvas.

### Step 2: Add a Trigger
1. Click the **"＋ Add Node"** button on the left (or press `Ctrl+K`).
2. Search for **Webhook** and drag it onto the canvas.
   *(This gives you a unique web URL where external apps or websites can send data).*

### Step 3: Add an Action Card
1. Search for **Salesforce** (or **Slack**, or **Email**).
2. Drag it onto the canvas to the right of the Webhook card.

### Step 4: Wire the Cards Together
1. Notice the small circle (**handle**) on the right side of the Webhook card.
2. Click and hold that circle, then drag a line to the circle on the left side of the action card.
3. Release the mouse. You have created an **Edge** (a connection wire)!

### Step 5: Configure the Action
1. Double-click the action card. The centered **3-Panel Node Editor** opens:
   - **Left Panel (Inputs)**: Shows data coming from previous cards.
   - **Center Panel (Parameters)**: Choose your connected account and action (e.g. *"Create Lead"*).
   - **Right Panel (Output)**: Shows the result when tested.
2. Click **"▶ Execute Step"** to test it.
3. Click **"✕"** in the top right corner to close the editor.

### Step 6: Save and Turn ON!
1. Press `Ctrl+S` (or click **"Save"** in the top bar).
2. Click the switch in the top bar from **"Inactive"** to **"Active"** (it turns green).
3. **You're live!** Your automation is now listening and running automatically 24/7.

---

## 6. Using AI to Build Workflows For You ("From AI ✨")

If you don't want to drag cards manually, you can have Flowsmith build the entire workflow for you:

1. On the **Workflows** page, click the button that says **"From AI ✨"**.
2. Type your requirement in everyday English. For example:
   > *"When a customer submits a contact request, check if their budget is over $10,000. If yes, create a high-priority Lead in Salesforce and alert the sales team on Slack. Otherwise, send them our standard brochure email."*
3. Click **Generate Workflow**.
4. In seconds, Flowsmith selects the exact cards needed, positions them on the canvas, sets up the branching logic, and wires them together!
5. You can then inspect any card, tweak parameters, and activate it immediately.

---

## 7. The Complete Card Catalog (Every Node Explained)

### 7.1. Triggers (Starting Points)
- **Webhook**: Gives you a unique URL to receive instant data from website forms, Stripe payments, Shopify orders, or external systems. Supports synchronous responses (`respond_to_webhook`).
- **Schedule**: An automated timer. Run your workflow every 15 minutes, every morning at 8:00 AM, or on specific days using a standard calendar picker or Cron schedule.
- **Salesforce Trigger**: Fires immediately when an Object (Lead, Contact, Opportunity, Case) is created or updated in Salesforce.
- **Email Trigger (IMAP)**: Listens to an email inbox and triggers whenever a new email arrives matching your sender or subject filters.
- **Error Trigger**: Automatically catches errors from other workflows and routes failure alerts to Slack, SMS, or PagerDuty.

### 7.2. App Connectors (Salesforce, Google, Slack, etc.)
Flowsmith comes with **45+ native first-party connectors**:
- **Salesforce**: Search SOQL, Create, Update, Upsert, Get, Delete records across standard and custom objects.
- **Google Sheets & Docs**: Read spreadsheet rows, append new rows, update cells, or generate Google Docs.
- **Gmail & Outlook**: Send rich HTML emails, send attachments, search inbox threads.
- **Slack & Microsoft Teams**: Post formatted messages, adaptive cards, and channel notifications.
- **HubSpot & Pipedrive**: Manage CRM contacts, companies, deals, and pipeline stages.
- **Stripe**: Manage customers, inspect invoices, verify charges, and issue refunds.
- **Jira, GitHub, GitLab, Bitbucket**: Create issues, manage pull requests, comment on tickets.
- **Twilio & WhatsApp**: Send SMS notifications or Meta Cloud API WhatsApp template messages.
- **Airtable & Notion**: Query bases, insert records, create and update workspace pages.
- **HTTP Request**: The universal connector! Connect to **any external REST API** on the internet with full support for GET, POST, PUT, DELETE, headers, and authentication.

### 7.3. Logic & Routing (Decisions, Splits & Merges)
- **IF Condition**: Evaluates boolean rules (`equals`, `contains`, `greater than`, `regex`). Sends items through either the **true** (top) or **false** (bottom) wire.
- **Switch**: Multi-way routing. Directs data down 4+ different paths based on status, department, or tier.
- **Merge**: Combines data arriving from two different branches into a unified dataset.
- **Split In Batches**: Takes large lists (e.g. 5,000 records) and processes them in smaller batches (e.g. 50 at a time) to prevent API rate-limit errors.
- **Wait / Delay**: Pauses execution for a specific duration (e.g. "Wait 2 days before sending follow-up email").

### 7.4. Data Transforms (Calculations, Filtering, Code)
- **Set Variables**: Define or overwrite fields on your data items.
- **Filter**: Drop records that don't match specific criteria (e.g. only keep records where `status == 'active'`).
- **Code (JavaScript & Python)**: A built-in Monaco (VS Code) editor where you can write custom scripts for complex math, data scrubbing, or custom transformations.
- **Token Manager**: A smart dual-handle node (`🟢 valid` vs `🟠 login`) that manages access tokens, reuses valid sessions, and prevents redundant login calls.

### 7.5. AI & Knowledge (Agents, Summarizers, RAG)
- **AI Agent**: An autonomous reasoning engine that can use external tools (search web, query database, run calculations) to complete tasks.
- **RAG Knowledge Retriever**: Queries your uploaded company documents and passes relevant excerpts to AI prompts.
- **Text Summarizer & Classifier**: Classifies incoming customer tickets (e.g. "Billing", "Bug", "Feature Request") or summarizes long email threads.

---

## 8. Connecting Your Accounts (Credentials & 1-Click OAuth)

Flowsmith features a **1-click frictionless OAuth connection experience**:

### 8.1. 1-Click Connecting
1. In the left navigation, click **Credentials** (`🔑`).
2. Under **New Credential**, click on the app you want to connect (e.g. **Salesforce** or **Google**).
3. Click the blue **`[ Connect <App> ]`** button.
4. A secure popup opens. Simply log into your account and click **Allow / Approve**.
5. The popup closes automatically, and your account appears in the **Connected Credentials** table!

### 8.2. Checking Status (Connected vs. Expired)
In the Credentials table, each account displays a live status badge:
- 🟢 **`● Connected`**: Active and healthy. Workflows can use this connection freely.
- 🟡 **`● Session Expired`**: The service requires a token renewal.

### 8.3. 1-Click Reconnect
If a connection ever expires:
1. Click the **`🔄 Reconnect`** button on that row.
2. Flowsmith automatically renews the session in the background.
3. If the provider requires re-approval, the popup seamlessly navigates to the login prompt. Click approve, and you're done!

### 8.4. Security Guarantee
- All passwords, API tokens, and OAuth keys are **100% encrypted at rest** in PostgreSQL using **AES-256 Fernet** ciphertexts (`k0:...`).
- Credentials are never stored in plain text files, never touch `.env`, and cannot be read by anyone over the API.

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

## 10. Environment Variables & Secrets (`/variables`)

Use workspace variables for values you want to reuse across multiple workflows (like your company's base URL, support email, or secret API keys):

1. Click **Variables** (`🌍`) in the left navigation.
2. Click **"Add Variable"**.
3. Enter the key name (e.g. `SUPPORT_EMAIL`) and value (`support@mycompany.com`).
4. **Secret Variables**: Check the **"Secret"** box for sensitive passwords or tokens. Secrets are encrypted in the database and masked with asterisks (`••••••••`) in the interface.
5. In any workflow node, reference it as: `{{ $env.SUPPORT_EMAIL }}`.

---

## 11. Built-In Relational Data Tables (`/data-tables`)

Flowsmith has a built-in spreadsheet database so you can store, edit, and query records without spinning up an external database:

1. Click **Data Tables** (`📊`) in the left navigation.
2. Click **"Create Table"** (e.g. `VIP_Customers`, `Inventory`, `SupportTickets`).
3. Define your columns with strict types: `Text`, `Number`, `Boolean`, `Date`, or `JSON`.
4. Add or edit rows directly in the spreadsheet view, sort by columns, and search instantly.
5. **In Workflows**: Add the **Data Table** card to search records, insert rows, or update status automatically.

---

## 12. Human Approvals & Review Gates (`/approvals`)

For high-risk operations (e.g. refunds over $500, bulk customer deletions, production deployments):

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

## 14. Templates, Sharing, Importing & Exporting

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
- **Test a Single Card**: Double-click any card and click **"▶ Execute Step"**. This runs only that specific node using upstream data, letting you test settings instantly without running the entire workflow!
- **Test the Full Canvas**: Click **"Run"** (`▶`) in the top bar to run every step sequentially from start to finish.

### 15.2. Data Pinning (Mocking Data)
- Don't want to call your real CRM or credit card processor while designing a flow?
- Click the **📌 Pin** button on any card to lock its output.
- When pinned, Flowsmith uses that mock data for downstream steps without making real external API calls!

### 15.3. Console Drawer & Execution Traces
- Click **"Console"** (`📋`) in the top bar.
- Shows every run in chronological order with duration (e.g. `24ms`), status, and node-by-node execution logs.
- Click **"Retry"** on any failed execution to re-run it from the exact step that failed.

### 15.4. Version History & 1-Click Rollback
- Every time you save (`Ctrl+S`), Flowsmith creates an immutable version snapshot.
- Click **"Versions"** in the top bar to view past save points.
- Made a mistake? Click **"Rollback"** to restore any previous version with a single click.

---

## 16. Custom Connectors & OpenAPI / cURL Importer

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

## 17. White-Labeling & Company Branding (`/settings/branding`)

You can completely customize Flowsmith to match your company's brand identity:

1. Click **Settings** ➔ **Branding** in the navigation.
2. Customize:
   - **Company Name & Tagline**: Displayed across the top bar and login page.
   - **Brand Logo & Favicon**: Upload your company's official logo.
   - **Color Palette**: Choose primary accent colors or dark/light themes.
   - **Custom CSS**: Inject custom CSS rules for typography and custom corporate styling.
3. Changes apply instantly across the entire application for all team members.

---

## 18. Keyboard Shortcuts & Canvas Navigation

| Shortcut | Action |
|---|---|
| `Ctrl + K` / `Cmd + K` | **Command Palette**: Quickly search and add any card onto the canvas. |
| `Ctrl + S` / `Cmd + S` | **Save**: Save your workflow and create an immutable backup version. |
| `Ctrl + D` / `Cmd + D` | **Duplicate**: Make an instant copy of the selected card. |
| `Delete` / `Backspace` | **Delete**: Remove the selected card or connection wire. |
| `Space + Click & Drag` | **Pan**: Move smoothly across your canvas whiteboard. |
| `Mouse Wheel` | **Zoom**: Zoom in for fine details or zoom out for the big picture. |
| **Auto-Layout Button** | Click in the bottom-left canvas toolbar to neatly align all cards automatically. |

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
