# Final Salesforce Demonstration — Live Walkthrough

Real org: `gaurav.sahoo@idslogic.com` (Dev Edition)
Connected via OAuth "Connect Salesforce" (PKCE + refresh token, server-side client id/secret).

Workflow shape:

```
Manual Trigger
      │
      ▼
Set Data (email)
      │
      ▼
Salesforce — Search Lead by Email
      │
      ▼
IF / Condition ($json.found)
   /     \
 YES      NO
  │        │
  ▼        ▼
Update    Create
```

---

## Step 1 — Log in

1. Open `http://localhost:8000` in Chrome.
2. Log in with your account.
3. You land on the **Workflows** list. Click **+ New Workflow**, name it `Salesforce Demo`, click **Create**.

## Step 2 — Open the visual editor

You are on the canvas (grid area). The **ConfigPanel** is on the right. Add nodes from the palette/toolbar.

## Step 3 — Add the nodes

Add these in order and connect them:

| Node | Connect from | Output handle → Input |
|---|---|---|
| **Manual Trigger** | — | main → Set Data |
| **Set / Edit Data** | Manual Trigger | main → Salesforce |
| **Salesforce** | Set Data | main → IF |
| **IF / Condition** | Salesforce | **true** → Update, **false** → Create |

## Step 4 — Configure Set Data

In the **Set / Edit Data** node config:

```
mode:  merge
fields:
  email:  demo.live@example.com   ← change this between demo runs
```

## Step 5 — Configure the Salesforce node

In the **Salesforce** node config:

- **Credential** (dropdown): select **Salesforce (gaurav.sahoo@idslogic.com)** ← the OAuth connection
- **Operation**: `search`
- **Object name**: `Lead`
- **Search field**: `Email`
- **Search value**: `{{ $json.email }}`

The `{{ $json.email }}` expression pulls the email from the Set Data node's item.

## Step 6 — Configure IF / Condition

```
condition:
  left:      $json.found
  operator:  equals
  right:     true
```

`$json.found` is the `found` field the Salesforce search outputs (`true` when the Lead already exists).

## Step 7 — Configure the Update branch (true)

In the **Update** Salesforce node config:

- **Credential**: **Salesforce (gaurav.sahoo@idslogic.com)**
- **Operation**: `update`
- **Object name**: `Lead`
- **Record id**: `{{ $json.record.Id }}`
- **Record** (fields to change):
  ```
  Company:  ACME (demo)
  ```

Note the node id of the **Set Data** node (e.g. `set_data_1` — shown on the node) — you'll need it in Step 8.

## Step 8 — Configure the Create branch (false)

In the **Create** Salesforce node config:

- **Credential**: **Salesforce (gaurav.sahoo@idslogic.com)**
- **Operation**: `create`
- **Object name**: `Lead`
- **Record**:
  ```
  FirstName:  Demo
  LastName:   Candidate
  Company:    ACME
  Email:      {{ $node.set_data_1.json.email }}   ← use your actual Set Data node id
  ```

## Step 9 — Save the workflow

Click **Save** in the toolbar. The node configs (including the credential reference) are persisted.

## Step 10 — Execute (run 1 → Create branch)

1. Click **Run**.
2. Watch the **Execution panel / history**: status goes `running` → `success`.
3. The Salesforce node output shows `"found": false` → IF routes to the **false** (Create) handle.
4. Create returns a new Lead id, e.g. `00Q...` — this is created in your **real org**.

> **Duplicate-rule note**: your org has the **Standard Lead Duplicate Rule** active
> (alert mode). If a Create matches an existing record the connector now handles it
> gracefully — the record is still created and the workflow succeeds with
> `"duplicate_alert": true` plus the recovered Lead id (no hard failure).

Verify in Salesforce: the Lead `demo.live@example.com` now exists.

## Step 11 — Execute (run 2 → Update branch)

1. Open the **Set Data** node and set `email` to the **same** value (`demo.live@example.com`).
2. Save, then **Run** again.
3. Now the Salesforce search finds the Lead → `"found": true` → IF routes to the **true** (Update) handle.
4. Update sets `Company = ACME (demo)` on that Lead.

Verify in Salesforce: the same Lead's Company is now `ACME (demo)`.

## Step 12 — Review the live results & history

- Open the **execution trace** for either run — you'll see full record details (Id, Name, attributes) — no `[truncated]`.
- Open **Execution History** — both runs listed newest first with statuses `success`.
- The trace never contains the OAuth refresh token; credentials stay encrypted in the DB.

---

## Demo talking points

- **No secrets in the UI** — client id/secret/redirect URI live server-side.
- **One-click connect** — OAuth with PKCE, multi-user isolated (each user gets their own connection).
- **Real API** — every operation hits the actual Salesforce REST API (no mocks).
- **Branching** — IF routes on `$json.found` to Update (existing) or Create (new).
- **Trace** — record payloads fully visible; tokens never logged.

## Re-run notes

- Change the email in Set Data to any fresh value to demo Create again.
- To demo a custom object instead of Lead, swap `Lead` → `Recruitment__c` and adjust the search field (that object has only `Id` and `Name`; emails live in `Name`).