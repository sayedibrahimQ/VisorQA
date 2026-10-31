export type FSMStep = 
  | "1.SENSE" 
  | "2.TRIAGE" 
  | "3.DIAGNOSE" 
  | "4.PATCH" 
  | "5.VERIFY";

export type RunStatus = "PENDING" | "RUNNING" | "RESOLVED" | "FAILED";

export type DefectType = "OCCLUSION" | "COLLISION" | "VIEWPORT_OVERFLOW";

export interface DOMBoundingBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface Anomaly {
  id: string;
  element_id: string;
  defect_type: DefectType;
  bounding_box?: DOMBoundingBox;
  visibility_ratio?: number;
  iou_score?: number;
  /** Viewport tag ('375px' | '1440px'). Mirrors AnomalyRecord.viewport; omitted by serializers today. */
  viewport?: string;
  /** Horizontal overflow in px. Mirrors AnomalyRecord.bleed_px; omitted by serializers today. */
  bleed_px?: number;
  sam_mask_path?: string;
  status: string;
}

/** Node 3 (Muse Wonder) RepairSpec JSON. Mirrors backend RepairSpec + GET /api/runs/{id} attempts[].repair_spec. */
export interface RepairSpecPayload {
  root_cause?: string;
  affected_selectors?: string[];
  target_file?: string;
  css_strategy?: string;
  desktop_preservation_constraints?: string[];
  forbidden_hacks?: string[];
  [key: string]: unknown;
}

/** Node 2 BR-2 decision. Mirrors backend RejectedTarget. */
export interface TriageRejectedTarget {
  path: string;
  reason: string;
}

/** Node 2 LCA node descriptor. Mirrors backend NodeDescriptor (either alias spelling). */
export interface NodeDescriptorInfo {
  tag?: string;
  element_id?: string;
  classes?: string[];
  visor_el_id?: string;
  "data-visor-el-id"?: string;
  role?: string;
  aria_label?: string;
  "aria-label"?: string;
  text_hint?: string;
  react_hint?: string;
}

/** Per-viewport verification metrics. Mirrors backend evaluate_viewport output. */
export interface ViewportMetrics {
  v_r?: number;
  iou?: number;
  delta_x?: number;
  valid?: boolean;
  passed?: boolean;
  failure_reasons?: string[];
  screenshot_ref?: string;
}

export interface SelfHealingAttempt {
  attempt_number: number;
  patch_diff?: string;
  verified_vr?: number;
  verified_iou?: number;
  /** Mirrors backend SelfHealingAttempt.verified_bleed_px. */
  verified_bleed_px?: number;
  passed: boolean;
  error_message?: string;
  timestamp: string;
  /** Mirrors backend SelfHealingAttempt.verification_status. */
  verification_status?: string;
  /** Mirrors backend SelfHealingAttempt.viewport_metrics ({mobile, desktop}). */
  viewport_metrics?: Record<string, ViewportMetrics>;
  /** Node 3 RepairSpec JSON (GET /api/runs/{id} attempts[]). */
  repair_spec?: RepairSpecPayload;
  /** Node 4 unified diff (GET /api/runs/{id} attempts[]). */
  unified_diff?: string;
}

/** Sandbox handoff. Mirrors backend SandboxMetadata (subset used by the drawer). */
export interface SandboxHandoff {
  backend?: string;
  last_patch_phase?: string;
  last_hmr_status?: string;
  server_state?: string;
  patch_count?: number;
  preview_url?: string | null;
  patch_timings?: Record<string, unknown>;
}

export interface PRRun {
  id: string;
  pr_number: number;
  repo_name: string;
  branch: string;
  commit_sha: string;
  status: RunStatus;
  current_step: FSMStep;
  strikes: number;
  anomalies_count?: number;
  anomalies?: Anomaly[];
  attempts?: SelfHealingAttempt[];
  created_at?: string;
  updated_at?: string;
  /** Merged backend repair_spec dict (triage metadata + diagnosis). Passthrough; sync does not populate it today. */
  repair_spec?: Record<string, unknown>;
  /** Node 4 in-flight unified diff (backend AgentState.current_patch). */
  current_patch?: string;
  /** Best verified unified diff (backend AgentState.best_patch). */
  best_patch?: string;
  /** Sandbox handoff (backend AgentState.sandbox). */
  sandbox?: SandboxHandoff;
  /** PR title when the backend provides one. Absent in GET /api/runs + WS state today. */
  pr_title?: string;
  /**
   * Real per-node execution latency in ms, keyed by FSM step.
   * Only set when the backend reports measured durations. Never synthesized
   * client-side; missing entries render a neutral placeholder.
   */
  step_latency_ms?: Partial<Record<FSMStep, number>>;
}
