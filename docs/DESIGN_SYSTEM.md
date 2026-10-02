# Flowsmith — Design System Specification

> **Design System Name**: Obsidian Glass  
> **Target Theme**: Dark-First Translucent Glassmorphism  
> **Typography**: Inter & JetBrains Mono  
> **Iconography**: Bespoke Vector SVG Brand Marks & Lucide Icons  

---

## 1. Design Philosophy & Aesthetic Principles

**Obsidian Glass** is Flowsmith’s proprietary, super-premium enterprise design language. It is crafted specifically for complex, mission-critical workflow graphs, dense data visualization, and real-time execution monitoring.

```
       ┌────────────────────────────────────────────────────────┐
       │                    OBSIDIAN GLASS                      │
       ├─────────────────────────┬──────────────────────────────┤
       │ 1. Deep Optical Contrast│ Midnight obsidian surfaces   │
       │ 2. Frosted Translucency │ Glassmorphic blur & glow     │
       │ 3. Vibrant Vector Marks │ Handcrafted brand badges     │
       │ 4. Micro-Interactions   │ Tactile feedback on actions  │
       └─────────────────────────┴──────────────────────────────┘
```

1. **Deep Optical Contrast**: Midnight obsidian dark-mode foundation eliminates eye fatigue during multi-hour canvas building sessions while making colored signal paths visually striking.
2. **Frosted Translucency**: Subtly elevated modals, drawers, and floating toolbars utilize `backdrop-filter: blur(16px)` to maintain environmental awareness of the underlying workflow graph.
3. **Information Density with Breathing Room**: Tight 4px / 8px spacing scale ensures maximum screen real estate for workflow DAGs, balanced with clear padding around interactive controls.
4. **Instant Visual State Feedback**: Every node, handle, edge, and button reacts instantaneously with smooth CSS transforms, subtle box-shadow flares, and status glow rings.

---

## 2. Design Tokens

### 2.1 Color Palette

#### Base Surface Hierarchy
```css
:root {
  /* Surfaces & Canvas */
  --bg: #0b0f19;              /* Deep Space Obsidian (Canvas background) */
  --bg-elevated: #111827;     /* Elevated Card Background */
  --panel: #161f30;           /* Modal & Sidebar Body */
  --panel-2: #1e293b;         /* Secondary Container / Accordion Body */
  --panel-3: #243248;         /* Active / Focused Container */

  /* Text & Foreground */
  --text: #f8fafc;            /* Primary Text (High contrast, 98% white) */
  --text-secondary: #cbd5e1;  /* Secondary Text (80% slate) */
  --muted: #64748b;           /* Placeholder & Meta Text */
  --faint: #334155;           /* Disabled / Inactive Icons */

  /* Borders & Dividers */
  --border: rgba(255, 255, 255, 0.08);        /* Subtle Divider */
  --border-hover: rgba(255, 255, 255, 0.16);  /* Hovered Edge */
  --border-focus: rgba(99, 102, 241, 0.5);    /* Keyboard Focus / Active Edge */
}
```

#### Accent & Semantic Colors
```css
:root {
  /* Primary Brand Accents */
  --primary: #4f8cff;         /* Flowsmith Electric Blue */
  --primary-glow: rgba(79, 140, 255, 0.25);
  --accent: #6366f1;          /* Indigo Fusion */
  --accent-glow: rgba(99, 102, 241, 0.25);

  /* Semantic Feedback Tokens */
  --success: #10b981;         /* Emerald 500 (Success, Active, Passed) */
  --success-bg: rgba(16, 185, 129, 0.12);
  --success-border: rgba(16, 185, 129, 0.35);

  --err: #ef4444;             /* Crimson Rose 500 (Failed, Error, Reject) */
  --err-bg: rgba(239, 68, 68, 0.12);
  --err-border: rgba(239, 68, 68, 0.35);

  --warn: #f59e0b;            /* Warm Amber 500 (Waiting, Escalated) */
  --warn-bg: rgba(245, 158, 11, 0.12);
  --warn-border: rgba(245, 158, 11, 0.35);

  --info: #0ea5e9;            /* Sky Blue 500 (Running, Processing) */
  --info-bg: rgba(14, 165, 233, 0.12);
  --info-border: rgba(14, 165, 233, 0.35);
}
```

#### Node Category Color Coding
Every node category in Flowsmith displays a distinct, high-recognition accent color:

| Category | Primary Color | Hex Code | Border Badge Style | Example Nodes |
| :--- | :--- | :--- | :--- | :--- |
| **Triggers** | Electric Emerald | `#10b981` | Glowing Emerald Edge | Webhook, Schedule, Manual, Form |
| **Flow Control** | Violet Indigo | `#8b5cf6` | Violet Pulse | If Condition, Switch, Loop While, Split |
| **Data Transform** | Amber Gold | `#f59e0b` | Warm Amber Border | Set Variable, Aggregate, Filter, Code |
| **AI & RAG** | Radiant Fuchsia | `#ec4899` | Fuchsia Neon Ring | AI Agent, LLM Prompt, RAG Search |
| **Enterprise CRM** | Corporate Azure | `#0078d4` | Cobalt Accent | Salesforce, Microsoft Dynamics 365, HubSpot |
| **Databases** | Cyan Sea | `#06b6d4` | Cyan Outline | Postgres, MongoDB, MySQL, Redis |
| **Messaging** | Slate Sky | `#0ea5e9` | Sky Blue Accent | Slack, Email, WhatsApp, Discord |

---

### 2.2 Typography Scale

Flowsmith utilizes **Inter** for all UI surfaces and **JetBrains Mono** for all code, JEXL expressions, JSON payloads, and log viewers.

| Token | Font Family | Size | Weight | Line Height | Usage |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `text-xs` | Inter | 11px | 400 / 500 | 14px | Field hints, badges, timestamp chips |
| `text-sm` | Inter | 12.5px | 500 | 18px | Input values, accordion headers, dropdowns |
| `text-base` | Inter | 14px | 500 / 600 | 20px | Modal headers, section titles, card labels |
| `text-lg` | Inter | 16px | 600 | 24px | Page titles, drawer headings |
| `text-xl` | Inter | 20px | 700 | 28px | Canvas top navigation title |
| `font-mono` | JetBrains Mono | 12px | 400 / 500 | 18px | JSON Viewer, expressions (`{{ ... }}`), SQL |

---

## 3. Core Component Patterns

### 3.1 Custom Workflow Node (`CustomNode.jsx`)
Nodes are the atomic units of the Flowsmith canvas. Built on top of React Flow (`@xyflow/react`):
* **Geometry**: Fixed width (260px) with dynamic auto-height based on subtitles and status pills.
* **Border & Elevation**: 1px solid `var(--border)` with `border-radius: 12px`. On selection, transitions to `border-color: var(--primary)` with an ambient outer glow `0 0 0 3px rgba(79, 140, 255, 0.2)`.
* **Header Structure**:
  * Left: 24px vector brand icon inside a rounded badge (`background: rgba(255,255,255,0.06)`).
  * Center: Node Label (bold 13px) and secondary subtitle (e.g. `contacts • Create`).
  * Right: Status indicator (green checkmark, red error badge, or animated rotating spinner).
* **Connection Handles**: Custom handles styled with outer border ring and hover expansion to ensure effortless mouse targeting.

### 3.2 Dynamic Mapping Input (`MappingField.jsx`)
A specialized input component that bridges raw text entry and reactive workflow expressions:
* **The "fx" Button**: Clicking the `fx` pill opens an inline popover indexing all available upstream node output fields.
* **Drag-and-Drop Variable Ingestion**: Users can drag data pills directly from the Output Panel into any `MappingInput` field.
* **Live Expression Preview**: If the value contains JEXL syntax like `{{ $(Webhook).item.json.email }}`, an asynchronous debounced preview chip renders the evaluated result directly below the input.

### 3.3 Searchable Select (`SearchableSelect.jsx`)
Replaces generic browser `<select>` elements with an Obsidian Glass searchable dropdown:
* Instant keyboard filtering (`query.toLowerCase()`).
* Rich option previews displaying title, icon, and multi-line technical descriptions.
* Full keyboard navigation (Arrow Up, Arrow Down, Enter, Escape).

### 3.4 Collapsible Field Accordions
Used in tier-1 enterprise editors (Salesforce, Microsoft Dynamics CRM) for managing complex record schemas:
* **Header Bar**: Displays `Field N`, localized column title badge, remove (`x`) icon, and chevron toggle.
* **Bulk Controls**: `[Expand all | Collapse all]` buttons for reviewing dozens of fields without scrolling fatigue.
* **Animation**: Hardware-accelerated CSS keyframe slide down (`0.14s ease-out`).

---

## 4. Modal & Drawer Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Modal Backdrop (rgba(0, 0, 0, 0.72) + blur(16px))          │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ Obsidian Modal Window (border: rgba(255,255,255,0.1)) │  │
│  ├───────────────────────────────────────────────────────┤  │
│  │ Tab Bar: [Parameters] [Settings]                      │  │
│  ├───────────────────────────────────────────────────────┤  │
│  │ Modal Body: SearchableSelects, Accordions, FormFields │  │
│  ├───────────────────────────────────────────────────────┤  │
│  │ Footer: [Test Step]                   [Save & Close]  │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

* **Backdrop**: Smooth dark overlay with high-blur backdrop filter to isolate attention.
* **Glass Container**: Double-bordered container with subtle radial gradient shining from the top-left edge.
* **Tab Navigation**: Clean pill tabs (`Parameters`, `Settings`, `Code`) with sliding background indicator.

---

## 5. Micro-Interactions & Animation Guidelines

* **Button Press Feedback**: All interactive buttons implement tactile scale compression on click:
  ```css
  button:active:not(:disabled) {
    transform: scale(0.97);
  }
  ```
* **Hover Transitions**: Standardized timing for hover states:
  ```css
  transition: background 0.12s ease, border-color 0.12s ease, transform 0.1s ease, box-shadow 0.12s ease;
  ```
* **Execution Pulse**: Running nodes display a subtle breathing SVG ring with emerald/sky illumination.

---

## 6. Accessibility & Contrast Compliance

* **WCAG 2.1 AA Compliance**: All text tokens against dark surfaces meet the 4.5:1 minimum contrast ratio requirement (primary text `#f8fafc` on `#0b0f19` achieves > 16:1 ratio).
* **Keyboard Navigation**: Complete focus rings (`outline: 2px solid var(--accent); outline-offset: 2px`) on all interactive canvas elements, inputs, and modals.
* **Screen Reader Semantics**: Proper ARIA roles on tabs (`role="tab"`, `aria-selected`), modals (`role="dialog"`, `aria-modal="true"`), and searchable select popovers (`role="listbox"`).
