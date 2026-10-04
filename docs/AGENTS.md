# Flowsmith — Autonomous AI Agents & RAG Architecture

> **Module**: AI Engine & Agent Runtime  
> **Supported Providers**: OpenAI, Anthropic, Google Gemini, DeepSeek, Groq, Ollama  
> **Loop Paradigm**: Autonomous ReAct (Reasoning + Acting)  
> **Protocols**: Model Context Protocol (MCP) & OpenAI Function Calling  

---

## 1. Overview of Autonomous Agents in Flowsmith

Flowsmith embeds a first-class, sovereign AI agent runtime directly inside its workflow canvas. Unlike static "call-and-response" prompt nodes, the **AI Agent Node (`AIAgentNode`)** is an autonomous reasoning engine that:
1. Receives complex enterprise objectives.
2. Dynamically decides which tools to invoke (database queries, CRM operations, calculator, HTTP lookups).
3. Executes tools, observes results, and iteratively refines its reasoning path.
4. Maintains conversation context across steps using a **Tri-Tier Memory** architecture.
5. Communicates with external agent ecosystems via the **Model Context Protocol (MCP)**.

```mermaid
graph TD
    UserGoal[User Goal / Incoming Payload] --> AgentInit[Agent Node Initializes Context]
    AgentInit --> LoadMemory[Retrieve Tri-Tier Memory]
    LoadMemory --> PromptAssembly[Assemble System Prompt + Tools Spec]
    PromptAssembly --> LLMCall[Call LLM Gateway (OpenAI/Anthropic/Gemini/Ollama)]
    LLMCall --> Decision{Did LLM Request Tool Call?}
    Decision -->|Yes (Tool Call)| ExecuteTool[Execute Tool via Local Registry or MCP]
    ExecuteTool --> StoreObservation[Store Observation in Working Memory]
    StoreObservation --> LoopCheck{Max Iterations Reached?}
    LoopCheck -->|No| PromptAssembly
    LoopCheck -->|Yes| ForceFinal[Synthesize Best Available Answer]
    Decision -->|No (Final Answer)| ExtractAnswer[Extract & Format Final Output]
    ExtractAnswer --> PersistMemory[Update Episodic Vector Memory in pgvector]
    PersistMemory --> NextNode[Pass Output to Next Workflow Node]
```

---

## 2. Multi-Provider LLM Gateway

Flowsmith provides a unified abstraction over commercial and self-hosted model providers in `backend/app/ai/providers.py`. Workflows can switch between cloud and on-premise models without altering agent tool definitions:

| Provider | Supported Models | Primary Use Case | Authentication |
| :--- | :--- | :--- | :--- |
| **Builtin (Zero-LLM)** | Deterministic ReAct, Rule Engine | 100% Offline, sovereign zero-dependency reasoning, instant fallback, air-gapped test harnesses | None (Built-in) |
| **OpenAI** | GPT-4o, GPT-4o-mini, o1, o3-mini | High-complexity reasoning & broad tool calling | API Key (`OPENAI_API_KEY`) |
| **Anthropic** | Claude 3.5 Sonnet, Claude 3.5 Haiku | Deep analytical tasks, long documents, coding | API Key (`ANTHROPIC_API_KEY`) |
| **Google Gemini** | Gemini 1.5 Pro, Gemini 1.5 Flash | Massive context window (up to 2M tokens) & multimodal | API Key (`GEMINI_API_KEY`) |
| **DeepSeek** | DeepSeek V3, DeepSeek R1 | High-efficiency open-weight reasoning | API Key (`DEEPSEEK_API_KEY`) |
| **Groq** | Llama 3.3 70B, Mixtral 8x7B | Ultra-low latency tool-calling loops (< 200ms) | API Key (`GROQ_API_KEY`) |
| **Ollama** | Llama 3.1, Mistral, Qwen 2.5 | 100% Offline, on-premise sovereign execution | Local endpoint (`http://localhost:11434`) |

---

## 3. Complete Multi-Tier Cognitive Memory Architecture

To balance execution speed, token budget constraints, deterministic zero-LLM operation, and long-term historical awareness, Flowsmith implements a **Complete Multi-Tier Cognitive Memory** model (`backend/app/ai/memory.py`):

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                 COMPLETE MULTI-TIER COGNITIVE MEMORY SYSTEM                 │
├──────────────────────┬──────────────────────────────────────────────────────┤
│ Tier 1: Working      │ Ephemeral in-memory execution trace during active    │
│ Memory               │ run. Records Thoughts, Tool Actions, & Observations. │
├──────────────────────┼──────────────────────────────────────────────────────┤
│ Tier 2: Summary      │ Rolling conversational summary buffer. Condenses     │
│ Buffer Memory        │ dialogue turns via LLM or deterministic extractive   │
│                      │ fallback when token/character limit is reached.      │
├──────────────────────┼──────────────────────────────────────────────────────┤
│ Tier 3: Episodic     │ Semantic & lexical memory store. Uses PostgreSQL     │
│ Vector/Lexical Memory│ `pgvector` embeddings or zero-embedding BM25/TF-IDF  │
│                      │ token & n-gram similarity scoring.                   │
├──────────────────────┼──────────────────────────────────────────────────────┤
│ Tier 4: Structured   │ Key-value and relation knowledge graph store for     │
│ Entity Memory        │ user profiles, extracted facts, preferences, dates.  │
├──────────────────────┼──────────────────────────────────────────────────────┤
│ Tier 5: Scratchpad   │ Tag-indexed volatile key-value workspace for task    │
│ Memory               │ sub-plans, intermediate calculations, & checkpoints. │
├──────────────────────┼──────────────────────────────────────────────────────┤
│ Tier 6: Full Buffer  │ Lossless chronological history log preserving exact  │
│ Memory               │ raw messages across entire agent conversational life.│
├──────────────────────┼──────────────────────────────────────────────────────┤
│ Persistence Layer    │ `SessionMemoryManager` with atomic JSON serialization│
│                      │ into `.runtime/ai_memory/{session}.json`.            │
└──────────────────────┴──────────────────────────────────────────────────────┘
```

### 3.1 Tier 1: Working Memory (`WorkingMemory`)
* Lives in memory for the duration of a single node execution pass.
* Records each iteration's `Thought`, `Action`, and `Observation`.
* Automatically cleared once the final answer is generated, with key outputs propagated to higher tiers.

### 3.2 Tier 2: Summary Buffer Memory (`SummaryBufferMemory`)
* Maintains recent messages verbatim.
* When the total character/token count exceeds the configured limit (e.g. 4,000 tokens), older messages are condensed.
* Includes an **autonomous deterministic extractive fallback**: if no external LLM is available, it mathematically clusters and condenses conversational key phrases without dropping factual context.

### 3.3 Tier 3: Episodic Vector & Lexical Memory (`EpisodicVectorMemory`)
* Dual-mode semantic search:
  * **Vector Mode**: Integrates with PostgreSQL 16 `pgvector` using HNSW cosine similarity indices.
  * **Zero-Embedding Lexical Mode**: Provides BM25 / TF-IDF token and n-gram overlap scoring, functioning 100% offline without requiring vector database infrastructure or embedding models.
* Retrieves relevant historical solutions and injects them directly into the reasoning context window.

### 3.4 Tier 4: Structured Entity Memory (`EntityMemory`)
* Maintains entity-attribute graphs (e.g., `user.preferred_currency = USD`, `order.last_id = 9812`).
* Supports structured fact upsertion, retrieval by key or prefix, and automatic entity extraction from conversations.

### 3.5 Tier 5: Scratchpad Memory (`ScratchpadMemory`)
* Volatile, tagged computational workspace for complex multi-step reasoning.
* Allows nodes and agent loops to store intermediate hypotheses, sub-task statuses, and computational checkpoints tagged by category.

### 3.6 Tier 6: Full Buffer Memory (`FullBufferMemory`)
* Lossless dialogue archive storing raw user, assistant, system, and tool messages in chronological order.
* Provides complete conversational playback and audit trails for compliance.

### 3.7 Unified Management & Disk Persistence (`SessionMemoryManager`)
* `CompleteMemory` unifies all 6 tiers behind a single coherent API (`add_user_message`, `add_ai_message`, `get_context`, `search_episodes`, `set_entity`, `set_note`).
* Managed sessions are automatically loaded from and saved to `.runtime/ai_memory/{session_id}.json` across server restarts.

---

## 4. The Autonomous ReAct Loop (`AIAgentNode`)

The core execution loop of `AIAgentNode` operates according to the ReAct framework:

### 4.1 Step-by-Step Lifecycle
1. **Context Initialization**: The agent receives input data from upstream workflow nodes (e.g. customer support email, webhook payload).
2. **System Prompt Formulation**: Base persona instructions are combined with:
   * Dynamic tool schemas formatted according to OpenAI function calling specifications.
   * Relevant memories retrieved from Tier 2 and Tier 3 stores.
   * Execution constraints (max iterations, timeout, temperature).
3. **Reasoning & Tool Selection**: The LLM outputs an internal thought and issues one or more tool calls.
4. **Tool Execution**: Flowsmith's engine validates tool parameters against their Pydantic schemas and executes the tool locally.
5. **Observation Ingestion**: Tool results are appended to the working memory buffer as an `Observation`.
6. **Iterative Refinement**: Steps 3–5 repeat until the model determines that sufficient information has been gathered to produce the final answer.
7. **Final Answer Extraction**: Flowsmith employs resilient parsing strategies to extract clean output:
   * Strategy A: `<final_answer>...</final_answer>` XML tags.
   * Strategy B: Markdown fenced JSON blocks (` ```json ... ``` `).
   * Strategy C: Fallback to the raw trailing text response if structured tags are omitted.

### 4.2 Loop Safeguards
* **Max Iterations Cap**: Default: 10 iterations. Prevents infinite reasoning loops if an external API produces unexpected errors.
* **Execution Timeout**: Default: 120 seconds. Handled at the `asyncio` task level.
* **Single-Flight Tool Execution**: Rejects duplicate identical tool calls in the same iteration to prevent API thrashing.

---

## 5. Dynamic Tool Registry

Flowsmith provides an extensible tool registry (`backend/app/ai/tools.py`) where tools are defined as typed Python callables with Pydantic parameter schemas:

```python
@tool(
    name="calculator",
    description="Perform mathematical calculations. Input must be a valid expression string.",
)
def calculator_tool(expression: str) -> str:
    # Sandboxed arithmetic evaluation
    ...
```

### 5.1 Built-in System Tools
* **Calculator**: Safe arithmetic and statistical evaluations.
* **Current Time**: Real-time UTC and timezone conversions.
* **Human Approval Gate**: Suspends the agent loop and dispatches an interactive approval request to a human operator before proceeding with sensitive actions (e.g. issuing a refund, modifying a database).
* **HTTP Universal Request**: Allows the agent to issue scoped GET/POST requests against external REST APIs subject to SSRF filtering.
* **Data Table Query**: Enables the agent to query, filter, and aggregate records from Flowsmith's embedded relational Data Tables.

### 5.2 Converting Workflows into Tools
Any Flowsmith sub-workflow can be exposed as an agent tool. The sub-workflow's input parameters automatically generate the tool's JSON schema, allowing agents to trigger complex multi-system orchestrations as a single action.

---

## 6. Model Context Protocol (MCP) Integration

Flowsmith natively implements Anthropic’s open **Model Context Protocol (MCP)** specification:

```
┌────────────────────┐     MCP Protocol (JSON-RPC)     ┌────────────────────┐
│ Flowsmith Agent    │ ◄─────────────────────────────► │ External MCP Server│
│ Node (MCP Client)  │   - Tools Discovery (tools/list)│ (e.g. GitHub MCP,  │
│                    │   - Tool Invocation (tools/call)│  Filesystem MCP,   │
│                    │   - Context Resources           │  Database MCP)     │
└────────────────────┘                                 └────────────────────┘
```

1. **Transports**: Supports both standard I/O (`stdio`) child process communication and Server-Sent Events (`SSE`) over HTTP.
2. **Dynamic Discovery**: On workflow initialization, Flowsmith queries configured MCP servers via `tools/list` and registers their operations directly into the agent's available tool palette.
3. **Secure Execution**: All MCP tool calls are mediated and logged by Flowsmith's execution engine, ensuring full auditability.

---

## 7. Configuration & Canvas User Experience

Inside the visual workflow editor, the **AI Agent Node Editor** provides dedicated controls:
* **Provider & Model Selector**: Searchable dropdown displaying cloud models (GPT-4o, Claude 3.5, Gemini 1.5), local models (Ollama), or the native **Builtin Zero-LLM** provider.
* **System Prompt Template**: Multi-line Monaco editor with auto-completion for workflow variables (`{{ $node["id"].json.field }}`).
* **Tools Checklist**: Interactive toggles for enabling/disabling specific tools from the local registry or connected MCP servers.
* **Memory Type Selector**: Select from `complete` (all 6 cognitive tiers active), `window` (short-term rolling messages), `summary` (compressed buffer), `episodic` (vector/lexical lookup), `entity` (facts graph), `scratchpad` (notes & checkpoints), or `none` (stateless execution).
* **Allow Builtin Fallback (`allow_builtin_fallback`)**: Resilient boolean switch that automatically cascades execution to the local zero-LLM reasoning engine if cloud credentials are absent, rate-limited, or network unreachable.
* **Session ID (`session_id`)**: Dynamic identifier binding interactions to long-term memory sessions persisted under `.runtime/ai_memory/`.
* **Memory Depth Slider**: Configurable sliding window size for conversation history.
* **Temperature & Top-P Controls**: Fine-grained sliders for tuning output creativity vs. deterministic precision.

---

## 8. Autonomous Zero-LLM Local Intelligence Engine (`BuiltinProvider`)

Flowsmith includes an enterprise-grade, fully sovereign **Autonomous Zero-LLM Local Intelligence Engine** (`backend/app/ai/providers/builtin_provider.py`). This engine allows AI agent workflows to execute completely without internet access, third-party API keys, or heavy GPU/LLM infrastructure.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                 AUTONOMOUS ZERO-LLM LOCAL INTELLIGENCE ENGINE               │
├─────────────────────────────────────────────────────────────────────────────┤
│ 1. Intent & Goal Parser    │ Extracts objectives, mathematical expressions, │
│                            │ entities, and context from structured input.   │
├────────────────────────────┼────────────────────────────────────────────────┤
│ 2. Deterministic ReAct     │ Synthesizes structured Thought, Action, and    │
│    Reasoning Loop          │ Action Input blocks according to agent tools.  │
├────────────────────────────┼────────────────────────────────────────────────┤
│ 3. Tool Dispatch Engine    │ Invokes registered tools (calculator, time,    │
│                            │ search, custom connectors) with schema guards. │
├────────────────────────────┼────────────────────────────────────────────────┤
│ 4. Observation Feedback    │ Feeds tool results into cognitive memory tiers │
│    & Context Synthesis     │ and updates scratchpad and entity stores.      │
├────────────────────────────┼────────────────────────────────────────────────┤
│ 5. Structured Final Answer │ Formats `<final_answer>` or JSON payload with  │
│    Generation              │ strict typing and deterministic consistency.   │
└────────────────────────────┴────────────────────────────────────────────────┘
```

### 8.1 Key Capabilities
* **100% Offline & Air-Gapped**: Runs inside high-security banking, healthcare, and defence environments where external network calls are prohibited.
* **Instant Fallback**: Can be configured as a failover backend for commercial LLMs when external providers experience outages or 429 rate limits.
* **Strict Tool Dispatching**: Understands tool signatures, parses arguments safely, runs execution pipelines, and summarizes observations without hallucinatory loops.
* **Zero Cost & Zero Cold Start**: Zero per-token operational cost, instant response time (< 5ms), and zero local memory footprint compared to multi-gigabyte neural models.
