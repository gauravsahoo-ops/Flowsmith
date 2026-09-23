# Flowsmith User Manual (Simple & Complete Guide)

> **Who is this guide for?**  
> Everyone! Whether you are a **business owner, sales manager, marketing specialist, or software engineer**, this guide explains Flowsmith in plain English so you can build powerful automations in minutes—**no coding experience required**.

---

## Table of Contents

1. [Flowsmith in Plain English (The 1-Minute Summary)](#1-flowsmith-in-plain-english-the-1-minute-summary)
2. [Everyday Real-World Examples](#2-everyday-real-world-examples)
3. [The 4 Basic Building Blocks (The "Lego" Pieces)](#3-the-4-basic-building-blocks-the-lego-pieces)
4. [Step-by-Step: Building Your First Automation in 5 Minutes](#4-step-by-step-building-your-first-automation-in-5-minutes)
5. [Using AI to Build Workflows For You ("From AI ✨")](#5-using-ai-to-build-workflows-for-you-from-ai-)
6. [Connecting Your Apps (Salesforce, Google, Slack, etc.)](#6-connecting-your-apps-salesforce-google-slack-etc)
7. [Passing Information Between Steps (Like Mail Merge!)](#7-passing-information-between-steps-like-mail-merge)
8. [Adding Rules & Decision Making (If / Then)](#8-adding-rules--decision-making-if--then)
9. [Human Approvals (Pausing For Manager Review)](#9-human-approvals-pausing-for-manager-review)
10. [Testing, Turning ON & Monitoring](#10-testing-turning-on--monitoring)
11. [Helpful Keyboard Shortcuts](#11-helpful-keyboard-shortcuts)
12. [Plain-English Glossary (Tech Words Made Simple)](#12-plain-english-glossary-tech-words-made-simple)
13. [Frequently Asked Questions (FAQ)](#13-frequently-asked-questions-faq)

---

## 1. Flowsmith in Plain English (The 1-Minute Summary)

Think of Flowsmith like a **smart digital assistant** that connects your everyday business apps together so you never have to copy and paste data between tools again.

Whenever something happens in one app (like a customer submitting a form), Flowsmith automatically takes that information and does the work in your other apps (like saving the customer into Salesforce and pinging your team on Slack).

```
   [ 🚪 Doorbell rings ]        ──────►     [ 🔍 Check Rule ]      ──────►    [ 🤖 Robot Helper ]
"A new lead fills out a form"              "Is order > $100?"               "Add to Salesforce & send email"
```

You build these automations visually by dragging cards onto a screen and connecting them with lines—just like drawing a flowchart!

---

## 2. Everyday Real-World Examples

Here are 3 common ways people use Flowsmith every day without writing any code:

### Example 1: Instant Lead Follow-Up
- **What happens**: A visitor submits a contact form on your website.
- **What Flowsmith does**:
  1. Checks if their email is a business email.
  2. Creates a new Lead inside **Salesforce**.
  3. Sends a notification to your sales channel in **Slack**.
  4. Sends a personalized welcome email to the customer.

### Example 2: Weekly Automated Report
- **What happens**: Every Monday morning at 9:00 AM.
- **What Flowsmith does**:
  1. Pulls the latest sales numbers from your database or spreadsheet.
  2. Formats a clean summary table.
  3. Automatically emails the report to your team and leadership.

### Example 3: Order Approval with Human Review
- **What happens**: A customer requests a refund or discount over $200.
- **What Flowsmith does**:
  1. Pauses the workflow.
  2. Alerts the store manager.
  3. When the manager clicks **"Approve"** in Flowsmith, the system issues the refund and confirms it with the customer.

---

## 3. The 4 Basic Building Blocks (The "Lego" Pieces)

When you look at the canvas, you will see cards (called **Nodes**). Every automation is made of just 4 simple types of cards:

| Card Type | Color | What It Does | Real-World Analogy |
|---|---|---|---|
| **Trigger** | 🟡 **Amber** | **Starts the workflow.** Waits for an event or a time schedule. | An **alarm clock** or a **doorbell**. |
| **Action / App** | 🔵 **Blue** | **Does something in an app.** (e.g. Salesforce, Slack, Gmail, Sheets). | A **helper** who delivers a letter or updates a spreadsheet. |
| **Logic / Filter** | 🟣 **Purple** | **Makes decisions.** (e.g. IF order is over $500, go top path; else go bottom path). | A **fork in the road** or a traffic light. |
| **AI Assistant** | 🔷 **Cyan** | **Thinks and analyzes.** Summarizes text, classifies sentiment, or extracts details. | An **analyst** who reads an email and summarizes it. |

---

## 4. Step-by-Step: Building Your First Automation in 5 Minutes

Let's walk through creating your very first workflow from scratch:

```
[ Webhook / Form ]  ──────────────────►  [ Salesforce / Action ]
  (Trigger card)        (Drag line)           (Action card)
```

### Step 1: Create a New Workflow
1. Log in to Flowsmith.
2. In the left menu, click **Workflows** (`⚡`).
3. Click the blue button: **"＋ Create workflow"**.
4. You now have a blank visual canvas!

### Step 2: Add Your Trigger (The Starting Point)
1. Open the cards menu on the left side (or press `Ctrl+K` on your keyboard).
2. Find the **Webhook** card (under *Triggers*) and drag it onto the canvas.
   *(This gives you a unique link where external apps or website forms can send information).*

### Step 3: Add Your Action (The App That Does Work)
1. In the cards menu, find **Salesforce** (or **Slack**, or **Email**).
2. Drag it onto the canvas to the right of your Webhook card.

### Step 4: Connect Them With a Line
1. Notice the small circle on the right side of the Webhook card.
2. Click that circle and drag a line over to the circle on the left side of your action card.
3. Release the mouse. You have now connected the two steps!

### Step 5: Configure Your Action Card
1. Double-click your action card. A clean window opens in the center of your screen.
2. Select your account (e.g. your connected Salesforce account).
3. Choose what you want it to do (e.g. *"Create a Lead"*).
4. Click **"▶ Execute Step"** to test it with a sample run.
5. Click the **"✕"** button in the top right to close the editor.

### Step 6: Turn It ON!
1. Click **"Save"** (`Ctrl+S`) in the top bar.
2. Look at the switch in the top bar that says **"Inactive"**. Click it to switch it to **"Active"** (it turns green).
3. **Congratulations!** Your automation is now running 24/7. Whenever data arrives, Flowsmith takes care of it automatically.

---

## 5. Using AI to Build Workflows For You ("From AI ✨")

Don't want to drag cards manually? Let AI do it for you!

1. On the **Workflows** page, click the button that says **"From AI ✨"**.
2. Type what you want in normal, everyday English. For example:
   > *"When a customer submits a contact form, check if they are interested in Enterprise. If yes, add them as a Lead in Salesforce and alert the sales team on Slack."*
3. Click **Generate Workflow**.
4. Flowsmith's AI will automatically choose the right cards, wire them together, and configure the rules for you in seconds! You can then customize it however you like.

---

## 6. Connecting Your Apps (Salesforce, Google, Slack, etc.)

Connecting your work accounts in Flowsmith takes **just 1 click**:

### How to Connect an Account:
1. In the left menu, click **Credentials** (`🔑`).
2. Pick the service you want to connect (e.g. **Salesforce** or **Google**).
3. Click the blue **`[ Connect ]`** button.
4. A secure popup window will open asking you to log into that app and click **Allow / Approve**.
5. Once you approve, the window closes automatically, and your account will show a green **`● Connected`** badge.

### What if a Session Expires Later?
Sometimes services like Salesforce or Google expire old logins for security. 
- You will see an amber badge: **`● Session Expired`**.
- Simply click the **`🔄 Reconnect`** button next to it!
- Flowsmith will immediately renew your connection in the background. You don't have to re-enter complex passwords or reconfigure any workflows.

> 🛡️ **Is my data safe?**  
> **Yes, 100%.** Flowsmith encrypts all account connections in an encrypted database vault using high-grade enterprise encryption (AES-256). No one—not even system administrators—can read your raw passwords or tokens.

---

## 7. Passing Information Between Steps (Like Mail Merge!)

Have you ever used **Mail Merge** in Microsoft Word or email marketing tools where you write:
> *"Hi {{ First Name }}, thank you for your order of {{ Product Name }}!"*

Flowsmith works the **exact same way**!

### How to Use Information From an Earlier Step:
1. Double-click any card to open its editor.
2. On the left side of the window, you will see the **Input Panel**. This shows all the information received from earlier steps (like Name, Email, Company, Phone).
3. **Just click on any field** (e.g. click on `email`). Flowsmith will automatically copy its tag!
4. Paste it into your field: `{{ $json.email }}`.
5. When the automation runs, Flowsmith automatically replaces `{{ $json.email }}` with the real customer's email address!

| You Type | What Flowsmith Fills In Live |
|---|---|
| `{{ $json.customer_name }}` | `"Sarah Jenkins"` |
| `{{ $json.email }}` | `"sarah@example.com"` |
| `{{ $json.order_total }}` | `"$249.00"` |

---

## 8. Adding Rules & Decision Making (If / Then)

Real business processes have rules. For example: *"Only notify the manager if the order value is greater than $500."*

### Using the IF Condition Card:
1. Drag an **IF** card (purple) onto your canvas.
2. Connect your previous step to the IF card.
3. In the IF settings, pick your rule:
   - *Field*: `{{ $json.order_total }}`
   - *Comparison*: `is greater than`
   - *Value*: `500`
4. Notice the IF card has **two output handles**:
   - 🟢 **Top handle (`true`)**: Runs when the rule matches (Order is > $500). Wire this to your Slack notification!
   - 🔴 **Bottom handle (`false`)**: Runs when the rule does not match (Order is ≤ $500). Wire this to normal processing.

---

## 9. Human Approvals (Pausing For Manager Review)

Sometimes you don't want an automation to do something sensitive (like issuing a refund or deleting a record) without a human looking at it first.

### How to Add a Human Checkpoint:
1. Add the **Human Approval** card right before the sensitive action.
2. When the automation reaches this card, it **pauses safely**.
3. A notification appears under the **Approvals** tab (`🛡️ /approvals`).
4. A manager opens the screen, reviews the customer details and requested amount, and clicks **"Approve"** or **"Reject"**.
5. Once approved, the automation wakes up and finishes the job!

---

## 10. Testing, Turning ON & Monitoring

### Testing Before You Launch
You never have to guess whether your automation works:
- Click the **"Run"** (`▶`) button in the top bar at any time to test the canvas.
- Cards that succeed will show a green checkmark (`✔`).
- If a card has an issue, it will highlight in red (`✖`) and tell you exactly what needs fixing.

### Seeing Past Runs (The Console)
- Click **"Console"** (`📋`) in the top bar.
- This opens a side drawer showing every single time your automation ran, how many seconds it took, and what information passed through each step.
- If an external website went down during a run, you can simply click **"Retry"** to re-run that step without starting over!

### Restoring Past Versions (Undo Button for the Whole Workflow)
- Made a change you didn't like?
- Click **"Versions"** in the top bar to view past saves and click **"Rollback"** to restore any earlier version of your workflow instantly.

---

## 11. Helpful Keyboard Shortcuts

| Shortcut | What It Does |
|---|---|
| `Ctrl + K` / `Cmd + K` | **Quick Add**: Search and insert any card onto your canvas instantly. |
| `Ctrl + S` / `Cmd + S` | **Save**: Saves your workflow and creates a backup version. |
| `Ctrl + D` / `Cmd + D` | **Duplicate**: Makes a copy of the selected card. |
| `Delete` / `Backspace` | **Delete**: Removes the selected card or wire. |
| `Hold Space + Drag` | **Pan**: Move smoothly across your canvas. |
| `Mouse Wheel` | **Zoom**: Zoom in or out to see your whole workflow. |

---

## 12. Plain-English Glossary (Tech Words Made Simple)

| Term | What It Means in Plain English |
|---|---|
| **Workflow** | An automated sequence or "recipe" of steps that runs automatically. |
| **Canvas** | The visual whiteboard screen where you build your workflows. |
| **Node** | A single card or step in your workflow (e.g. "Send Email"). |
| **Trigger** | The starting event (the "doorbell") that wakes up your workflow. |
| **Action** | A step that does something in an external app (like creating a contact). |
| **Edge / Wire** | The connection line that guides data from one step to the next. |
| **Handle** | The little circle on the side of a card that you click to drag connection lines. |
| **Credential** | Your secure account connection (e.g. your Salesforce or Google login). |
| **Active** | Turned ON. When active, your automation runs automatically 24/7. |
| **Inactive / Draft** | Turned OFF. Use this mode while editing or testing safely. |
| **Expression** | A placeholder tag (like `{{ $json.name }}`) that automatically fills in live information. |

---

## 13. Frequently Asked Questions (FAQ)

### Q: Do I need to know how to code to use Flowsmith?
**A: No, not at all!** Over 95% of tasks (connecting apps, moving data, filtering records, sending emails, and updating CRMs) are done purely with visual cards and simple point-and-click settings.

### Q: Why didn't my automation run when I tested an external form?
**A:** Check the switch in the top bar of your workflow. Make sure it is flipped from **"Inactive"** to **"Active"** (green). When inactive, workflows only run when you manually click the "Run" button.

### Q: What if my Salesforce login expires?
**A:** You never need to rebuild your workflow. Just go to **Credentials** (`🔑`) in the left navigation and click **`🔄 Reconnect`**. Flowsmith will renew the connection in one click!

### Q: Can multiple people on my team use Flowsmith together?
**A:** Yes! Flowsmith has full multi-user support with **Organizations** and **Workspaces**, so your team can collaborate, share workflows, and manage permissions securely.

### Q: What if I need custom calculations or advanced scripting?
**A:** If you or an engineer on your team ever wants to write code, Flowsmith includes a built-in **Code** card that supports standard JavaScript and Python with a full code editor.

---

*Need help or have questions? Reach out to your Flowsmith workspace administrator or visit our [GitHub Repository](https://github.com/gauravsahoo-ops/Flowsmith).*
