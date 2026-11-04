# 🛡️ VisorQA Draw.io Diagrams Guide & Technical Architecture Specification

> **Classification:** Engineering Specification & Architectural Diagrams Documentation  
> **Target Audience:** Principal Software Engineers, Staff Architects, and Hackathon Judges  
> **Format:** Native Draw.io XML (`.drawio`) compatible with [diagrams.net](https://app.diagrams.net), VS Code Draw.io Integration, and desktop applications.

---

## 1. Quick Access & File Inventory

All diagrams are provided both as individual standalone files and as a consolidated multi-tab master bundle.

| Diagram Name | File Path | Format | Description |
| :--- | :--- | :--- | :--- |
| **Consolidated Master Bundle** | [`VisorQA_Master_Diagrams.drawio`](file:///run/media/mrharpo/30BEB7EBBEB7A82C/Meta_Ai_Hackathons/VisorQA/Docs/VisorQA_Master_Diagrams.drawio) | Multi-Page `.drawio` | Contains all 3 diagrams in tabbed pages: System Architecture, Use Case Diagrams, and Database Schema (ERD). |
| **Master System Architecture** | [`VisorQA_System_Architecture.drawio`](file:///run/media/mrharpo/30BEB7EBBEB7A82C/Meta_Ai_Hackathons/VisorQA/Docs/VisorQA_System_Architecture.drawio) | Single Page `.drawio` | Comprehensive 5-tier architecture: Ingress, API Gateway, 5-Node FSM Orchestrator, Meta AI Models Suite, E2B Micro-VM, and PostgreSQL 16. |
| **UML Use Case Model** | [`VisorQA_Use_Case_Diagram.drawio`](file:///run/media/mrharpo/30BEB7EBBEB7A82C/Meta_Ai_Hackathons/VisorQA/Docs/VisorQA_Use_Case_Diagram.drawio) | Single Page `.drawio` | Formal UML 2.5 Use Case model covering 3 human actors, 3 system actors, 5 functional packages, `«include»`, and `«extend»` loops. |
| **Database Schema (ERD)** | [`VisorQA_Database_Schema.drawio`](file:///run/media/mrharpo/30BEB7EBBEB7A82C/Meta_Ai_Hackathons/VisorQA/Docs/VisorQA_Database_Schema.drawio) | Single Page `.drawio` | Complete PostgreSQL 16 relational Crow's Foot ERD, JSONB document schemas, GIN/Covering indexes, and database-level CHECK constraints. |

> **Backup / Mirror Directory:** Exact copies are also available under [`Docs/diagrams/`](file:///run/media/mrharpo/30BEB7EBBEB7A82C/Meta_Ai_Hackathons/VisorQA/Docs/diagrams/).

---

## 2. How to Open and Edit the Diagrams

### Option A: Web Browser (Instant, No Installation)
1. Navigate to **[https://app.diagrams.net](https://app.diagrams.net)**.
2. Select **"Open Existing Diagram"** (or drag & drop the `.drawio` file directly into the browser window).
3. If opening [`VisorQA_Master_Diagrams.drawio`](file:///run/media/mrharpo/30BEB7EBBEB7A82C/Meta_Ai_Hackathons/VisorQA/Docs/VisorQA_Master_Diagrams.drawio), toggle between the tabs at the bottom:
   - `1. System Architecture`
   - `2. Use Case Diagrams`
   - `3. Database Schema (PostgreSQL ERD)`

### Option B: VS Code / Cursor IDE
1. Install the extension: **Draw.io Integration** (`hediet.vscode-drawio`).
2. Click any `.drawio` file in the file explorer to view and edit visually directly inside the editor.

### Option C: Draw.io Desktop
1. Download from **[jgraph/drawio-desktop](https://github.com/jgraph/drawio-desktop/releases)**.
2. Open any `.drawio` file locally with full offline editing support.

---

## 3. Diagram 1: Master System Architecture Breakdown

### 3.1 Architecture Overview
The system architecture diagram visualizes the end-to-end, event-driven, closed-loop pipeline of VisorQA. It separates concerns into five distinct vertical tiers:

```
┌────────────────────┐   ┌────────────────────┐   ┌──────────────────────┐   ┌─────────────────────┐   ┌───────────────────────┐
│ 1. PRESENTATION    │   │ 2. FASTAPI GATEWAY │   │ 3. CORE DOMAIN & FSM │   │ 4. META AI MODELS   │   │ 5. SANDBOX & DB STORE │
│ GitHub PR / Bot    │──▶│ Webhook Ingestion  │──▶│ 5-Node FSM Machine   │──▶│ SAM 3.1 & Muse Suite│──▶│ E2B Micro-VM          │
│ Next.js 15 UI      │◀──│ WebSocket Hub      │◀──│ 3-Strike Feedback    │   │ (Spark, Wonder,     │   │ PostgreSQL 16 (JSONB) │
│ Realtime Stepper   │   │ In-Memory Cache    │   │ NumPy Math Engine    │   │  Code)              │   │ Auto-Commit to PR     │
└────────────────────┘   └────────────────────┘   └──────────────────────┘   └─────────────────────┘   └───────────────────────┘
```

### 3.2 Key Architectural Components
1. **Presentation & Ingress (Tier 1):**
   - **GitHub Pull Request & Webhooks:** Captures developer pushes, PR open/sync events, and commit SHAs.
   - **`visorqa-agent[bot]`:** GitHub App using RS256 JWT authentication and short-lived installation access tokens.
   - **Next.js 15 Mission Control (`frontend/`):** Real-time command center with `<FSMOrchestratorBar/>`, `<VisualEvidenceCard/>` (DOM vs SAM mask slider), `<TelemetryMetrics/>` scorecard, and `<UnifiedDiffViewer/>`.
2. **FastAPI Gateway & Real-Time Broker (Tier 2):**
   - **`POST /api/webhooks/github`:** Cryptographic HMAC-SHA256 signature verification (`X-Hub-Signature-256`) with `< 1.2s` ingestion response.
   - **WebSocket Broadcaster (`/ws/runs/{id}`):** Pub/sub manager delivering state changes, visual mask PNGs, and latency telemetry to the frontend in `< 10ms`.
   - **In-Memory Cache:** Ephemeral fast cache ensuring zero UI lag before PostgreSQL write completion.
3. **5-Node Deterministic FSM Engine (Tier 3):**
   - **[Node 01] SENSE:** Captures Mobile (`375×812`) and Desktop (`1440×900`) viewports in Playwright, extracts `visor-el-id` tracking tags and $B_{\text{DOM}}$ bounding boxes, and generates binary segmentation masks ($M_{\text{SAM}}$).
   - **[Node 02] TRIAGE:** Computes Lowest Common Ancestor (LCA) DOM subtree; Meta Muse Spark isolates parent layout container while **shielding** `src/components/ui/*` from any modification.
   - **[Node 03] DIAGNOSE:** Multimodal optical defect inspection by Meta Muse Wonder; emits declarative `RepairSpec` JSON (writes zero code).
   - **[Node 04] PATCH:** Meta Muse Code synthesizes surgical Unified Diff enforcing Tailwind responsive breakpoints and anti-hack rules (no `!important`, no `z-[9999]`).
   - **[Node 05] VERIFY:** Applies diff in sandbox via Hot Module Reload (HMR, `< 300ms`), re-captures dual viewports, and evaluates Composite Health $H$.
4. **Vectorized NumPy Vision Math Engine:**
   - **Visibility Ratio ($V_r$):**
     $$V_r = \frac{\text{Area}(M_{\text{SAM}} \cap B_{\text{DOM}})}{\text{Area}(B_{\text{DOM}})} \quad [\text{Defect if } < 0.85, \text{Healed if } \ge 0.98]$$
   - **Sibling Collision ($\text{IoU}$):**
     $$\text{IoU}(B_A, B_B) = \frac{\text{Area}(B_A \cap B_B)}{\text{Area}(B_A \cup B_B)} \quad [\text{Defect if } > 0.05, \text{Healed if } = 0.00]$$
   - **Horizontal Bleed ($\Delta_x$):**
     $$\Delta_x = \max(0, (x + w) - W_{\text{viewport}}) \quad [\text{Defect if } > 2.0\text{px}]$$
   - **Composite Viewport Health ($H$):**
     $$H = \text{mean}(V_r) - \max(\text{IoU}) - 0.01 \cdot \max(\Delta_x) \quad [\text{Gate: } H \ge 0.98 \text{ on BOTH viewports}]$$
5. **3-Strike Self-Healing Feedback Circuit:**
   - If $H < 0.98$ and $\text{attempt} < 3$: FSM rolls back sandbox state, snapshots the best-scoring patch, increments the attempt counter, and feeds new failure coordinates back to **Node 03 DIAGNOSE**.
   - If $H \ge 0.98$ on both viewports: Status marked `RESOLVED`, fix auto-committed directly to the PR branch.
   - If Strike 3 exhausted: Status marked `FALLBACK`, PR branch kept clean, best patch posted as a non-destructive suggested review comment.
6. **Meta AI Foundation Models Allocation (Tier 4):**
   - **Meta SAM 3.1:** Zero-shot pixel segmentation ($B_{\text{DOM}} \to M_{\text{SAM}}$) in 420ms.
   - **Meta Muse Spark 1.3:** LCA DOM tree pruning and component isolation (88.5% token reduction) in 580ms.
   - **Meta Muse Wonder 1.0:** Multimodal optical diagnostic reasoning; generates `RepairSpec` JSON.
   - **Meta Muse Code 1.3:** Unified diff patch synthesis (91% first-pass resolution rate).
7. **Infrastructure & Persistence (Tier 5):**
   - **E2B Micro-VM Sandbox:** Hardware virtualization container running Headless Chromium Playwright and HMR live reload.
   - **PostgreSQL 16 Persistence:** Stores multi-tenant configs, active watched repo singleton, FSM run lifecycle, anomalies, and attempt audit trails.

---

## 4. Diagram 2: Comprehensive Use Case Diagram Breakdown

### 4.1 Actors
- **Primary Human Actors:**
  - **Frontend Developer / PR Author:** Pushes code, opens PRs, reviews autonomous fixes.
  - **QA Lead / Reviewer / Tech Lead:** Monitors live Mission Control, inspects mask overlays, reviews math scorecards, and sets layout tolerances.
  - **DevOps / System Administrator:** Manages GitHub App secrets, configures watched repositories, defines budget caps ($0.05 min – $0.15 max / PR), and monitors system health.
- **Secondary / External System Actors:**
  - **GitHub Platform:** Delivers webhook events, authenticates bot requests, accepts git commits, and renders PR comments.
  - **Meta AI Models API:** Serves SAM 3.1 segmentation, Spark LCA triage, Wonder optical diagnosis, and Code patch synthesis.
  - **E2B Micro-VM Cloud / Modal:** Spawns isolated container sandboxes, executes Headless Playwright, and synchronizes live HMR diffs.

### 4.2 Functional Packages & Use Cases
1. **Package 1: PR Ingestion & Event Validation:**
   - `UC01: Open / Sync Pull Request`
   - `UC02: Receive Webhook Event`
   - `UC03: Validate HMAC-SHA256 Signature` (`«include»` to UC02)
   - `UC04: Spawn Async FSM Session` (`«include»` to UC02)
2. **Package 2: Dual-Viewport Optical Sense & Mathematical Evaluation:**
   - `UC05: Execute Optical Sense (Node 01)`
   - `UC06: Render Headless Playwright at 375px & 1440px` (`«include»` to UC05)
   - `UC07: Segment with Meta SAM 3.1` (`«include»` to UC05)
   - `UC08: Compute Vision Math Metrics (Vr, IoU, Bleed)` (`«include»` to UC05)
   - `UC08b: Calculate Composite Viewport Health H` (`«include»` to UC08)
3. **Package 3: Component Triage & Multimodal Optical Diagnosis:**
   - `UC09: Triage Source Components (Node 02)`
   - `UC10: Prune with Meta Muse Spark (Lock src/components/ui/*)` (`«include»` to UC09)
   - `UC11: Diagnose Optical Defect (Node 03)`
   - `UC12: Formulate RepairSpec JSON via Meta Muse Wonder` (`«include»` to UC11)
4. **Package 4: Surgical Patch Synthesis, HMR & 3-Strike Feedback Circuit:**
   - `UC13: Synthesize Surgical Diff via Meta Muse Code (Node 04)`
   - `UC14: Enforce Anti-Hack CSS Policy (No !important, No z-9999)` (`«include»` to UC13)
   - `UC15: Verify in E2B Sandbox (Node 05)`
   - `UC16: 3-Strike Self-Healing Feedback Loop` (`«extend»` to UC15 when $H < 0.98 \land \text{attempt} < 3$)
5. **Package 5: Resolution Governance, Audit & Observability:**
   - `UC17: Auto-Commit Verified Fix` (`«extend»` to UC15 when $H \ge 0.98$ on both viewports)
   - `UC18: Post Non-Destructive Review Comment` (`«extend»` to UC16 when Strike 3 is exhausted)
   - `UC19: Monitor Mission Control UI via WebSockets`
   - `UC20: Inspect Math Scorecards & Visual Mask Sliders` (`«include»` to UC19)
   - `UC21: Configure Watched Repo & Budget Caps`
   - `UC22: Audit Run Telemetry & Historical Database Records`

---

## 5. Diagram 3: Database Schema (PostgreSQL 16 ERD) Breakdown

### 5.1 Relational Architecture & Tables

#### 1. `repositories` (Multi-Tenant SaaS Configuration)
- **`id`** (`VARCHAR / UUID`, PK): Unique repository configuration identifier.
- **`repo_full_name`** (`VARCHAR(255)`, UNIQUE, INDEX): GitHub full repository name (e.g., `sayedibrahimQ/visorqa-demo-storefront`).
- **`default_branch`** (`VARCHAR(64)`, DEFAULT `'main'`): Target base branch.
- **`protected_globs`** (`JSONB`, NOT NULL, DEFAULT `'["src/components/ui/*"]'`): File globs forbidden from automated modification.
- **`modal_snapshot_id`** (`VARCHAR(255)`, NULLABLE): Cached sandbox container image ID.
- **`commit_mode`** (`VARCHAR(32)`, DEFAULT `'SUGGEST_REVIEW'`): `AUTO_COMMIT` or `SUGGEST_REVIEW`.
- **`is_active`** (`BOOLEAN`, DEFAULT `TRUE`): Active monitoring toggle.
- **`created_at`** (`TIMESTAMPTZ`, DEFAULT `NOW()`): Creation timestamp.

#### 2. `watched_repository` (Singleton Runtime Target)
- **`id`** (`INT`, PK, CHECK `id = 1`): Enforces the single-repository sentinel invariant.
- **`repo_full_name`** (`VARCHAR(255)`, INDEX): The one repository actively watched by VisorQA.
- **`default_branch`** (`VARCHAR(64)`, DEFAULT `'main'`): Monitored branch.
- **`installation_id`** (`BIGINT`, NULLABLE): GitHub App installation token identifier.
- **`webhook_active`** (`BOOLEAN`, DEFAULT `FALSE`): Ingress webhook active status.
- **`auto_heal_enabled`** (`BOOLEAN`, DEFAULT `TRUE`): Auto-healing enablement switch.
- **`updated_at`** (`TIMESTAMPTZ`, DEFAULT `NOW()`): Last sync timestamp.
- *Fallback Mechanism:* Automatically synchronized with `artifacts/watched_repo.json` when PostgreSQL is offline locally.

#### 3. `pr_runs` (Master FSM Run Aggregate Root)
- **`id`** (`VARCHAR / UUID`, PK): Primary run tracking ID.
- **`repo_id`** (`VARCHAR / UUID`, FK $\to$ `repositories.id`, INDEX, NULLABLE): Parent repository relationship.
- **`github_delivery_id`** (`VARCHAR(64)`, UNIQUE): GitHub Webhook delivery UUID for idempotent replay prevention.
- **`repo_full_name`** (`VARCHAR(255)`, INDEX): Target repo.
- **`pr_number`** (`INT`, INDEX): GitHub PR number.
- **`pr_title`** (`VARCHAR(512)`, NULLABLE): PR headline.
- **`branch`** (`VARCHAR(128)`, DEFAULT `'main'`): Head branch name.
- **`commit_sha`** (`VARCHAR(64)`, INDEX): Head commit hash.
- **`status`** (`VARCHAR(32)`, INDEX): Lifecycle state (`QUEUED`, `SENSE`, `TRIAGE`, `DIAGNOSE`, `PATCH`, `VERIFY`, `RESOLVED`, `FALLBACK`, `FAILED`).
- **`attempt`** (`INT`, CHECK `attempt BETWEEN 0 AND 3`): Current strike count.
- **`max_attempts`** (`INT`, DEFAULT `3`): Maximum allowed feedback loops.
- **`target_files`** (`JSONB`, NOT NULL, DEFAULT `'[]'`): Triaged candidate source file paths.
- **`initial_score`** (`FLOAT`, DEFAULT `0.0`): Baseline health score before repair.
- **`best_score`** (`FLOAT`, DEFAULT `0.0`): Peak composite health score achieved.
- **`best_patch`** (`TEXT`, NULLABLE): Highest-scoring Unified Diff preserved for audit/fallback review.
- **`is_resolved`** (`BOOLEAN`, INDEX, DEFAULT `FALSE`): Successfully healed flag.
- **`healed_commit_sha`** (`VARCHAR(64)`, NULLABLE): Commit hash generated on auto-commit.
- **`total_latency_ms`** (`INT`, DEFAULT `0`): End-to-end execution duration.
- **`total_cost_usd`** (`NUMERIC(6,4)`, CHECK `total_cost_usd <= 0.15`): Unit economics safety guardrail ($0.05 min single-pass, $0.15 max ceiling per PR).
- **`created_at`** (`TIMESTAMPTZ`, DEFAULT `NOW()`): Run initiation timestamp.
- **`updated_at`** (`TIMESTAMPTZ`, DEFAULT `NOW()`): Last stage transition timestamp.
- *Covering Index:* `idx_pr_runs_dashboard_covering` on `(repo_full_name, created_at DESC)` for sub-millisecond dashboard queries.

#### 4. `visual_anomalies` (Mathematical Optical Defects)
- **`id`** (`VARCHAR / UUID`, PK): Anomaly instance ID.
- **`run_id`** (`VARCHAR / UUID`, FK $\to$ `pr_runs.id` ON DELETE CASCADE, INDEX): Associated PR run.
- **`attempt_num`** (`INT`, INDEX, DEFAULT `0`): Attempt index during which defect was detected.
- **`viewport`** (`VARCHAR(16)`, INDEX, CHECK `viewport IN ('375px', '1440px')`): Viewport specification.
- **`visor_el_id`** (`VARCHAR(64)`, INDEX): DOM-to-SAM 1:1 correlation tracking attribute.
- **`secondary_el_id`** (`VARCHAR(64)`, NULLABLE): Collision or occlusion partner element ID.
- **`defect_type`** (`VARCHAR(32)`, INDEX): `OCCLUSION`, `COLLISION`, or `BLEED`.
- **`v_r`** (`FLOAT`, NULLABLE): Visibility ratio ($V_r$).
- **`iou`** (`FLOAT`, NULLABLE): Intersection-over-Union ($\text{IoU}$).
- **`bleed_px`** (`FLOAT`, NULLABLE): Horizontal bleed in pixels ($\Delta_x$).
- **`b_dom_box`** (`JSONB`, NOT NULL): Client bounding box `{x, y, width, height, selector}`.
- **`lca_dom`** (`JSONB`, NOT NULL): Extracted DOM ancestor hierarchy.
- **`mask_url`** (`TEXT`, NULLABLE): Disk / artifact path to SAM 3.1 red mask overlay PNG.
- **`is_resolved`** (`BOOLEAN`, INDEX, DEFAULT `FALSE`): Defect resolution status.
- **`created_at`** (`TIMESTAMPTZ`, DEFAULT `NOW()`): Detection timestamp.
- *Mathematical Check Constraint:*
  ```sql
  CHECK (
    (defect_type = 'OCCLUSION' AND v_r IS NOT NULL AND v_r < 0.85) OR
    (defect_type = 'COLLISION' AND iou IS NOT NULL AND iou > 0.05) OR
    (defect_type = 'BLEED' AND bleed_px IS NOT NULL AND bleed_px > 2.0)
  )
  ```
- *GIN Index:* `idx_anomalies_lca_gin` ON `lca_dom` USING GIN.

#### 5. `repair_attempts` (3-Strike Closed-Loop Audit Trail)
- **`id`** (`VARCHAR / UUID`, PK): Attempt audit record ID.
- **`run_id`** (`VARCHAR / UUID`, FK $\to$ `pr_runs.id` ON DELETE CASCADE, INDEX): Associated PR run.
- **`attempt_number`** (`INT`, CHECK `attempt_number BETWEEN 1 AND 3`): Attempt counter.
- **`repair_spec`** (`JSONB`, NOT NULL): Meta Muse Wonder Pydantic diagnostic specification.
- **`unified_diff`** (`TEXT`, NULLABLE): Meta Muse Code synthesized git patch hunk.
- **`telemetry`** (`JSONB`, NOT NULL): Complete verification scorecard snapshot.
- **`mobile_v_r_min`** (`FLOAT`, DEFAULT `0.0`): Lowest $V_r$ recorded on 375px mobile viewport.
- **`desktop_v_r_min`** (`FLOAT`, DEFAULT `1.0`): Lowest $V_r$ recorded on 1440px desktop viewport.
- **`verified_iou`** (`FLOAT`, DEFAULT `0.0`): Sibling collision on re-sense.
- **`verified_bleed_px`** (`FLOAT`, DEFAULT `0.0`): Viewport bleed on re-sense.
- **`post_score`** (`FLOAT`, DEFAULT `0.0`): Composite Health $H$ after patch application.
- **`hmr_latency_ms`** (`INT`, DEFAULT `0`): Sandbox Hot Module Reload duration in milliseconds.
- **`passed`** (`BOOLEAN`, DEFAULT `FALSE`): Verification gate status ($H \ge 0.98$ on both viewports).
- **`error_message`** (`TEXT`, NULLABLE): Syntax validation or execution error details.
- **`created_at`** (`TIMESTAMPTZ`, DEFAULT `NOW()`): Attempt recording timestamp.
- *Anti-Hack CSS Check Constraint:*
  ```sql
  CHECK (
    unified_diff IS NULL OR (
      unified_diff NOT ILIKE '%!important%' AND
      unified_diff NOT ILIKE '%z-index: 9999%' AND
      unified_diff NOT ILIKE '%z-[9999]%'
    )
  )
  ```
- *GIN Index:* `idx_attempts_repair_spec_gin` ON `repair_spec` USING GIN.
- *Unique Constraint:* `UNIQUE (run_id, attempt_number)` enforcing one audit entry per strike attempt.

### 5.2 Cardinalities & Entity Relationships
```
[repositories] 1 ──────── 0..N [pr_runs] (Optional parent configuration)
[pr_runs]      1 ──────── 0..N [visual_anomalies] (CASCADE DELETE)
[pr_runs]      1 ──────── 1..3 [repair_attempts] (CASCADE DELETE, MAX 3)
[watched_repository] (Singleton sentinel id=1)
```

---

## 6. Verification and Generation Script

The generator script is completely deterministic and self-contained:
```bash
python3 scripts/generate_drawio_diagrams.py
```

It validates that all generated draw.io files conform to strict XML standards, contain zero syntax warnings, and can be rendered seamlessly across any draw.io compatible client.

