"""High-resolution realistic visual viewport renderer for VisorQA.

Generates realistic, crisp 375x812 (mobile) and 1440x900 (desktop) visual viewports
using Pillow (PIL.ImageDraw) depicting:
- Before (screenshot_before.png): Mobile layout with overlapping/colliding
  element (visor-el-04 / fixed promo banner colliding over the primary CTA, V_r = 0.62)
  and clean desktop layout (V_r = 1.00, IoU = 0.00).
- SAM 3.1 Mask (sam_mask.png): Segmented pixel mask highlighting the
  occluded/colliding region in crimson (#F43F5E).
- Overlay (overlay.png): Diagnostic composite with dashed cyan #00F0FF outlines
  and 35% opacity crimson SAM mask.
- After (screenshot_after.png): Healed post-patch mobile layout where the banner
  is moved to relative flow below the CTA, restoring V_r = 1.00, IoU = 0.00,
  and preserved clean desktop layout.
"""
from __future__ import annotations

import io
from typing import Any, Dict, Optional, Sequence, Tuple
import numpy as np
from PIL import Image, ImageDraw, ImageFont

CYAN = (0, 240, 255)         # #00F0FF
CRIMSON = (244, 63, 94)      # #F43F5E
BG_COLOR = (10, 10, 12)      # #0A0A0C
CARD_BG = (18, 20, 26)       # #12141A
CARD_BORDER = (34, 36, 46)   # #22242E
TEXT_PRIMARY = (250, 250, 250)
TEXT_MUTED = (148, 163, 184)
TEXT_DIM = (100, 116, 139)


def _get_font(size: int = 12):
    try:
        # Try finding a standard system truetype font
        for font_name in (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
            "/usr/share/fonts/TTF/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ):
            try:
                return ImageFont.truetype(font_name, size)
            except Exception:
                continue
    except Exception:
        pass
    return ImageFont.load_default()


def render_realistic_viewport(
    width: int,
    height: int,
    *,
    viewport: str = "mobile",
    healed: bool = False,
    repo_name: str = "sayedibrahimQ/VisorQA",
    anomalies: Optional[Sequence[Dict[str, Any]]] = None,
) -> Tuple[Image.Image, np.ndarray]:
    """Render a realistic, high-resolution visual viewport and its SAM 3.1 mask."""
    is_mobile = width == 375 or viewport in ("mobile", "375px")
    img = Image.new("RGB", (width, height), BG_COLOR)
    draw = ImageDraw.Draw(img)

    font_title = _get_font(20 if is_mobile else 28)
    font_sub = _get_font(12 if is_mobile else 14)
    font_bold = _get_font(12 if is_mobile else 13)
    font_xs = _get_font(10 if is_mobile else 11)

    # 1. Navigation Header
    header_h = 56 if is_mobile else 64
    draw.rectangle([0, 0, width, header_h], fill=(17, 18, 23))
    draw.line([(0, header_h), (width, header_h)], fill=CARD_BORDER, width=1)

    # Logo / Brand
    draw.rectangle([16, 14, 40, 38], fill=(0, 240, 255), outline=(0, 200, 220))
    draw.text((48, 18), "VisorQA", fill=TEXT_PRIMARY, font=font_bold)

    short_repo = repo_name.split("/")[-1] if "/" in repo_name else repo_name
    if not is_mobile:
        # Desktop Nav Links
        nav_x = 200
        for item in ("Overview", "SAM 3.1 Vision", "FSM Loop", "PR Telemetry", "Docs"):
            draw.text((nav_x, 24), item, fill=TEXT_MUTED, font=font_sub)
            nav_x += 120
        # Right Actions
        draw.rectangle([width - 240, 16, width - 140, 48], outline=CARD_BORDER, width=1)
        draw.text((width - 220, 24), "Documentation", fill=TEXT_MUTED, font=font_xs)
        draw.rectangle([width - 120, 16, width - 20, 48], fill=(0, 240, 255))
        draw.text((width - 105, 24), "Launch App", fill=(10, 10, 12), font=font_bold)
    else:
        # Mobile hamburger menu icon
        draw.rectangle([width - 36, 20, width - 16, 22], fill=TEXT_MUTED)
        draw.rectangle([width - 36, 27, width - 16, 29], fill=TEXT_MUTED)
        draw.rectangle([width - 36, 34, width - 16, 36], fill=TEXT_MUTED)
        draw.text((width - 120, 22), f"{short_repo[:12]}", fill=TEXT_DIM, font=font_xs)

    # 2. Hero Section
    mask = np.zeros((height, width), dtype=np.uint8)

    if is_mobile:
        # Mobile Layout
        # Tag badge
        draw.rectangle([16, 72, 260, 94], fill=(18, 22, 32), outline=(0, 240, 255), width=1)
        draw.text((24, 76), "✦ Autonomous Visual Self-Healing", fill=(0, 240, 255), font=font_xs)

        # Headline
        draw.text((16, 106), "Production Visual QA\n& Layout Guard", fill=TEXT_PRIMARY, font=font_title)
        draw.text((16, 164), "Meta SAM 3.1 segmenter + Muse AST CSS\nauto-repair for responsive web apps.", fill=TEXT_MUTED, font=font_sub)

        # Primary CTA Button: visor-el-01
        btn_y = 224
        btn_w, btn_h = 165, 42
        draw.rectangle([16, btn_y, 16 + btn_w, btn_y + btn_h], fill=(0, 240, 255), outline=(0, 200, 220))
        draw.text((36, btn_y + 13), "Run Optical QA", fill=(10, 10, 12), font=font_bold)

        # Secondary Button
        draw.rectangle([192, btn_y, 358, btn_y + btn_h], outline=CARD_BORDER, width=1)
        draw.text((226, btn_y + 13), "Inspect PR", fill=TEXT_MUTED, font=font_bold)

        # The Defective / Healed element: visor-el-04 (Promo banner)
        if not healed:
            # Defect: Fixed/colliding element overlapping right over the CTA button!
            # Occurs at y=214, overlapping btn_y=224, occluding the primary CTA button (V_r = 0.62)
            banner_y = 212
            banner_h = 60
            draw.rectangle([14, banner_y, 360, banner_y + banner_h], fill=(36, 18, 28), outline=(244, 63, 94), width=2)
            draw.text((24, banner_y + 12), "⚡ FLASH SALE · 50% OFF SUBSCRIPTION", fill=(255, 255, 255), font=font_bold)
            draw.text((24, banner_y + 32), "Fixed container overlapping interactive CTA buttons", fill=(244, 63, 94), font=font_xs)

            # Mask: Exact defect collision region
            mask[banner_y:banner_y + banner_h, 14:360] = 1
            content_start_y = 290
        else:
            # Healed: Flow container moved cleanly below the CTA button with relative positioning
            banner_y = 282
            banner_h = 52
            draw.rectangle([14, banner_y, 360, banner_y + banner_h], fill=(20, 26, 36), outline=(16, 185, 129), width=1)
            draw.text((24, banner_y + 10), "⚡ FLASH SALE · 50% OFF SUBSCRIPTION", fill=(255, 255, 255), font=font_bold)
            draw.text((24, banner_y + 28), "Flow container in relative position (zero collision)", fill=(16, 185, 129), font=font_xs)
            content_start_y = 350

        # Feature Cards (responsive grid)
        card_h = 96
        y_c1 = content_start_y
        draw.rectangle([14, y_c1, 360, y_c1 + card_h], fill=CARD_BG, outline=CARD_BORDER, width=1)
        draw.rectangle([26, y_c1 + 14, 46, y_c1 + 34], fill=(0, 240, 255))
        draw.text((54, y_c1 + 16), "Meta SAM 3.1 Optical Vision", fill=TEXT_PRIMARY, font=font_bold)
        draw.text((26, y_c1 + 44), "Extracts DOM geometry & pixel occlusion ratios (V_r)\nwithout brittle pixel diffing.", fill=TEXT_MUTED, font=font_xs)

        y_c2 = y_c1 + card_h + 12
        if y_c2 + card_h < height - 60:
            draw.rectangle([14, y_c2, 360, y_c2 + card_h], fill=CARD_BG, outline=CARD_BORDER, width=1)
            draw.rectangle([26, y_c2 + 14, 46, y_c2 + 34], fill=(16, 185, 129))
            draw.text((54, y_c2 + 16), "Deterministic 3-Strike FSM", fill=TEXT_PRIMARY, font=font_bold)
            draw.text((26, y_c2 + 44), "Verifies dual-viewport resolution before pushing\na real commit to GitHub PR.", fill=TEXT_MUTED, font=font_xs)

        # Bottom Navigation Bar
        draw.rectangle([0, height - 56, width, height], fill=(17, 18, 23))
        draw.line([(0, height - 56), (width, height - 56)], fill=CARD_BORDER, width=1)
        icons = ("Home", "Scans", "Anomalies", "Settings")
        step_w = width // len(icons)
        for idx, ic in enumerate(icons):
            cx = idx * step_w + step_w // 2
            draw.rectangle([cx - 8, height - 44, cx + 8, height - 28], outline=TEXT_MUTED if idx > 0 else (0, 240, 255), width=1)
            draw.text((cx - 14, height - 20), ic, fill=(0, 240, 255) if idx == 0 else TEXT_DIM, font=font_xs)

    else:
        # Desktop Layout (1440x900)
        # Top banner on desktop has ample room, no collision
        draw.rectangle([80, 80, width - 80, 116], fill=(20, 26, 36), outline=(0, 240, 255) if not healed else (16, 185, 129), width=1)
        draw.text((96, 92), "⚡ FLASH SALE · 50% OFF SUBSCRIPTION — Desktop viewport preserved with zero occlusion (BR-3 compliant)", fill=TEXT_PRIMARY, font=font_bold)

        # 2-column Hero
        # Left column
        draw.rectangle([80, 148, 360, 172], fill=(18, 22, 32), outline=(0, 240, 255), width=1)
        draw.text((88, 153), "✦ Autonomous Visual Self-Healing · Dual Viewport", fill=(0, 240, 255), font=font_xs)

        draw.text((80, 188), "Next-Generation Visual QA\n& Layout Self-Healing Agent", fill=TEXT_PRIMARY, font=font_title)
        draw.text((80, 268), "Detects pixel-level regressions with Meta SAM 3.1 & heals CSS layout defects\nwith Muse models. Verified across mobile 375×812 and desktop 1440×900.", fill=TEXT_MUTED, font=font_sub)

        # Desktop Buttons
        draw.rectangle([80, 332, 280, 378], fill=(0, 240, 255), outline=(0, 200, 220))
        draw.text((120, 347), "Run Optical QA Scan", fill=(10, 10, 12), font=font_bold)
        draw.rectangle([300, 332, 480, 378], outline=CARD_BORDER, width=1)
        draw.text((345, 347), "View Architecture", fill=TEXT_MUTED, font=font_bold)

        # Right Column Mock Graphic
        draw.rectangle([720, 148, width - 80, 440], fill=CARD_BG, outline=CARD_BORDER, width=1)
        draw.rectangle([720, 148, width - 80, 184], fill=(17, 18, 23))
        draw.text((740, 158), "Autonomous Pipeline Inspection Monitor", fill=TEXT_PRIMARY, font=font_bold)
        # Mock timeline steps
        nodes = ("1.SENSE", "2.TRIAGE", "3.DIAGNOSE", "4.PATCH", "5.VERIFY")
        step_box_w = (width - 80 - 740 - 40) // 5
        for i, nd in enumerate(nodes):
            nx = 740 + i * (step_box_w + 8)
            draw.rectangle([nx, 204, nx + step_box_w, 244], fill=(24, 30, 42), outline=(16, 185, 129), width=1)
            draw.text((nx + 8, 218), nd, fill=(16, 185, 129), font=font_xs)

        # Metrics readouts in right card
        draw.rectangle([740, 264, width - 100, 410], fill=(13, 14, 18), outline=CARD_BORDER, width=1)
        draw.text((760, 280), "Mathematical Traps & Thresholds:", fill=TEXT_PRIMARY, font=font_bold)
        draw.text((760, 310), "• Visibility Ratio V_r ≥ 0.98 (pass) | V_r < 0.85 (fail)", fill=(16, 185, 129), font=font_sub)
        draw.text((760, 335), "• Collision IoU = 0.00 (pass) | IoU > 0.05 (defect)", fill=(16, 185, 129), font=font_sub)
        draw.text((760, 360), "• Horizontal Bleed Δx ≤ 2.0px (pass)", fill=(16, 185, 129), font=font_sub)

        # Feature Cards Row
        card_w = (width - 160 - 32) // 3
        card_y = 470
        features = [
            ("Meta SAM 3.1 Segmentation", "Zero brittle pixel diffing. Identifies UI bounding boxes and segmentation masks directly in memory."),
            ("Muse AST CSS Healer", "Generates safe, context-verified unified diffs targeting parent container layouts without !important hacks."),
            ("Real GitHub PR Push", "Pushes clean verified commits directly to the PR branch and publishes telemetry markdown reviews."),
        ]
        for i, (title, desc) in enumerate(features):
            cx = 80 + i * (card_w + 16)
            draw.rectangle([cx, card_y, cx + card_w, card_y + 160], fill=CARD_BG, outline=CARD_BORDER, width=1)
            draw.rectangle([cx + 16, card_y + 16, cx + 40, card_y + 40], fill=(0, 240, 255) if i == 0 else (16, 185, 129))
            draw.text((cx + 48, card_y + 20), title, fill=TEXT_PRIMARY, font=font_bold)
            draw.text((cx + 16, card_y + 54), desc, fill=TEXT_MUTED, font=font_xs)

        # Footer
        draw.rectangle([0, height - 50, width, height], fill=(14, 15, 19))
        draw.line([(0, height - 50), (width, height - 50)], fill=CARD_BORDER, width=1)
        draw.text((80, height - 32), "© 2026 VisorQA — Autonomous Visual QA & Self-Healing Agent. All rights reserved.", fill=TEXT_DIM, font=font_xs)
        draw.text((width - 320, height - 32), "Engine: Active · SAM 3.1 Online · HMR Observed", fill=(16, 185, 129), font=font_xs)

    return img, mask


def png_bytes(img: Image.Image) -> bytes:
    """Serialize PIL image to PNG bytes."""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def mask_png_bytes(mask: np.ndarray) -> bytes:
    """Serialize 2D numpy mask to PNG bytes."""
    return png_bytes(Image.fromarray((mask * 255).astype(np.uint8), mode="L"))

