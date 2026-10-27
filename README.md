# VisorQA 
**Autonomous Visual QA & Self-Healing Frontend Agent**  
*Built for the Meta Global AI Developer Hackathon*

VisorQA catches pixel-level UI regressions (z-index clipping, layout collisions, viewport overflow) that pass standard DOM tests (Playwright/Cypress), diagnoses the root cause, and autonomously commits verified CSS/React fixes inside isolated sandboxes.

## Architecture
1. **DOM Geometry Extraction (Playwright + Modal Sandboxes):** Boots PR branches across Desktop (`1440x900`) and Mobile (`375x812`) viewports and extracts expected DOM bounding boxes ($B_{DOM}$) + computed styles.
2. **Pixel-Level Segmentation (Meta SAM 3.1):** Generates actual visible pixel masks ($M_{SAM}$) for every interactive UI component.
3. **Mathematical Discrepancy Engine:**
   - **Occlusion / Clipping:** $\text{Visibility Ratio} = \frac{\text{Area}(M_{SAM})}{\text{Area}(B_{DOM})} < 0.85$
   - **Component Collision:** $IoU(M_i, M_j) > 0.05$
4. **Triage & Root-Cause Reasoning (Muse Spark + Muse Wonder):** Maps visual anomalies to exact source files and diagnoses layout failures.
5. **Self-Healing Patch Loop (Muse Code + Modal):** Generates the code patch, hot-reloads the sandbox, re-verifies with SAM 3.1 until $IoU = 0$, and commits the fix to the PR.

## Repository Structure
- `agent-core/` — Modal sandbox runner, Playwright DOM extractor, SAM 3.1 discrepancy engine, and Muse orchestrator.
- `dashboard/` — Live trace & mask-overlay visualization dashboard.
- `demo-target-app/` — Sample storefront with reproducible CSS/layout regressions.
