"""
VisorQA Domain Logic - Mathematical Discrepancy Engine (NumPy)
Equations for Visibility Ratio (V_r), Intersection over Union (IoU), and Viewport Bleed
"""

from typing import Tuple
import numpy as np

from backend.config import settings


def calculate_visibility_ratio(sam_mask: np.ndarray, dom_box_mask: np.ndarray) -> float:
    """
    Computes component visibility ratio V_r = Area(M_SAM) / Area(B_DOM).
    If V_r < 0.85, the element suffers from occlusion or z-index clipping.

    :param sam_mask: Binary 2D numpy array representing SAM 3.1 segmentation mask (M_SAM)
    :param dom_box_mask: Binary 2D numpy array representing DOM bounding box (B_DOM)
    :return: Visibility ratio between 0.0 and 1.0
    """
    dom_area = float(np.sum(dom_box_mask > 0))
    if dom_area == 0.0:
        return 1.0

    # SAM visible area within the DOM bounding box
    visible_intersection = float(np.sum(np.logical_and(sam_mask > 0, dom_box_mask > 0)))
    v_r = visible_intersection / dom_area
    return round(float(np.clip(v_r, 0.0, 1.0)), 4)


def calculate_iou(mask_a: np.ndarray, mask_b: np.ndarray) -> float:
    """
    Computes Intersection over Union (IoU) between two UI component masks:
    IoU = Area(M_i ∩ M_j) / Area(M_i ∪ M_j)
    If IoU > 0.05, the components collide / overlap illegally.

    :param mask_a: Binary 2D numpy array for component i
    :param mask_b: Binary 2D numpy array for component j
    :return: IoU score between 0.0 and 1.0
    """
    intersection = float(np.sum(np.logical_and(mask_a > 0, mask_b > 0)))
    union = float(np.sum(np.logical_or(mask_a > 0, mask_b > 0)))

    if union == 0.0:
        return 0.0

    iou = intersection / union
    return round(float(np.clip(iou, 0.0, 1.0)), 4)


def detect_bleed_overflow(mask: np.ndarray, viewport_shape: Tuple[int, int]) -> bool:
    """
    Detects if component pixel mask bleeds beyond expected viewport boundary.

    :param mask: Binary 2D mask of the component
    :param viewport_shape: (height, width) of the simulated device viewport
    :return: True if component bleeds outside viewport
    """
    h, w = viewport_shape
    mask_h, mask_w = mask.shape
    return mask_w > w or mask_h > h
