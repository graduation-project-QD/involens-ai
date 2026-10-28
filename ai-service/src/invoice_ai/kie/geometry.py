"""Polygon helpers: upright rotation, overlap and simple reading order."""

from __future__ import annotations

import math
from collections.abc import Sequence

import cv2
import numpy as np

Point = tuple[float, float]
Polygon = tuple[Point, ...]


def rotated_size(width: int, height: int, angle_cw: float) -> tuple[int, int]:
    """Canvas size after rotating clockwise with expansion (same as PIL ``rotate(-angle, expand=True)``)."""
    theta = math.radians(angle_cw)
    cos, sin = abs(math.cos(theta)), abs(math.sin(theta))
    return int(round(width * cos + height * sin)), int(round(width * sin + height * cos))


def upright_affine(width: int, height: int, angle_cw: float) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """2x3 affine (continuous pixel coordinates) mapping the source image into the expanded upright canvas.

    Single source of truth for both image warping and annotation rotation.
    """
    new_width, new_height = rotated_size(width, height, angle_cw)
    theta = math.radians(angle_cw)
    cos, sin = math.cos(theta), math.sin(theta)
    # Snap exact right angles so 90/180/270 stay integer (lossless) transforms.
    cos, sin = (round(cos) if abs(cos - round(cos)) < 1e-12 else cos), (round(sin) if abs(sin - round(sin)) < 1e-12 else sin)
    tx = new_width / 2 - (cos * width / 2 - sin * height / 2)
    ty = new_height / 2 - (sin * width / 2 + cos * height / 2)
    return (cos, -sin, tx), (sin, cos, ty)


def rotate_points(points: Sequence[Sequence[float]], width: int, height: int, angle_cw: float) -> Polygon:
    """Map points of the source image into the upright frame.

    ``angle_cw`` is ``rotation_to_upright`` from the labeler: degrees clockwise (CSS ``rotate``).
    """
    if angle_cw % 360 == 0:
        return tuple((float(x), float(y)) for x, y in points)
    (a, b, c), (d, e, f) = upright_affine(width, height, angle_cw)
    return tuple((a * x + b * y + c, d * x + e * y + f) for x, y in points)


def flat_to_points(flat: Sequence[float]) -> Polygon:
    points = [(float(flat[i]), float(flat[i + 1])) for i in range(0, len(flat) - 1, 2)]
    if len(points) > 3 and points[0] == points[-1]:
        points.pop()
    return tuple(points)


def bbox(points: Sequence[Point]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def _hull(points: Sequence[Point]) -> np.ndarray:
    array = np.asarray(points, dtype=np.float32).reshape(-1, 1, 2)
    return cv2.convexHull(array)


def area(points: Sequence[Point]) -> float:
    return float(cv2.contourArea(_hull(points)))


def intersection_area(a: Sequence[Point], b: Sequence[Point]) -> float:
    ax0, ay0, ax1, ay1 = bbox(a)
    bx0, by0, bx1, by1 = bbox(b)
    if ax1 <= bx0 or bx1 <= ax0 or ay1 <= by0 or by1 <= ay0:
        return 0.0
    value, _ = cv2.intersectConvexConvex(_hull(a), _hull(b))
    return max(0.0, float(value))


def interpolate_quad(quad: Sequence[Point], start: float, end: float) -> Polygon:
    """Sub-quad of a text-line quad (tl, tr, br, bl) between fractions ``start`` and ``end`` of its width."""
    (tlx, tly), (trx, try_), (brx, bry), (blx, bly) = quad[:4]

    def lerp(p: Point, q: Point, t: float) -> Point:
        return p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t

    top_l, top_r = lerp((tlx, tly), (trx, try_), start), lerp((tlx, tly), (trx, try_), end)
    bot_r, bot_l = lerp((blx, bly), (brx, bry), end), lerp((blx, bly), (brx, bry), start)
    return top_l, top_r, bot_r, bot_l


def order_rows(boxes: Sequence[tuple[float, float, float, float]], overlap: float = 0.5) -> list[list[int]]:
    """Group upright boxes into rows (top to bottom), each row sorted left to right.

    A box joins the current row when its vertical overlap with the row band is at least
    ``overlap`` of the smaller height.
    """
    order = sorted(range(len(boxes)), key=lambda i: ((boxes[i][1] + boxes[i][3]) / 2, boxes[i][0]))
    rows: list[list[int]] = []
    band: tuple[float, float] | None = None
    for index in order:
        _, y0, _, y1 = boxes[index]
        if band is not None:
            inter = min(band[1], y1) - max(band[0], y0)
            if inter >= overlap * max(1e-6, min(band[1] - band[0], y1 - y0)):
                rows[-1].append(index)
                members = rows[-1]
                band = (
                    sum(boxes[i][1] for i in members) / len(members),
                    sum(boxes[i][3] for i in members) / len(members),
                )
                continue
        rows.append([index])
        band = (y0, y1)
    return [sorted(row, key=lambda i: boxes[i][0]) for row in rows]
