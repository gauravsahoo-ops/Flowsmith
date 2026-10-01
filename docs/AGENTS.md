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
| **OpenAI** | GPT-4o, GPT-4o-mini, o1, o3-mini | High-complexity reasoning & broad tool calling | API Key (`OPENAI_API_KEY`) |
| **Anthropic** | Claude 3.5 Sonnet, Claude 3.5 Haiku | Deep analytical tasks, long documents, coding | API Key (`ANTHROPIC_API_KEY`) |
| **Google Gemini** | Gemini 1.5 Pro, Gemini 1.5 Flash | Massive context window (up to 2M tokens) & multimodal | API Key (`GEMINI_API_KEY`) |
| **DeepSeek** | DeepSeek V3, DeepSeek R1 | High-efficiency open-weight reasoning | API Key (`DEEPSEEK_API_KEY`) |
| **Groq** | Llama 3.3 70B, Mixtral 8x7B | Ultra-low latency tool-calling loops (< 200ms) | API Key (`GROQ_API_KEY`) |
| **Ollama** | Llama 3.1, Mistral, Qwen 2.5 | 100% Offline, on-premise sovereign execution | Local endpoint (`http://localhost:11434`) |

---

## 3. Tri-Tier Memory Architecture

To balance execution speed, token budget constraints, and long-term historical awareness, Flowsmith implements a **Tri-Tier Memory** model:

```
┌─────────────────────────────────────────────────────────────┐
│                    TRI-TIER AGENT MEMORY                    │
├───────────────────┬─────────────────────────────────────────┤
│ Tier 1: Working   │ In-memory scratchpad during active run. │
│ Memory            │ Holds thoughts, tool inputs & outputs.  │
├───────────────────┼─────────────────────────────────────────┤
│ Tier 2: Summary   │ Rolling conversational context window.  │
│ Buffer Memory     │ Condenses past turns once token budget  │
│                   │ threshold (e.g. 4,000 tokens) is met.   │
├───────────────────┼─────────────────────────────────────────┤
│ Tier 3: Episodic  │ Long-term semantic knowledge in         │
│ Vector Memory     │ PostgreSQL `pgvector`. Retrieves past   │
│                   │ executions via cosine similarity.       │
└───────────────────┴─────────────────────────────────────────┘
```

### 3.1 Tier 1: Working Memory (`WorkingMemory`)
* Lives in memory for the duration of a single node execution pass.
* Records each iteration's `Thought`, `Action`, and `Observation`.
* Automatically cleared once the final answer is generated.

### 3.2 Tier 2: Summary Buffer Memory (`SummaryBufferMemory`)
* Maintains recent messages verbatim.
* When the total character/token count exceeds the configured limit, the agent triggers an asynchronous background condensation prompt that compresses older turns into an executive summary.

### 3.3 Tier 3: Episodic Vector Memory (`EpisodicVectorMemory`)
* Backed by PostgreSQL 16 `pgvector`.
* When an agent resolves a customer inquiry, debugs an incident, or classifies an anomaly, the final summary is vectorized and stored in `vector_embeddings`.
* On subsequent runs, the agent executes an HNSW vector search (`<->` cosine distance) to inject relevant past solutions directly into the context window.

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
* **Provider & Model Selector**: Searchable dropdown displaying model latency profiles and context limits.
* **System Prompt Template**: Multi-line Monaco editor with auto-completion for workflow variables (`{{ $node["id"].json.field }}`).
* **Tools Checklist**: Interactive toggles for enabling/disabling specific tools from the local registry or connected MCP servers.
* **Memory Depth Slider**: Configurable sliding window size for conversation history.
* **Temperature & Top-P Controls**: Fine-grained sliders for tuning output creativity vs. deterministic precision.
