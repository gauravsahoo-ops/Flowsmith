// Types for the store instance the app exposes to e2e specs
// (src/main.jsx: window.__wfStore). The app itself is plain JS, so this
// describes only the surface the Playwright specs use.

interface WfStoreWorkflow {
  id: string;
  name: string;
}

interface WfStoreNode {
  id: string;
  type?: string;
  position?: { x: number; y: number };
  data?: {
    node?: {
      id: string;
      type: string;
      parameters?: Record<string, unknown>;
      settings?: Record<string, unknown>;
      credentials?: Record<string, string>;
      version?: number;
    };
  };
}

interface WfStoreEdge {
  id: string;
  source: string;
  sourceHandle?: string | null;
  target: string;
  targetHandle?: string | null;
}

interface WfStoreConnection {
  source: string;
  sourceHandle?: string;
  target: string;
  targetHandle?: string;
}

interface WfStoreState {
  workflow: WfStoreWorkflow | null;
  nodes: WfStoreNode[];
  edges: WfStoreEdge[];
  loading?: boolean;
  saving: boolean;
  setName(name: string): void;
  addNode(type: string, position: { x: number; y: number }): string;
  updateNode(id: string, patch: Record<string, unknown>): void;
  onConnect(connection: WfStoreConnection): void;
  save(): Promise<void> | void;
  load(id: string): Promise<void> | void;
}

interface WfStore {
  getState(): WfStoreState;
}

interface UiStoreState {
  openNodeEditor?: (nodeId: string) => void;
  closeNodeEditor?: () => void;
  [key: string]: unknown;
}

interface UiStore {
  getState(): UiStoreState;
}

declare global {
  interface Window {
    __wfStore: WfStore;
    __uiStore: UiStore;
    __executionStore?: unknown;
    __execStore?: unknown;
  }
}

export {};
