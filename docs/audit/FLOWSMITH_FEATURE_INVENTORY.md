# Flowsmith Source-Code Feature Inventory

**Audit Date**: October 18, 2026  
**Derivation Method**: Automated Source Code AST & Runtime Inspection  
**Canonical Baseline**: Single Source of Truth  

---

## 1. High-Level Inventory Summary

| Artifact Category | Actual Count | Source Registry / Origin | Status |
|:---|:---:|:---|:---:|
| **Canonical Built-in Nodes** | 71 | `app.nodes.registry.NODE_REGISTRY` | 100% Verified |
| **Node Aliases** | 6 | `app.nodes.registry._ALIASES` | 100% Verified |
| **Registered Connectors** | 528 | `app.connectors.registry.ConnectorRegistry` | 100% Verified |
| **Connector Operations** | 1505 | `ConnectorDefinitionV1.operations` | 100% Verified |
| **Connector Triggers** | 120 | `ConnectorDefinitionV1.triggers` | 100% Verified |
| **Unique Credential Types** | 405 | `ConnectorDefinitionV1.credential_types` | 100% Verified |
| **LLM Platform Providers** | 188 | `app.ai.llm_registry.LLMProviderRegistry` | 100% Verified |
| **FastAPI Route Paths** | 200 | FastAPI OpenAPI Specification | 100% Verified |
| **API Operations** | 244 | FastAPI OpenAPI Specification | 100% Verified |
| **SQLAlchemy ORM Tables** | 41 | `app.db.Base.metadata.tables` | 100% Verified |
| **Frontend Application Pages** | 26 | `frontend/src/pages/` & `App.jsx` | 100% Verified |

---

## 2. Built-in Node Registry (71 Canonical Nodes)

| Node Type | Display Name | Category | Idempotency | Version | Operations | Handles (In / Out) |
|:---|:---|:---:|:---:|:---:|:---:|:---:|
| `ai` | AI | AI | `non-idempotent` | `1` | none | main &rarr; main |
| `ai_agent` | AI Agent | AI | `non-idempotent` | `2` | none | main &rarr; main |
| `embeddings` | Embeddings | AI | `idempotent` | `1` | none | main &rarr; main |
| `memory` | Memory | AI | `conditionally_idempotent` | `2` | none | main &rarr; main |
| `output_parser` | Output Parser | AI | `idempotent` | `1` | none | main &rarr; main |
| `rag_pipeline` | RAG Pipeline | AI | `non-idempotent` | `1` | none | main &rarr; main |
| `reranker` | AI Reranker | AI | `idempotent` | `1` | none | main &rarr; main |
| `text_splitter` | Text Splitter | AI | `idempotent` | `1` | none | main &rarr; main |
| `auth_fetch` | Auth Fetch | Actions | `conditionally_idempotent` | `1` | none | main &rarr; main |
| `auth_store` | Auth Store | Actions | `conditionally_idempotent` | `1` | none | main &rarr; main |
| `file_io` | File I/O | Actions | `idempotent` | `2` | none | main &rarr; main |
| `graphql` | GraphQL | Actions | `conditionally_idempotent` | `1` | none | main &rarr; main |
| `http_request` | HTTP Request | Actions | `conditionally_idempotent` | `3` | none | main &rarr; main |
| `rss_feed` | RSS Feed | Actions | `idempotent` | `1` | none | main &rarr; main |
| `set_variable` | Set Variable | Actions | `idempotent` | `1` | none | main &rarr; main |
| `soap_request` | SOAP Request | Actions | `conditionally_idempotent` | `1` | none | main &rarr; main |
| `token_fetch` | Token Fetch | Actions | `conditionally_idempotent` | `1` | none | main &rarr; main |
| `token_manager` | Token Manager | Actions | `conditionally_idempotent` | `1` | none | main &rarr; valid, login |
| `token_store` | Token Store | Actions | `conditionally_idempotent` | `1` | none | main &rarr; main |
| `email_read` | Read Email | Communication | `idempotent` | `1` | none | main &rarr; main |
| `send_email` | Send Email | Communication | `non-idempotent` | `1` | none | main &rarr; main |
| `slack` | Slack | Communication | `idempotent` | `1` | none | main &rarr; main |
| `telegram` | Telegram | Communication | `idempotent` | `1` | none | main &rarr; main |
| `websocket` | WebSocket | Communication | `idempotent` | `2` | none | main &rarr; main |
| `flowsmith.data_load` | Flowsmith DataLoad | Data Transformation | `idempotent` | `1` | none | main &rarr; main |
| `data_table` | Data Table | Database | `conditionally_idempotent` | `1` | none | main &rarr; main |
| `database_query` | Database Query | Database | `conditionally_idempotent` | `1` | none | main &rarr; main |
| `elasticsearch` | Elasticsearch | Database | `conditionally_idempotent` | `1` | none | main &rarr; main |
| `compare_datasets` | Compare Datasets | Flow | `idempotent` | `1` | none | input_a, input_b, main &rarr; main, different, same |
| `execute_workflow_trigger` | When executed by Another Workflow | Flow | `idempotent` | `1` | none | default &rarr; main |
| `filter` | Filter | Flow | `idempotent` | `1` | none | main &rarr; main |
| `ftp` | FTP | Flow | `idempotent` | `1` | none | main &rarr; main |
| `git` | Git | Flow | `idempotent` | `1` | none | main &rarr; main |
| `if_condition` | If | Flow | `idempotent` | `2` | none | main &rarr; true, false |
| `loop` | Loop / ForEach | Flow | `idempotent` | `1` | none | main &rarr; done, loop |
| `loop_over_items` | Loop Over Items | Flow | `idempotent` | `1` | none | main &rarr; done, loop |
| `merge` | Merge | Flow | `idempotent` | `1` | none | main &rarr; main |
| `noop` | NoOp | Flow | `idempotent` | `1` | none | main &rarr; main |
| `respond_to_webhook` | Respond to Webhook | Flow | `idempotent` | `1` | none | main &rarr; main |
| `router` | Router | Flow | `idempotent` | `1` | none | main &rarr; route_0, route_1, default |
| `split` | Split Out | Flow | `idempotent` | `1` | none | main &rarr; main |
| `split_out` | Split Out | Flow | `idempotent` | `1` | none | main &rarr; main |
| `ssh` | SSH | Flow | `idempotent` | `1` | none | main &rarr; main |
| `stop_and_error` | Stop and Error | Flow | `idempotent` | `1` | none | main &rarr; main |
| `sub_workflow` | Execute Sub-workflow | Flow | `conditionally_idempotent` | `1` | none | main &rarr; main |
| `switch` | Switch | Flow | `idempotent` | `1` | none | main &rarr; route_0, route_1, route_2, default |
| `wait` | Wait | Flow | `idempotent` | `1` | none | main &rarr; main |
| `human_approval` | Human Approval | Logic | `idempotent` | `1` | none | main &rarr; main |
| `loop_while` | Loop While | Logic | `idempotent` | `1` | none | main &rarr; main |
| `pagination` | Pagination | Logic | `idempotent` | `1` | none | main &rarr; main |
| `aggregate` | Aggregate | Transform | `idempotent` | `1` | none | main &rarr; main |
| `code` | Code | Transform | `idempotent` | `1` | none | main &rarr; main |
| `compression` | Compression | Transform | `idempotent` | `1` | none | main &rarr; main |
| `crypto_tools` | Crypto | Transform | `idempotent` | `1` | 10 (hash, hmac, base64_encode...) | main &rarr; main |
| `csv_json_transform` | CSV / JSON Transform | Transform | `idempotent` | `1` | none | main &rarr; main |
| `date_time` | Date & Time | Transform | `idempotent` | `1` | none | main &rarr; main |
| `html_extract` | HTML Extract | Transform | `idempotent` | `1` | none | main &rarr; main |
| `item_lists` | Item Lists | Transform | `idempotent` | `1` | none | main &rarr; main |
| `markdown_text` | Markdown | Transform | `idempotent` | `1` | none | main &rarr; main |
| `rename_keys` | Rename Keys | Transform | `idempotent` | `1` | rename, copy, remove | main &rarr; main |
| `set_data` | Set / Edit Data | Transform | `idempotent` | `1` | none | main &rarr; main |
| `string_tools` | String Tools | Transform | `idempotent` | `1` | none | main &rarr; main |
| `xml_ops` | XML | Transform | `idempotent` | `1` | none | main &rarr; main |
| `chat_trigger` | Chat Trigger | Triggers | `idempotent` | `1` | none | default &rarr; main |
| `error_trigger` | Error Trigger | Triggers | `idempotent` | `1` | none | default &rarr; main |
| `form_trigger` | Form Trigger | Triggers | `idempotent` | `1` | none | default &rarr; main |
| `manual_trigger` | Manual Trigger | Triggers | `idempotent` | `1` | none | default &rarr; main |
| `salesforce_trigger` | Salesforce Event Trigger | Triggers | `idempotent` | `1` | none | default &rarr; main |
| `schedule` | Schedule Trigger | Triggers | `idempotent` | `1` | none | default &rarr; main |
| `sftp_trigger` | SFTP Trigger | Triggers | `conditionally_idempotent` | `1` | none | main &rarr; main |
| `webhook` | Webhook Trigger | Triggers | `idempotent` | `1` | none | default &rarr; main |

### Node Aliases (Backward Compatibility)

| Alias Key | Resolves To Canonical Node Type | Purpose |
|:---|:---|:---|
| `csv` | `flowsmith.data_load` | Engine and workflow import legacy compatibility |
| `csv_parser` | `flowsmith.data_load` | Engine and workflow import legacy compatibility |
| `data_load` | `flowsmith.data_load` | Engine and workflow import legacy compatibility |
| `execute_sub_workflow` | `sub_workflow` | Engine and workflow import legacy compatibility |
| `sub_workflow_trigger` | `execute_workflow_trigger` | Engine and workflow import legacy compatibility |
| `when_executed_by_another_workflow` | `execute_workflow_trigger` | Engine and workflow import legacy compatibility |

---

## 3. Connector Ecosystem (528 Registered Connectors)

Flowsmith ships with **528 fully-registered connectors** covering enterprise ERPs, CRMs, cloud providers, developer platforms, databases, AI systems, and communication channels.

### Connector Category Breakdown

| Category | Connectors Count | Examples |
|:---|:---:|:---|
| **Api** | 99 | `aggregate`, `auth_fetch`, `auth_store`, `aws_textract`, `bamboo_hr`, and 94 more |
| **Developer** | 97 | `ai_transform`, `amqp`, `amqp_trigger`, `aws_certificate_manager`, `aws_cognito`, and 92 more |
| **Communication** | 90 | `aws_ses`, `cisco_webex`, `cisco_webex_trigger`, `customer_io`, `customer_io_trigger`, and 85 more |
| **Database** | 49 | `adalo`, `airtable_trigger`, `aws_dynamo_d_b`, `azure_cosmos_db`, `azure_storage`, and 44 more |
| **Productivity** | 47 | `acuity_scheduling_trigger`, `airtable`, `airtop`, `asana`, `asana_trigger`, and 42 more |
| **Marketing** | 40 | `active_campaign`, `active_campaign_trigger`, `activecampaign`, `agile_crm`, `api_template_io`, and 35 more |
| **Crm** | 33 | `action_network`, `affinity`, `affinity_trigger`, `clearbit`, `copper_trigger`, and 28 more |
| **Finance** | 19 | `chargebee`, `chargebee_trigger`, `coin_gecko`, `e_r_p_next`, `frankfurter`, and 14 more |
| **Ai** | 14 | `ai`, `ai_agent`, `anthropic`, `embeddings`, `gemini`, and 9 more |
| **Analytics** | 14 | `google_ads`, `google_analytics`, `google_cloud_natural_language`, `google_perspective`, `human_approval`, and 9 more |
| **Logic** | 7 | `if_condition`, `loop`, `loop_over_items`, `noop`, `router`, and 2 more |
| **Transform** | 7 | `crypto_tools`, `csv`, `csv_json_transform`, `markdown_text`, `set_data`, and 2 more |
| **Storage** | 4 | `box`, `dropbox`, `google_drive`, `s3` |
| **Webhook** | 3 | `chat_trigger`, `sftp_trigger`, `webhook` |
| **Support** | 2 | `freshdesk`, `zendesk` |
| **Customer_Support** | 1 | `intercom` |
| **Devops** | 1 | `pagerduty` |
| **Schedule** | 1 | `schedule` |

### Detailed Connector Inventory (First-Party & Verified Connectors)

| Connector Key | Display Name | Category | Version | Lifecycle | Operations | Triggers | Credentials |
|:---|:---|:---:|:---:|:---:|:---:|:---:|:---:|
| `ai` | AI | ai | `1.0.0` | `stable` | 1 ops | 0 | `llm` |
| `ai_agent` | AI Agent | ai | `1.0.0` | `stable` | 1 ops | 0 | `llm` |
| `anthropic` | Anthropic Claude | ai | `1.0.0` | `stable` | 2 ops | 0 | `anthropic` |
| `embeddings` | Embeddings | ai | `1.0.0` | `stable` | 1 ops | 0 | `api_key` |
| `gemini` | Google Gemini | ai | `1.0.0` | `stable` | 3 ops | 0 | `gemini` |
| `memory` | Memory | ai | `1.0.0` | `stable` | 1 ops | 0 | `redis` |
| `message_an_agent` | Message an Agent | ai | `1.0.0` | `stable` | 1 ops | 0 | `message_an_agent_auth` |
| `open_router` | OpenRouter | ai | `1.0.0` | `beta` | 3 ops | 0 | `open_router` |
| `openai` | OpenAI | ai | `1.0.0` | `beta` | 3 ops | 0 | `openai` |
| `output_parser` | Output Parser | ai | `1.0.0` | `stable` | 1 ops | 0 | `api_key` |
| `perplexity` | Perplexity | ai | `1.0.0` | `stable` | 1 ops | 0 | `perplexity_auth` |
| `rag_pipeline` | RAG Pipeline | ai | `1.0.0` | `stable` | 1 ops | 0 | `llm` |
| `reranker` | AI Reranker | ai | `1.0.0` | `stable` | 1 ops | 0 | `api_key` |
| `text_splitter` | Text Splitter | ai | `1.0.0` | `stable` | 1 ops | 0 | `api_key` |
| `google_ads` | Google Ads | analytics | `1.0.0` | `stable` | 1 ops | 0 | `googleAdsOAuth2Api` |
| `google_analytics` | Google Analytics | analytics | `1.0.0` | `stable` | 1 ops | 0 | `google_analytics_auth` |
| `google_cloud_natural_language` | Google Cloud Natural Language | analytics | `1.0.0` | `stable` | 1 ops | 0 | `googleCloudNaturalLanguageOAuth2Api` |
| `google_perspective` | Google Perspective | analytics | `1.0.0` | `stable` | 1 ops | 0 | `googlePerspectiveOAuth2Api` |
| `human_approval` | Human Approval | analytics | `1.0.0` | `stable` | 1 ops | 0 | `api_key` |
| `humantic_ai` | Humantic AI | analytics | `1.0.0` | `stable` | 1 ops | 0 | `humanticAiApi` |
| `loop_while` | Loop While | analytics | `1.0.0` | `stable` | 1 ops | 0 | `api_key` |
| `marketstack` | Marketstack | analytics | `1.0.0` | `stable` | 3 ops | 0 | `marketstackApi` |
| `orbit` | Orbit | analytics | `1.0.0` | `stable` | 1 ops | 0 | `orbitApi` |
| `pagination` | Pagination | analytics | `1.0.0` | `stable` | 1 ops | 0 | `api_key` |
| `post_hog` | PostHog | analytics | `1.0.0` | `stable` | 1 ops | 0 | `postHogApi` |
| `profit_well` | ProfitWell | analytics | `1.0.0` | `stable` | 1 ops | 0 | `profitWellApi` |
| `security_scorecard` | SecurityScorecard | analytics | `1.0.0` | `stable` | 1 ops | 0 | `securityScorecardApi` |
| `segment` | Segment | analytics | `1.0.0` | `stable` | 3 ops | 0 | `segmentApi` |
| `aggregate` | Aggregate | api | `1.0.0` | `stable` | 1 ops | 0 | `aggregate_auth` |
| `auth_fetch` | Auth Fetch | api | `1.0.0` | `stable` | 1 ops | 0 | `api_key` |
| `auth_store` | Auth Store | api | `1.0.0` | `stable` | 1 ops | 0 | `api_key` |
| `aws_textract` | AWS Textract | api | `1.0.0` | `stable` | 1 ops | 0 | `aws_textract_auth` |
| `bamboo_hr` | BambooHr | api | `1.0.0` | `stable` | 1 ops | 0 | `bamboo_hr_auth` |
| `bitly` | Bitly | api | `1.0.0` | `stable` | 1 ops | 0 | `bitlyApi` |
| `brandfetch` | Brandfetch | api | `1.0.0` | `stable` | 1 ops | 0 | `brandfetch_auth` |
| `clockify_trigger` | Clockify Trigger | api | `1.0.0` | `stable` | 1 ops | 1 trigs | `clockifyApi` |
| `compare_datasets` | Compare Datasets | api | `1.0.0` | `stable` | 4 ops | 0 | `compare_datasets_auth` |
| `compression` | Compression | api | `1.0.0` | `stable` | 2 ops | 0 | `compression_auth` |
| `convert_to_file` | Convert to File | api | `1.0.0` | `stable` | 10 ops | 0 | `convert_to_file_auth` |
| `cron` | Cron | api | `1.0.0` | `stable` | 1 ops | 1 trigs | `cron_auth` |
| `data_table` | Data table | api | `1.0.0` | `stable` | 1 ops | 0 | `data_table_auth` |
| `date_time` | Date & Time | api | `1.0.0` | `stable` | 1 ops | 0 | `date_time_auth` |
| `deep_l` | DeepL | api | `1.0.0` | `stable` | 1 ops | 0 | `deepLApi` |
| `dhl` | DHL | api | `1.0.0` | `stable` | 1 ops | 0 | `dhlApi` |
| `e2e_test` | E2E Test | api | `1.0.0` | `stable` | 1 ops | 0 | `e2e_test_auth` |
| `e2e_test_polling_trigger` | E2E Test Polling Trigger | api | `1.0.0` | `stable` | 1 ops | 1 trigs | `e2e_test_polling_trigger_auth` |
| `execute_workflow` | Workflow Inputs | api | `1.0.0` | `stable` | 6 ops | 0 | `execute_workflow_auth` |
| `execute_workflow_trigger` | Execute Workflow Trigger | api | `1.0.0` | `stable` | 3 ops | 1 trigs | `execute_workflow_trigger_auth` |
| `extract_from_file` | Extract from File | api | `1.0.0` | `stable` | 12 ops | 0 | `extract_from_file_auth` |
| `figma_trigger` | Figma Trigger (Beta) | api | `1.0.0` | `stable` | 5 ops | 1 trigs | `figmaOAuth2Api` |
| `file_io` | File I/O | api | `1.0.0` | `stable` | 1 ops | 0 | `api_key` |
| `filter` | Filter | api | `1.0.0` | `stable` | 1 ops | 0 | `filter_auth` |
| `form` | Limit Wait Time | api | `1.0.0` | `stable` | 4 ops | 0 | `form_auth` |
| `form_trigger` | n8n Form Trigger | api | `1.0.0` | `stable` | 1 ops | 1 trigs | `form_trigger_auth` |
| `ftp` | Timeout | api | `1.0.0` | `stable` | 5 ops | 0 | `ftp` |
| `g_suite_admin` | Google Workspace Admin | api | `1.0.0` | `stable` | 1 ops | 0 | `gSuiteAdminOAuth2Api` |
| `git` | Git | api | `1.0.0` | `stable` | 15 ops | 0 | `gitPassword` |
| `google_books` | Google Books | api | `1.0.0` | `stable` | 6 ops | 0 | `googleApi` |
| `google_contacts` | Google Contacts | api | `1.0.0` | `stable` | 1 ops | 0 | `googleContactsOAuth2Api` |
| `google_translate` | Google Translate | api | `1.0.0` | `stable` | 1 ops | 0 | `googleApi` |
| `graphql` | GraphQL | api | `1.0.0` | `stable` | 1 ops | 0 | `http` |
| `home_assistant` | Home Assistant | api | `1.0.0` | `stable` | 1 ops | 0 | `homeAssistantApi` |
| `html` | Extraction Values | api | `1.0.0` | `stable` | 3 ops | 0 | `html_auth` |
| `html_extract` | HTML Extract | api | `1.0.0` | `stable` | 4 ops | 0 | `html_extract_auth` |
| `http` | Universal HTTP Connector | api | `2.0.0` | `stable` | 8 ops | 0 | `http` |
| `i_calendar` | iCalendar | api | `1.0.0` | `stable` | 1 ops | 0 | `i_calendar_auth` |
| `if` | If | api | `1.0.0` | `stable` | 1 ops | 0 | `if_auth` |
| `interval` | Interval | api | `1.0.0` | `stable` | 1 ops | 1 trigs | `interval_auth` |
| `item_lists` | Item Lists | api | `1.0.0` | `stable` | 1 ops | 0 | `item_lists_auth` |
| `jina_ai` | Jina AI | api | `1.0.0` | `stable` | 3 ops | 0 | `jinaAiApi` |
| `limit` | Limit | api | `1.0.0` | `stable` | 1 ops | 0 | `limit_auth` |
| `lingva_nex` | LingvaNex | api | `1.0.0` | `stable` | 1 ops | 0 | `lingvaNexApi` |
| `local_file_trigger` | Local File Trigger | api | `1.0.0` | `stable` | 7 ops | 1 trigs | `local_file_trigger_auth` |
| `mailcheck` | Mailcheck | api | `1.0.0` | `stable` | 1 ops | 0 | `mailcheckApi` |
| `manual_trigger` | Manual Trigger | api | `1.0.0` | `stable` | 1 ops | 1 trigs | `manual_trigger_auth` |
| `markdown` | Markdown | api | `1.0.0` | `stable` | 2 ops | 0 | `markdown_auth` |
| `merge` | Merge | api | `1.0.0` | `stable` | 1 ops | 0 | `merge_auth` |
| `mindee` | Mindee | api | `1.0.0` | `stable` | 1 ops | 0 | `mindeeInvoiceApi` |
| `mistral_ai` | Mistral AI | api | `1.0.0` | `stable` | 1 ops | 0 | `mistralCloudApi` |
| `move_binary_data` | Convert to/from binary data | api | `1.0.0` | `stable` | 2 ops | 0 | `move_binary_data_auth` |
| `n8n_trigger` | n8n Trigger | api | `1.0.0` | `stable` | 3 ops | 1 trigs | `n8n_trigger_auth` |
| `nasa` | NASA | api | `1.0.0` | `stable` | 2 ops | 0 | `nasaApi` |
| `no_op` | No Operation, do nothing | api | `1.0.0` | `stable` | 1 ops | 0 | `no_op_auth` |
| `one_simple_api` | One Simple API | api | `1.0.0` | `stable` | 10 ops | 0 | `oneSimpleApi` |
| `onfleet` | Onfleet | api | `1.0.0` | `stable` | 1 ops | 0 | `onfleetApi` |
| `onfleet_trigger` | Onfleet Trigger | api | `1.0.0` | `stable` | 1 ops | 1 trigs | `onfleetApi` |
| `open_ai` | OpenAI | api | `1.0.0` | `stable` | 1 ops | 0 | `openAiApi` |
| `open_thesaurus` | OpenThesaurus | api | `1.0.0` | `stable` | 1 ops | 0 | `open_thesaurus_auth` |
| `open_weather_map` | OpenWeatherMap | api | `1.0.0` | `stable` | 5 ops | 0 | `openWeatherMapApi` |
| `philips_hue` | Philips Hue | api | `1.0.0` | `stable` | 1 ops | 0 | `philipsHueOAuth2Api` |
| `rabbitmq` | RabbitMQ | api | `1.0.0` | `stable` | 3 ops | 0 | `rabbitmq` |
| `read_binary_file` | Read Binary File | api | `1.0.0` | `stable` | 1 ops | 0 | `read_binary_file_auth` |
| `read_binary_files` | Read Binary Files | api | `1.0.0` | `stable` | 1 ops | 0 | `read_binary_files_auth` |
| `read_p_d_f` | Read PDF | api | `1.0.0` | `stable` | 1 ops | 0 | `read_p_d_f_auth` |
| `read_write_file` | Read/Write Files from Disk | api | `1.0.0` | `stable` | 2 ops | 0 | `read_write_file_auth` |
| `remove_duplicates` | Remove Duplicates | api | `1.0.0` | `stable` | 1 ops | 0 | `remove_duplicates_auth` |
| `rename_keys` | Rename Keys | api | `1.0.0` | `stable` | 3 ops | 0 | `rename_keys_auth` |
| `respond_to_webhook` | Respond With | api | `1.0.0` | `stable` | 10 ops | 0 | `jwtAuth` |
| `rss_feed` | RSS Feed | api | `1.0.0` | `stable` | 1 ops | 0 | `api_key` |
| `rss_feed_read` | RSS Read | api | `1.0.0` | `stable` | 1 ops | 0 | `rss_feed_read_auth` |

*(Complete list of all 528 connectors is preserved in `backend/app/connectors/registry.py` and queryable via `GET /api/connectors`)*

---

## 4. LLM & AI Platform Inventory (188 Providers)

The centralized LLM Provider Registry (`app.ai.llm_registry`) supports **188 AI providers** spanning commercial hyperscalers, open-weights inference clouds, regional gateways, and local offline models.

| Provider ID | Display Name | Category | Auth Type | Static Models | Regional Variants |
|:---|:---|:---:|:---:|:---:|:---:|
| `302_ai` | 302.AI | Aggregators | `api_key` | 0 | 0 |
| `abacus` | Abacus | Enterprise AI | `api_key` | 0 | 0 |
| `abliteration_ai` | abliteration.ai | Inference Providers | `api_key` | 0 | 0 |
| `above_dev` | above.dev | Inference Providers | `api_key` | 0 | 0 |
| `agentrouter` | AgentRouter | LLM Gateways | `api_key` | 0 | 0 |
| `agnes_ai` | Agnes AI | Enterprise AI | `api_key` | 0 | 0 |
| `ai21_labs` | AI21 Labs | Aggregators | `api_key` | 0 | 0 |
| `ai_and` | ai& | Inference Providers | `api_key` | 0 | 0 |
| `ai_router` | AI-ROUTER | LLM Gateways | `api_key` | 0 | 0 |
| `aihubmix` | AIHubMix | Aggregators | `api_key` | 0 | 0 |
| `ainetface` | ainetface | Inference Providers | `api_key` | 0 | 0 |
| `aixy` | Aixy | Inference Providers | `api_key` | 0 | 0 |
| `aki_io` | AKI.IO | Compute Providers | `api_key` | 0 | 0 |
| `alibaba` | Alibaba | Regional Providers | `api_key` | 4 | 6 |
| `ambient` | Ambient | Compute Providers | `api_key` | 0 | 0 |
| `amd` | AMD | Compute Providers | `api_key` | 0 | 0 |
| `anthropic` | Anthropic (API key) | Major Providers | `api_key` | 4 | 0 |
| `anyapi` | AnyAPI | Inference Providers | `api_key` | 0 | 0 |
| `arcee` | Arcee | Inference Providers | `api_key` | 0 | 0 |
| `atomic_chat` | Atomic Chat | Enterprise AI | `api_key` | 0 | 0 |
| `auriko` | Auriko | Enterprise AI | `api_key` | 0 | 0 |
| `azure` | Azure | Cloud Providers | `api_key` | 0 | 0 |
| `azure_cognitive_services` | Azure Cognitive Services | Cloud Providers | `api_key` | 0 | 0 |
| `bailing` | Bailing | Regional Providers | `api_key` | 0 | 0 |
| `baseten` | Baseten | Inference Providers | `api_key` | 0 | 0 |
| `bedrock` | Amazon Bedrock | Cloud Providers | `aws_sigv4` | 3 | 0 |
| `bee_by_heosst` | Bee by HEOSST | Enterprise AI | `api_key` | 0 | 0 |
| `berget_ai` | Berget AI | Regional Providers | `api_key` | 0 | 0 |
| `blue_claw` | Blue Claw | Inference Providers | `api_key` | 0 | 0 |
| `bothub` | Bothub | Aggregators | `api_key` | 0 | 0 |
| `cerebras` | Cerebras | Inference Providers | `api_key` | 2 | 0 |
| `charm_hyper` | Charm Hyper | Inference Providers | `api_key` | 0 | 0 |
| `chutes` | Chutes | Inference Providers | `api_key` | 0 | 0 |
| `clarifai` | Clarifai | Aggregators | `api_key` | 0 | 0 |
| `claudinio` | Claudinio | Inference Providers | `api_key` | 0 | 0 |
| `custom` | Other Custom provider | Custom | `api_key` | 0 | 0 |
| `daoxe` | DaoXE | Regional Providers | `api_key` | 0 | 0 |
| `databricks` | Databricks | Cloud Providers | `bearer_token` | 0 | 0 |
| `deep_infra` | Deep Infra | Inference Providers | `api_key` | 0 | 0 |
| `deepseek` | DeepSeek | Major Providers | `api_key` | 2 | 0 |

*(Remaining 148 providers listed in `app/ai/llm_registry.py`)*

---

## 5. API Route Inventory (200 Paths / 244 Operations)

| Tag / Group | Operation Count | Endpoint Samples |
|:---|:---:|:---|
| **untagged** | 41 | `GET /api/apikeys`, `POST /api/apikeys`, `DELETE /api/apikeys/{key_id}` |
| **ai** | 27 | `POST /api/ai/auto-fix`, `GET /api/ai/capabilities`, `POST /api/ai/chat` |
| **workflows** | 24 | `GET /api/workflows`, `POST /api/workflows`, `POST /api/workflows/import` |
| **credentials** | 19 | `GET /api/credentials`, `POST /api/credentials`, `GET /api/credentials/auth-metadata` |
| **executions** | 19 | `GET /api/executions`, `GET /api/executions/export`, `GET /api/executions/universal-search` |
| **data-tables** | 17 | `GET /api/data-tables`, `POST /api/data-tables`, `DELETE /api/data-tables/{table_id}` |
| **auth** | 13 | `POST /api/auth/forgot-password`, `POST /api/auth/login`, `POST /api/auth/logout` |
| **connectors** | 10 | `GET /api/connectors`, `POST /api/connectors/import-openapi`, `POST /api/connectors/preview-openapi` |
| **rag** | 9 | `GET /api/rag/collections`, `POST /api/rag/collections`, `DELETE /api/rag/collections/{collection_id}` |
| **notifications** | 8 | `GET /api/notifications`, `GET /api/notifications/preferences`, `PUT /api/notifications/preferences` |
| **files** | 7 | `GET /api/files`, `POST /api/files`, `DELETE /api/files/{file_id}` |
| **integrations** | 6 | `GET /api/integrations/canonical-nodes`, `GET /api/integrations/catalog`, `GET /api/integrations/catalog/{integration_id}` |
| **llm** | 6 | `GET /api/llm/credentials/{credential_id}/models`, `POST /api/llm/credentials/{credential_id}/refresh-models`, `POST /api/llm/discover-models` |
| **webhooks** | 6 | `GET /api/webhooks/chat/{slug}`, `POST /api/webhooks/chat/{slug}`, `GET /api/webhooks/deliveries` |
| **workflow-tests** | 6 | `GET /api/workflows/{workflow_id}/tests`, `POST /api/workflows/{workflow_id}/tests`, `DELETE /api/workflows/{workflow_id}/tests/{test_id}` |
| **monitoring** | 5 | `GET /api/monitoring/dlq`, `POST /api/monitoring/dlq/{execution_id}/retry`, `GET /api/monitoring/metrics` |
| **sso** | 3 | `GET /api/auth/sso/providers`, `GET /api/auth/sso/{provider}/callback`, `GET /api/auth/sso/{provider}/login` |
| **branding** | 3 | `GET /api/branding`, `PUT /api/branding`, `POST /api/branding/reset` |
| **health** | 3 | `GET /api/health`, `GET /api/readyz`, `GET /readyz` |
| **nodes** | 3 | `GET /api/nodes`, `GET /api/nodes/{node_type}/parameters`, `GET /api/nodes/{node_type}/schema` |
| **oauth** | 2 | `GET /api/auth/{provider}/callback`, `POST /api/auth/{provider}/connect` |
| **users** | 2 | `GET /api/users`, `PATCH /api/users/{user_id}` |
| **admin** | 1 | `POST /api/admin/maintenance/prune` |
| **audit** | 1 | `GET /api/audit` |
| **metrics** | 1 | `GET /api/metrics` |
| **code** | 1 | `POST /api/nodes/code/validate` |
| **salesforce-triggers** | 1 | `POST /api/triggers/salesforce/{path}` |
| **workflow-api** | 1 | `POST /api/w/{workflow_id}/execute` |

---

## 6. Frontend Pages & Routes Inventory (26 Pages)

| Page Component | Route Path | Bundle Mode | Primary Function |
|:---|:---|:---:|:---|
| `OverviewPage.jsx` | `/overview` | Eager | Dashboard, execution summary, quick start |
| `WorkflowsPage.jsx` | `/workflows` | Eager | Workflow list, filter, create, duplicate, delete |
| `WorkflowEditorPage.jsx` | `/workflows/:id` | Lazy | Visual React Flow canvas, node configuration, live run |
| `IntegrationsPage.jsx` | `/integrations` | Lazy | Connector ecosystem catalog, status, documentation |
| `CredentialsPage.jsx` | `/credentials` | Lazy | Secure credential store, OAuth handshakes, test connections |
| `ExecutionsPage.jsx` | `/executions` | Lazy | Historical execution search, filtering, CSV export |
| `ExecutionDetailPage.jsx` | `/executions/:id` | Lazy | Step trace, timeline, input/output inspection, live logs |
| `TemplatesPage.jsx` | `/templates` | Lazy | Pre-built workflow template gallery |
| `VariablesPage.jsx` | `/variables` | Lazy | Global environment variables and scoped secrets |
| `DataTablesPage.jsx` | `/data-tables` | Lazy | Relational data tables index and table management |
| `DataTableEditorPage.jsx` | `/data-tables/:tableId` | Lazy | Grid editor, column schema management, row filtering |
| `KnowledgePage.jsx` | `/knowledge` | Lazy | RAG knowledge base collections, document upload, chunking |
| `ApprovalsPage.jsx` | `/approvals` | Lazy | Human-in-the-loop pending approval requests |
| `SharedPage.jsx` | `/shared` | Lazy | Shared workflows across organization workspaces |
| `MonitoringPage.jsx` | `/monitoring` | Lazy | Dead-letter queue, retry policies, telemetry, system metrics |
| `AIPage.jsx` | `/ai` | Lazy | AI Workflow Builder console, agent chat, prompt-to-workflow |
| `SettingsPage.jsx` | `/settings` | Lazy | Organization settings, branding, audit logs, members |
| `HelpPage.jsx` | `/help` | Lazy | In-app documentation and keyboard shortcuts |
| `OAuthCallbackPage.jsx` | `/oauth/callback` | Eager | OAuth2 popup postMessage handoff listener |
| `FormFillPage.jsx` | `/forms/:slug` | Lazy | Public standalone form trigger submission view |
| `ChatPage.jsx` | `/chat/:slug` | Lazy | Public interactive AI agent chat interface |
