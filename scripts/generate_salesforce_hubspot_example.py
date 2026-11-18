"""Generate the Salesforce -> HubSpot contact-sync example workflows.

The example is deliberately two workflows:

* ``wf_salesforce_to_hubspot_contact_sync`` (parent) queries Salesforce,
  normalises/scores the records, skips incomplete records, and runs the
  child once per eligible contact.
* ``wf_salesforce_hubspot_contact_upsert`` (child) upserts the HubSpot
  company, contact, and (for high-value accounts) deal, then associates
  them.  Running it as a database sub-workflow keeps each child run's
  expressions scoped to that run instead of being pre-resolved in the
  parent's context.

Run from the repository root:

    .venv\\Scripts\\python.exe scripts\\generate_salesforce_hubspot_example.py
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "examples"

PARENT_ID = "wf_salesforce_to_hubspot_contact_sync"
CHILD_ID = "wf_salesforce_hubspot_contact_upsert"
SF_CREDENTIAL_PLACEHOLDER = "REPLACE_WITH_SALESFORCE_CREDENTIAL_ID"
HS_CREDENTIAL_PLACEHOLDER = "REPLACE_WITH_HUBSPOT_CREDENTIAL_ID"

SOQL = """\
SELECT Id, FirstName, LastName, Name, Email, Title, Phone, Department,
       LeadSource, AccountId, Account.Name, Account.Website, Account.Industry,
       Account.BillingCountry, Account.BillingCity, Account.AnnualRevenue,
       Account.NumberOfEmployees, Account.Type, Account.Owner.Name,
       Account.Owner.Email
FROM Contact
WHERE Email != null AND AccountId != null
ORDER BY LastModifiedDate DESC
LIMIT 200"""


def node(
    node_id: str,
    node_type: str,
    *,
    name: str,
    parameters: dict[str, Any] | None = None,
    credentials: dict[str, str] | None = None,
    settings: dict[str, Any] | None = None,
    x: float = 0,
    y: float = 0,
) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": node_type,
        "name": name,
        "position": {"x": x, "y": y},
        "parameters": parameters or {},
        "credentials": credentials or {},
        "settings": settings or {},
    }


def edge(source: str, target: str, source_handle: str = "main") -> dict[str, str]:
    return {
        "source": source,
        "sourceHandle": source_handle,
        "target": target,
        "targetHandle": "main",
    }


# ---------------------------------------------------------------------------
# Parent: Salesforce query -> normalise/score -> fan out -> child per contact
# ---------------------------------------------------------------------------

NORMALIZE_CODE = textwrap.dedent(
    r"""
    query_items = items or []
    raw_records = []
    for entry in query_items:
        records = entry.get("records") if entry else None
        if records:
            for record in records:
                if record:
                    raw_records.append(record)

    industry_map = {
        "technology": "COMPUTER_SOFTWARE",
        "software": "COMPUTER_SOFTWARE",
        "computer software": "COMPUTER_SOFTWARE",
        "information technology": "INFORMATION_TECHNOLOGY_AND_SERVICES",
        "it services": "INFORMATION_TECHNOLOGY_AND_SERVICES",
        "internet": "INTERNET",
        "telecommunications": "TELECOMMUNICATIONS",
        "telecom": "TELECOMMUNICATIONS",
        "financial services": "FINANCIAL_SERVICES",
        "finance": "FINANCIAL_SERVICES",
        "banking": "FINANCIAL_SERVICES",
        "insurance": "FINANCIAL_SERVICES",
        "healthcare": "HOSPITAL_HEALTH_CARE",
        "health care": "HOSPITAL_HEALTH_CARE",
        "hospital": "HOSPITAL_HEALTH_CARE",
        "retail": "RETAIL",
        "e-commerce": "RETAIL",
        "ecommerce": "RETAIL",
        "education": "EDUCATION_MANAGEMENT",
        "higher education": "EDUCATION_MANAGEMENT",
        "marketing": "MARKETING_AND_ADVERTISING",
        "advertising": "MARKETING_AND_ADVERTISING",
        "construction": "CONSTRUCTION",
        "real estate": "REAL_ESTATE",
        "nonprofit": "NON_PROFIT_ORGANIZATION_MANAGEMENT",
        "non-profit": "NON_PROFIT_ORGANIZATION_MANAGEMENT",
        "government": "GOVERNMENT_ADMINISTRATION",
        "public sector": "GOVERNMENT_ADMINISTRATION",
        "legal": "LEGAL_SERVICES",
        "accounting": "ACCOUNTING",
        "staffing": "STAFFING_AND_RECRUITING",
        "recruiting": "STAFFING_AND_RECRUITING",
        "transportation": "TRANSPORTATION_TRUCKING_RAILROAD",
        "logistics": "LOGISTICS_AND_SUPPLY_CHAIN",
        "food": "FOOD_BEVERAGES",
        "beverage": "FOOD_BEVERAGES",
        "consumer goods": "CONSUMER_GOODS",
        "entertainment": "ENTERTAINMENT",
        "utilities": "UTILITIES",
        "semiconductors": "SEMICONDUCTORS",
        "research": "RESEARCH",
        "design": "DESIGN",
    }
    country_map = {
        "usa": "United States",
        "us": "United States",
        "u.s.": "United States",
        "united states": "United States",
        "united states of america": "United States",
        "uk": "United Kingdom",
        "united kingdom": "United Kingdom",
        "great britain": "United Kingdom",
        "canada": "Canada",
        "germany": "Germany",
        "de": "Germany",
        "france": "France",
        "australia": "Australia",
        "netherlands": "Netherlands",
        "sweden": "Sweden",
        "india": "India",
        "japan": "Japan",
        "singapore": "Singapore",
        "brazil": "Brazil",
        "mexico": "Mexico",
    }
    industry_targets = (
        "COMPUTER_SOFTWARE",
        "INFORMATION_TECHNOLOGY_AND_SERVICES",
        "INTERNET",
        "TELECOMMUNICATIONS",
        "SEMICONDUCTORS",
    )
    country_targets = (
        "United States",
        "Canada",
        "United Kingdom",
        "Germany",
        "France",
        "Australia",
        "Netherlands",
        "Sweden",
    )

    contacts = []
    for record in raw_records:
        account = record.get("Account") or {}
        email = str(record.get("Email") or "").strip().lower()
        first_name = str(record.get("FirstName") or "").strip()
        last_name = str(record.get("LastName") or "").strip()
        full_name = str(record.get("Name") or "").strip()
        if not full_name:
            full_name = (first_name + " " + last_name).strip()
        title = str(record.get("Title") or "").strip()
        phone = str(record.get("Phone") or "").strip()
        lead_source = str(record.get("LeadSource") or "").strip()

        account_name = str(account.get("Name") or "").strip()
        website = str(account.get("Website") or "").strip().lower()
        domain = website
        if "://" in domain:
            domain = domain.split("://", 1)[1]
        if domain.startswith("www."):
            domain = domain[4:]
        if "/" in domain:
            domain = domain.split("/", 1)[0]
        if "?" in domain:
            domain = domain.split("?", 1)[0]
        if "#" in domain:
            domain = domain.split("#", 1)[0]
        if ":" in domain:
            domain = domain.split(":", 1)[0]
        domain = domain.strip().strip(".")
        if " " in domain or "." not in domain:
            domain = ""

        revenue = 0.0
        revenue_raw = account.get("AnnualRevenue")
        if revenue_raw:
            try:
                revenue = float(str(revenue_raw).replace(",", "").replace("$", ""))
            except:
                revenue = 0.0

        employees = 0
        employees_raw = account.get("NumberOfEmployees")
        if employees_raw:
            try:
                employees = int(float(str(employees_raw).replace(",", "")))
            except:
                employees = 0

        industry_raw = str(account.get("Industry") or "").strip()
        hubspot_industry = industry_map.get(industry_raw.lower(), "")
        country_raw = str(account.get("BillingCountry") or "").strip()
        country = country_map.get(country_raw.lower(), country_raw)
        city = str(account.get("BillingCity") or "").strip()
        account_type = str(account.get("Type") or "").strip()
        owner = account.get("Owner") or {}
        owner_name = str(owner.get("Name") or "").strip()

        score = 0
        if email:
            score += 10
        if title:
            score += 10
        if phone:
            score += 5
        if revenue >= 1000000:
            score += 30
        elif revenue >= 250000:
            score += 20
        elif revenue > 0:
            score += 10
        if employees >= 500:
            score += 20
        elif employees >= 50:
            score += 10
        if hubspot_industry in industry_targets:
            score += 15
        if country in country_targets:
            score += 10
        if account_type.lower() == "customer":
            score += 20
        if lead_source.lower() in ("web", "partner", "referral", "referral program"):
            score += 10
        if score > 100:
            score = 100

        if score >= 75:
            tier = "A"
        elif score >= 45:
            tier = "B"
        else:
            tier = "C"
        is_high_value = score >= 75 or revenue >= 1000000

        if account_type.lower() == "customer":
            lifecycle = "customer"
        elif score >= 80:
            lifecycle = "salesqualifiedlead"
        elif score >= 50:
            lifecycle = "marketingqualifiedlead"
        else:
            lifecycle = "lead"

        if score >= 75:
            lead_status = "OPEN"
        elif score >= 45:
            lead_status = "IN_PROGRESS"
        else:
            lead_status = "NEW"

        skip_reasons = []
        if not email:
            skip_reasons.append("missing_email")
        if not domain:
            skip_reasons.append("missing_company_domain")
        eligible = len(skip_reasons) == 0

        company_properties = {
            "name": account_name or domain,
            "domain": domain,
            "lifecyclestage": lifecycle,
            "description": (
                "Salesforce Account " + str(account.get("Id") or "")
                + " | Owner: " + owner_name
                + " | Lead score: " + str(score)
                + " | Tier: " + tier
            ),
        }
        if hubspot_industry:
            company_properties["industry"] = hubspot_industry
        if city:
            company_properties["city"] = city
        if country:
            company_properties["country"] = country
        if revenue:
            company_properties["annualrevenue"] = str(int(revenue))
        if employees:
            company_properties["numberofemployees"] = str(employees)

        contact_properties = {
            "email": email,
            "lifecyclestage": lifecycle,
            "hs_lead_status": lead_status,
        }
        if first_name:
            contact_properties["firstname"] = first_name
        if last_name:
            contact_properties["lastname"] = last_name
        if title:
            contact_properties["jobtitle"] = title
        if phone:
            contact_properties["phone"] = phone
        if account_name or domain:
            contact_properties["company"] = account_name or domain
        if city:
            contact_properties["city"] = city

        deal_name = (
            "Flowsmith Sync | " + (account_name or domain)
            + " | " + str(record.get("Id") or "")
        )
        deal_properties = {
            "dealname": deal_name,
            "dealstage": "appointmentscheduled",
            "pipeline": "default",
            "dealtype": "newbusiness",
            "description": (
                "High-value contact sync from Salesforce."
                " Contact: " + full_name + " <" + email + ">"
                + " | Lead score: " + str(score)
                + " | Account: " + (account_name or domain)
            ),
        }
        if revenue:
            deal_properties["amount"] = str(int(revenue))

        contacts.append({
            "sf_contact_id": str(record.get("Id") or ""),
            "sf_account_id": str(account.get("Id") or ""),
            "sf_contact_name": full_name,
            "contact_email": email,
            "contact_first_name": first_name,
            "contact_last_name": last_name,
            "account_name": account_name or domain,
            "company_domain": domain,
            "industry": industry_raw,
            "hubspot_industry": hubspot_industry,
            "country": country,
            "city": city,
            "annual_revenue": revenue,
            "employees": employees,
            "lead_score": score,
            "lead_tier": tier,
            "is_high_value": is_high_value,
            "eligible_for_sync": eligible,
            "skip_reason": "; ".join(skip_reasons),
            "company_properties": company_properties,
            "contact_properties": contact_properties,
            "deal_name": deal_name,
            "deal_properties": deal_properties,
        })

    eligible_count = 0
    for contact in contacts:
        if contact.get("eligible_for_sync"):
            eligible_count += 1
    for contact in contacts:
        contact["batch_fetched"] = len(contacts)
        contact["batch_eligible"] = eligible_count
        contact["batch_skipped"] = len(contacts) - eligible_count

    return [{
        "contacts": contacts,
        "fetched_count": len(contacts),
        "eligible_count": eligible_count,
        "skipped_count": len(contacts) - eligible_count,
    }]
    """
).strip()

SUMMARY_CODE = textwrap.dedent(
    r"""
    items = items or []
    rows = items
    if len(rows) == 1 and rows[0] and "items" in rows[0]:
        rows = rows[0].get("items") or []
    summary = {
        "fetched": 0,
        "eligible": 0,
        "skipped": 0,
        "synced": 0,
        "failed": 0,
        "companies_created": 0,
        "companies_updated": 0,
        "contacts_created": 0,
        "contacts_updated": 0,
        "deals_created": 0,
        "deals_updated": 0,
        "deals_not_applicable": 0,
        "contact_company_associations": 0,
        "deal_company_associations": 0,
    }
    results = []
    for item in rows:
        if not item:
            continue
        if "batch_fetched" in item and "status" not in item:
            summary["fetched"] = int(item.get("batch_fetched") or 0)
            summary["eligible"] = int(item.get("batch_eligible") or 0)
            continue
        if "$error" in item:
            summary["failed"] += 1
            error = item.get("$error") or {}
            results.append({
                "status": "failed",
                "error": str(error.get("message") or "unknown error"),
            })
            continue
        status = str(item.get("status") or "")
        if status == "skipped":
            summary["skipped"] += 1
            results.append({
                "status": "skipped",
                "sf_contact_id": item.get("sf_contact_id", ""),
                "contact_email": item.get("contact_email", ""),
                "account_name": item.get("account_name", ""),
                "reason": item.get("skip_reason", ""),
            })
            continue

        summary["synced"] += 1
        if item.get("company_action") == "created":
            summary["companies_created"] += 1
        if item.get("company_action") == "updated":
            summary["companies_updated"] += 1
        if item.get("contact_action") == "created":
            summary["contacts_created"] += 1
        if item.get("contact_action") == "updated":
            summary["contacts_updated"] += 1
        if item.get("deal_action") == "created":
            summary["deals_created"] += 1
        if item.get("deal_action") == "updated":
            summary["deals_updated"] += 1
        if item.get("deal_action") == "not_applicable":
            summary["deals_not_applicable"] += 1
        if item.get("association_ok"):
            summary["contact_company_associations"] += 1
        if item.get("deal_association_ok"):
            summary["deal_company_associations"] += 1

        results.append({
            "status": "synced",
            "sf_contact_id": item.get("sf_contact_id", ""),
            "contact_email": item.get("contact_email", ""),
            "account_name": item.get("account_name", ""),
            "lead_score": item.get("lead_score", 0),
            "lead_tier": item.get("lead_tier", ""),
            "company_id": item.get("company_id", ""),
            "company_action": item.get("company_action", ""),
            "contact_id": item.get("contact_id", ""),
            "contact_action": item.get("contact_action", ""),
            "deal_id": item.get("deal_id", ""),
            "deal_action": item.get("deal_action", ""),
        })

    return [{
        "status": "error" if summary["failed"] else "success",
        "summary": summary,
        "results": results,
    }]
    """
).strip()


def build_parent() -> dict[str, Any]:
    nodes = [
        node("start", "manual_trigger", name="Manual Trigger", x=0, y=0),
        node(
            "fetch_contacts",
            "salesforce",
            name="Fetch Salesforce Contacts",
            parameters={
                "operation": "query",
                "soql": SOQL,
                "max_pages": 5,
            },
            credentials={"salesforce": SF_CREDENTIAL_PLACEHOLDER},
            settings={"retry_max_attempts": 2, "retry_backoff_seconds": 2},
            x=220,
            y=0,
        ),
        node(
            "normalize",
            "code",
            name="Normalize and Score",
            parameters={
                "language": "python",
                "mode": "runOnceForAllItems",
                "code": NORMALIZE_CODE,
            },
            x=440,
            y=0,
        ),
        node(
            "fan_out",
            "split",
            name="One Item Per Contact",
            parameters={
                "field": "contacts",
                "include": "allOtherFields",
                "batch_size": 0,
            },
            x=660,
            y=0,
        ),
        node(
            "eligible",
            "if_condition",
            name="Eligible for Sync?",
            parameters={
                "conditions": [
                    {
                        "id": "eligible",
                        "left": "{{ $json.eligible_for_sync }}",
                        "operator": "is true",
                        "right": "",
                        "combinator": "AND",
                    }
                ],
                "combinator": "AND",
            },
            x=880,
            y=0,
        ),
        node(
            "sync_contact",
            "sub_workflow",
            name="Sync Contact to HubSpot",
            parameters={
                "source": "database",
                "workflow_selector": "id",
                "workflow_id": CHILD_ID,
                "mode": "onceForEach",
                "options": {"waitForSubWorkflowCompletion": True},
            },
            settings={"continue_on_error": True, "timeout_seconds": 120},
            x=1100,
            y=-120,
        ),
        node(
            "skip_contact",
            "set_data",
            name="Record Skipped Contact",
            parameters={
                "mode": "merge",
                "fields": {
                    "status": "skipped",
                    "skip_reason": "{{ $json.skip_reason }}",
                    "sf_contact_id": "{{ $json.sf_contact_id }}",
                    "contact_email": "{{ $json.contact_email }}",
                    "account_name": "{{ $json.account_name }}",
                    "batch_fetched": "{{ $json.batch_fetched }}",
                    "batch_eligible": "{{ $json.batch_eligible }}",
                },
            },
            x=1100,
            y=120,
        ),
        node(
            "collect",
            "merge",
            name="Collect Sync Results",
            parameters={"strategy": "concat"},
            x=1320,
            y=0,
        ),
        node(
            "batch_meta",
            "set_data",
            name="Batch Metadata",
            parameters={
                "mode": "replace",
                "fields": {
                    "batch_fetched": "{{ $json.fetched_count }}",
                    "batch_eligible": "{{ $json.eligible_count }}",
                    "batch_skipped": "{{ $json.skipped_count }}",
                },
            },
            x=1320,
            y=160,
        ),
        node(
            "aggregate_results",
            "aggregate",
            name="Aggregate Results",
            parameters={"field": "items"},
            x=1540,
            y=60,
        ),
        node(
            "summarize",
            "code",
            name="Summarize Sync",
            parameters={
                "language": "python",
                "mode": "runOnceForAllItems",
                "code": SUMMARY_CODE,
            },
            x=1760,
            y=60,
        ),
        node(
            "failed",
            "if_condition",
            name="Any Failures?",
            parameters={
                "conditions": [
                    {
                        "id": "failed",
                        "left": "{{ $json.summary.failed }}",
                        "operator": "is greater than",
                        "right": 0,
                        "combinator": "AND",
                    }
                ],
                "combinator": "AND",
            },
            x=1760,
            y=0,
        ),
        node(
            "stop",
            "stop_and_error",
            name="Stop on Sync Failures",
            parameters={
                "error_type": "errorMessage",
                "error_message": (
                    "Salesforce to HubSpot sync finished with "
                    "{{ $json.summary.failed }} failed contact(s). "
                    "Inspect the execution trace for details."
                ),
            },
            x=1980,
            y=-120,
        ),
        node("complete", "noop", name="Sync Complete", x=1980, y=120),
    ]

    connections = [
        edge("start", "fetch_contacts"),
        edge("fetch_contacts", "normalize"),
        edge("normalize", "fan_out"),
        edge("fan_out", "eligible"),
        edge("eligible", "sync_contact", "true"),
        edge("eligible", "skip_contact", "false"),
        edge("sync_contact", "collect"),
        edge("skip_contact", "collect"),
        edge("normalize", "batch_meta"),
        edge("collect", "aggregate_results"),
        edge("batch_meta", "aggregate_results"),
        edge("aggregate_results", "summarize"),
        edge("summarize", "failed"),
        edge("failed", "stop", "true"),
        edge("failed", "complete", "false"),
    ]

    return {
        "id": PARENT_ID,
        "name": "Salesforce to HubSpot Contact Sync",
        "status": "draft",
        "nodes": nodes,
        "connections": connections,
        "settings": {
            "max_parallelism": 1,
            "timeout_seconds": 600,
        },
    }


# ---------------------------------------------------------------------------
# Child: one contact in, one sync result out
# ---------------------------------------------------------------------------


def _carry_from(prefix: str, keys: tuple[str, ...]) -> dict[str, str]:
    return {key: "{{ $node." + prefix + ".json." + key + " }}" for key in keys}


COMPANY_CARRY = (
    "sf_contact_id",
    "sf_account_id",
    "contact_email",
    "account_name",
    "lead_score",
    "lead_tier",
    "is_high_value",
    "company_id",
    "company_action",
    "company_domain",
    "deal_name",
    "deal_properties",
    "batch_fetched",
    "batch_eligible",
)
CONTACT_CARRY = (
    "contact_id",
    "contact_action",
    "company_id",
    "company_action",
    "company_domain",
    "sf_contact_id",
    "sf_account_id",
    "contact_email",
    "account_name",
    "lead_score",
    "lead_tier",
    "is_high_value",
    "deal_name",
    "deal_properties",
    "batch_fetched",
    "batch_eligible",
)
ASSOCIATION_CARRY = CONTACT_CARRY + ("association_ok",)


def build_child() -> dict[str, Any]:
    hs_settings = {"retry_max_attempts": 2, "retry_backoff_seconds": 1}
    # HubSpot creates are non-idempotent: a retried 429/5xx can duplicate the
    # record. Search/update/associate are safe to retry; creates are not.
    hs_create_settings = {"retry_max_attempts": 0, "retry_backoff_seconds": 1}
    hs_credentials = {"hubspot": HS_CREDENTIAL_PLACEHOLDER}

    nodes = [
        node("start", "manual_trigger", name="Contact Input", x=0, y=0),
        node(
            "search_company",
            "hubspot",
            name="Find Company by Domain",
            parameters={
                "operation": "search",
                "object_type": "companies",
                "search_field": "domain",
                "search_value": "{{ $node.start.json.company_domain }}",
                "limit": 1,
            },
            credentials=hs_credentials,
            settings=hs_settings,
            x=220,
            y=0,
        ),
        node(
            "company_found",
            "if_condition",
            name="Company Exists?",
            parameters={
                "conditions": [
                    {
                        "id": "company_found",
                        "left": "{{ $json.found }}",
                        "operator": "is true",
                        "right": "",
                        "combinator": "AND",
                    }
                ],
                "combinator": "AND",
            },
            x=440,
            y=0,
        ),
        node(
            "update_company",
            "hubspot",
            name="Update Company",
            parameters={
                "operation": "update",
                "object_type": "companies",
                "record_id": "{{ $node.search_company.json.record.id }}",
                "properties": "{{ $node.start.json.company_properties }}",
            },
            credentials=hs_credentials,
            settings=hs_settings,
            x=660,
            y=-80,
        ),
        node(
            "create_company",
            "hubspot",
            name="Create Company",
            parameters={
                "operation": "create",
                "object_type": "companies",
                "properties": "{{ $node.start.json.company_properties }}",
            },
            credentials=hs_credentials,
            settings=hs_create_settings,
            x=660,
            y=80,
        ),
        node(
            "company_done",
            "merge",
            name="Company Upserted",
            parameters={"strategy": "concat"},
            x=880,
            y=0,
        ),
        node(
            "company_context",
            "set_data",
            name="Carry Company Context",
            parameters={
                "mode": "merge",
                "fields": {
                    "company_id": "{{ $json.id }}",
                    "company_action": (
                        "{{ $node.search_company.json.found ? 'updated' : 'created' }}"
                    ),
                    "company_domain": "{{ $node.start.json.company_domain }}",
                    "sf_contact_id": "{{ $node.start.json.sf_contact_id }}",
                    "sf_account_id": "{{ $node.start.json.sf_account_id }}",
                    "contact_email": "{{ $node.start.json.contact_email }}",
                    "contact_properties": "{{ $node.start.json.contact_properties }}",
                    "account_name": "{{ $node.start.json.account_name }}",
                    "lead_score": "{{ $node.start.json.lead_score }}",
                    "lead_tier": "{{ $node.start.json.lead_tier }}",
                    "is_high_value": "{{ $node.start.json.is_high_value }}",
                    "deal_name": "{{ $node.start.json.deal_name }}",
                    "deal_properties": "{{ $node.start.json.deal_properties }}",
                    "batch_fetched": "{{ $node.start.json.batch_fetched }}",
                    "batch_eligible": "{{ $node.start.json.batch_eligible }}",
                },
            },
            x=1100,
            y=0,
        ),
        node(
            "search_contact",
            "hubspot",
            name="Find Contact by Email",
            parameters={
                "operation": "search",
                "object_type": "contacts",
                "search_field": "email",
                "search_value": "{{ $node.start.json.contact_email }}",
                "limit": 1,
            },
            credentials=hs_credentials,
            settings=hs_settings,
            x=1320,
            y=0,
        ),
        node(
            "contact_found",
            "if_condition",
            name="Contact Exists?",
            parameters={
                "conditions": [
                    {
                        "id": "contact_found",
                        "left": "{{ $json.found }}",
                        "operator": "is true",
                        "right": "",
                        "combinator": "AND",
                    }
                ],
                "combinator": "AND",
            },
            x=1540,
            y=0,
        ),
        node(
            "update_contact",
            "hubspot",
            name="Update Contact",
            parameters={
                "operation": "update",
                "object_type": "contacts",
                "record_id": "{{ $node.search_contact.json.record.id }}",
                "properties": "{{ $node.start.json.contact_properties }}",
            },
            credentials=hs_credentials,
            settings=hs_settings,
            x=1760,
            y=-80,
        ),
        node(
            "create_contact",
            "hubspot",
            name="Create Contact",
            parameters={
                "operation": "create",
                "object_type": "contacts",
                "properties": "{{ $node.start.json.contact_properties }}",
            },
            credentials=hs_credentials,
            settings=hs_create_settings,
            x=1760,
            y=80,
        ),
        node(
            "contact_done",
            "merge",
            name="Contact Upserted",
            parameters={"strategy": "concat"},
            x=1980,
            y=0,
        ),
        node(
            "contact_context",
            "set_data",
            name="Carry Contact Context",
            parameters={
                "mode": "merge",
                "fields": {
                    "contact_id": "{{ $json.id }}",
                    "contact_action": (
                        "{{ $node.search_contact.json.found ? 'updated' : 'created' }}"
                    ),
                    **_carry_from("company_context", COMPANY_CARRY),
                },
            },
            x=2200,
            y=0,
        ),
        node(
            "associate_contact_company",
            "hubspot",
            name="Associate Contact to Company",
            parameters={
                "operation": "associate_records",
                "from_object_type": "contacts",
                "from_record_id": "{{ $node.contact_context.json.contact_id }}",
                "to_object_type": "companies",
                "to_record_id": "{{ $node.contact_context.json.company_id }}",
                "association_type_id": "1",
            },
            credentials=hs_credentials,
            settings=hs_settings,
            x=2420,
            y=0,
        ),
        node(
            "association_context",
            "set_data",
            name="Carry Association Context",
            parameters={
                "mode": "merge",
                "fields": {
                    "association_ok": "{{ $json.success }}",
                    **_carry_from("contact_context", CONTACT_CARRY),
                },
            },
            x=2640,
            y=0,
        ),
        node(
            "high_value",
            "if_condition",
            name="High-Value Account?",
            parameters={
                "conditions": [
                    {
                        "id": "high_value",
                        "left": "{{ $json.is_high_value }}",
                        "operator": "is true",
                        "right": "",
                        "combinator": "AND",
                    }
                ],
                "combinator": "AND",
            },
            x=2860,
            y=0,
        ),
        node(
            "search_deal",
            "hubspot",
            name="Find Deal by Name",
            parameters={
                "operation": "search",
                "object_type": "deals",
                "search_field": "dealname",
                "search_value": "{{ $node.association_context.json.deal_name }}",
                "limit": 1,
            },
            credentials=hs_credentials,
            settings=hs_settings,
            x=3080,
            y=-120,
        ),
        node(
            "deal_found",
            "if_condition",
            name="Deal Exists?",
            parameters={
                "conditions": [
                    {
                        "id": "deal_found",
                        "left": "{{ $json.found }}",
                        "operator": "is true",
                        "right": "",
                        "combinator": "AND",
                    }
                ],
                "combinator": "AND",
            },
            x=3300,
            y=-120,
        ),
        node(
            "update_deal",
            "hubspot",
            name="Update Deal",
            parameters={
                "operation": "update",
                "object_type": "deals",
                "record_id": "{{ $node.search_deal.json.record.id }}",
                "properties": "{{ $node.association_context.json.deal_properties }}",
            },
            credentials=hs_credentials,
            settings=hs_settings,
            x=3520,
            y=-200,
        ),
        node(
            "create_deal",
            "hubspot",
            name="Create Deal",
            parameters={
                "operation": "create",
                "object_type": "deals",
                "properties": "{{ $node.association_context.json.deal_properties }}",
            },
            credentials=hs_credentials,
            settings=hs_create_settings,
            x=3520,
            y=-40,
        ),
        node(
            "deal_done",
            "merge",
            name="Deal Upserted",
            parameters={"strategy": "concat"},
            x=3740,
            y=-120,
        ),
        node(
            "associate_deal_company",
            "hubspot",
            name="Associate Deal to Company",
            parameters={
                "operation": "associate_records",
                "from_object_type": "deals",
                "from_record_id": "{{ $json.id }}",
                "to_object_type": "companies",
                "to_record_id": "{{ $node.association_context.json.company_id }}",
                "association_type_id": "5",
            },
            credentials=hs_credentials,
            settings=hs_settings,
            x=3960,
            y=-120,
        ),
        node(
            "deal_context",
            "set_data",
            name="Carry Deal Context",
            parameters={
                "mode": "merge",
                "fields": {
                    "deal_id": "{{ $json.from_record_id }}",
                    "deal_action": (
                        "{{ $node.deal_found.json.found ? 'updated' : 'created' }}"
                    ),
                    "deal_association_ok": "{{ $json.success }}",
                    "status": "synced",
                    **_carry_from("association_context", ASSOCIATION_CARRY),
                },
            },
            x=4180,
            y=-120,
        ),
        node(
            "deal_skipped",
            "set_data",
            name="No Deal Required",
            parameters={
                "mode": "merge",
                "fields": {
                    "deal_id": "",
                    "deal_action": "not_applicable",
                    "deal_association_ok": False,
                    "status": "synced",
                    **_carry_from("association_context", ASSOCIATION_CARRY),
                },
            },
            x=3080,
            y=120,
        ),
        node(
            "deal_paths",
            "merge",
            name="Collect Deal Path",
            parameters={"strategy": "concat"},
            x=4400,
            y=0,
        ),
        node(
            "result",
            "set_data",
            name="Contact Sync Result",
            parameters={
                "mode": "merge",
                "fields": {
                    "status": "synced",
                    "deal_id": "{{ $json.deal_id }}",
                    "deal_action": "{{ $json.deal_action }}",
                    "deal_association_ok": "{{ $json.deal_association_ok }}",
                    **_carry_from("association_context", ASSOCIATION_CARRY),
                },
            },
            x=4620,
            y=0,
        ),
    ]

    connections = [
        edge("start", "search_company"),
        edge("search_company", "company_found"),
        edge("company_found", "update_company", "true"),
        edge("company_found", "create_company", "false"),
        edge("update_company", "company_done"),
        edge("create_company", "company_done"),
        edge("company_done", "company_context"),
        edge("company_context", "search_contact"),
        edge("search_contact", "contact_found"),
        edge("contact_found", "update_contact", "true"),
        edge("contact_found", "create_contact", "false"),
        edge("update_contact", "contact_done"),
        edge("create_contact", "contact_done"),
        edge("contact_done", "contact_context"),
        edge("contact_context", "associate_contact_company"),
        edge("associate_contact_company", "association_context"),
        edge("association_context", "high_value"),
        edge("high_value", "search_deal", "true"),
        edge("high_value", "deal_skipped", "false"),
        edge("search_deal", "deal_found"),
        edge("deal_found", "update_deal", "true"),
        edge("deal_found", "create_deal", "false"),
        edge("update_deal", "deal_done"),
        edge("create_deal", "deal_done"),
        edge("deal_done", "associate_deal_company"),
        edge("associate_deal_company", "deal_context"),
        edge("deal_context", "deal_paths"),
        edge("deal_skipped", "deal_paths"),
        edge("deal_paths", "result"),
    ]

    return {
        "id": CHILD_ID,
        "name": "HubSpot Contact Upsert (Salesforce Contact)",
        "status": "draft",
        "nodes": nodes,
        "connections": connections,
        "settings": {
            "max_parallelism": 1,
            "timeout_seconds": 300,
        },
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    parent = build_parent()
    child = build_child()
    for name, workflow in (
        ("salesforce_to_hubspot_contact_sync.json", parent),
        ("salesforce_hubspot_contact_upsert.json", child),
    ):
        path = OUT_DIR / name
        path.write_text(
            json.dumps(workflow, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
