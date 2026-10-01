# Flowsmith — Code Style & Engineering Guidelines

> **Target Standard**: Clean, Idiomatic, Production-Grade Architecture  
> **Backend**: Python 3.12 / FastAPI / Pydantic v2 / SQLAlchemy 2.0  
> **Frontend**: React 19 / Vite 8 / Zustand / Vanilla CSS Tokens (Obsidian Glass)  
> **Linter Policy**: Zero Warnings, Zero Errors (`oxlint`, `ruff`, `pytest`)  

---

## 1. Engineering Philosophy

1. **Explicit Over Implicit**: Always favor readable, strongly typed code over clever metaprogramming or dynamic monkey-patching.
2. **Deterministic & Testable**: Design every function, service, and node handler to be isolated and testable without side-effects.
3. **Zero-Warning Tolerance**: Code that emits compiler, linter, or test warnings is considered broken and must not be merged.
4. **Preserve System Boundaries**: Never mix frontend state with backend logic; never bypass the encrypted credential vault.

---

## 2. Python Backend Standards

### 2.1 Typing & Modern Syntax (Python 3.12+)
* **Mandatory Future Annotations**: Include `from __future__ import annotations` at the top of all Python files.
* **Native Type Hinting**: Use native collection types (`dict[str, Any]`, `list[str]`, `set[int]`, `tuple[str, ...]`) instead of importing from `typing`.
* **Union Operators**: Use the pipe operator `|` for optional and union types (e.g. `str | None`, `int | float`) instead of `Optional` or `Union`.
* **Example**:
  ```python
  from __future__ import annotations

  from dataclasses import dataclass
  from typing import Any

  @dataclass(slots=True)
  class NodeExecutionRecord:
      node_id: str
      status: str
      duration_ms: float
      output_payload: dict[str, Any] | None = None
  ```

### 2.2 Pydantic v2 Schemas
* Use Pydantic models for all API requests, responses, and connector configurations.
* Declare clear field validations and explicit defaults:
  ```python
  from pydantic import BaseModel, Field

  class WorkflowCreateRequest(BaseModel):
      name: str = Field(..., min_length=1, max_length=120, description="Workflow display title")
      data: dict[str, Any] = Field(default_factory=dict, description="Canvas graph schema")
      active: bool = Field(default=False, description="Whether workflow triggers are active")
  ```

### 2.3 SQLAlchemy 2.0 ORM Idioms
* Use 2.0-style `select()`, `update()`, and `delete()` statements; never use legacy 1.x `session.query()`:
  ```python
  # Correct SQLAlchemy 2.0 usage:
  stmt = (
      select(WorkflowRecord)
      .where(WorkflowRecord.user_id == user_id)
      .order_by(WorkflowRecord.updated_at.desc())
      .limit(50)
  )
  results = (await session.execute(stmt)).scalars().all()
  ```
* Always wrap database access in context managers ensuring transaction rollback on error:
  ```python
  async with get_session() as session:
      async with session.begin():
          session.add(record)
  ```

### 2.4 Error Handling & Custom Exceptions
* Subclass `FlowsmithError` or `ConnectorError` with standardized machine-readable error codes:
  ```python
  class ConnectorError(Exception):
      def __init__(self, message: str, code: ConnectorErrorCode = ConnectorErrorCode.UNKNOWN):
          super().__init__(message)
          self.code = code
  ```
* Never catch generic `Exception` without re-raising or logging the full traceback.

---

## 3. Frontend React & JavaScript Standards

### 3.1 React 19 Idioms
* Functional components with explicit prop destructuring.
* Avoid massive monolithic components; extract reusable controls into focused sub-components.
* Use `useMemo` and `useCallback` judiciously to prevent expensive re-computations:
  ```jsx
  // Correct useMemo pattern with primitive/stable dependencies:
  const rawRecordJson = useMemo(() => {
    const recordData = params.data || params.record || {}
    try {
      return JSON.stringify(recordData, null, 2)
    } catch {
      return ''
    }
  }, [params.data, params.record])
  ```

### 3.2 Obsidian Glass Styling Conventions
* **Strict Token Usage**: Never hardcode raw hex values in JSX style props. Always reference CSS custom properties:
  ```jsx
  // Incorrect:
  <div style={{ background: '#111827', color: '#fff' }}>

  // Correct:
  <div style={{ background: 'var(--panel)', color: 'var(--text)' }}>
  ```
* **CSS Class Naming**: Use descriptive kebab-case names scoped to components (`.sf-editor`, `.sf-field`, `.modal-backdrop`).

### 3.3 State Management with Zustand
* Subscribe only to the specific slices of state a component renders:
  ```jsx
  // Correct (only re-renders when activeWorkflow changes):
  const activeWorkflow = useWorkflowStore(state => state.activeWorkflow)

  // Incorrect (causes re-renders on ANY store mutation):
  const store = useWorkflowStore()
  ```

---

## 4. Testing Standards

### 4.1 Backend Pytest Conventions
* Place test files in `backend/tests/` with the `test_*.py` naming convention.
* Use descriptive test function names stating input and expected outcome:
  ```python
  def test_salesforce_update_requires_valid_record_id():
      ...
  ```
* Mock external HTTP APIs using `unittest.mock.AsyncMock` or `respx`; never make live internet calls in automated unit tests.
* Ensure all tests clean up database state using the isolated test database fixtures (`automate_test`).

### 4.2 Frontend Vitest Conventions
* Component unit tests should use `renderToStaticMarkup` for ultra-fast, deterministic snapshot and text assertions.
* Verify keyboard accessibility, required badges, error states, and DOM structure.
* Keep test suites green with 0 errors and 0 warnings prior to merging.

---

## 5. Git Commit & Documentation Workflow

* Use Conventional Commits formatting:
  * `feat: add Microsoft Dynamics 365 Dataverse connector`
  * `fix: correct token refresh race condition in worker loop`
  * `docs: update API guide with batch execution endpoints`
  * `refactor: extract MappingInput component from node editors`
  * `test: add comprehensive test cases for OAuth PKCE exchange`
* Maintain clickable GitHub-flavored markdown file links for all references: `[filename](file:///path/to/file)`.
