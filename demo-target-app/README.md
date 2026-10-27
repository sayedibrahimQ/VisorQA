# Demo Target Storefront App

This directory contains the sample target web application used for autonomous visual QA regression testing.

## Target Visual Regressions (3 Visual Defects):
1. **Occlusion / Z-Index Defect:** Fixed promo banner covering the primary checkout CTA (`visor-el-04`), causing Visibility Ratio $V_r < 0.85$.
2. **Layout Collision Defect:** Overlapping text and badge elements in responsive viewport ($IoU > 0.05$).
3. **Viewport Bleed / Overflow Defect:** Mobile viewport horizontal clipping ($375\text{px}$) where content bleeds outside the boundary.
