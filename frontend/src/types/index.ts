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

export interface SelfHealingAttempt {
  attempt_number: number;
  patch_diff?: string;
  verified_vr?: number;
  verified_iou?: number;
  passed: boolean;
  error_message?: string;
  timestamp: string;
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
  /** PR title when the backend provides one. Absent in GET /api/runs + WS state today. */
  pr_title?: string;
  /**
   * Real per-node execution latency in ms, keyed by FSM step.
   * Only set when the backend reports measured durations. Never synthesized
   * client-side; missing entries render a neutral placeholder.
   */
  step_latency_ms?: Partial<Record<FSMStep, number>>;
}
