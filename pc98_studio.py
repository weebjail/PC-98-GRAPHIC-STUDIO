import sys
import os
import math
import ctypes

# Windows taskbar grouping ID so the pinned/taskbar icon persists
try:
    myappid = 'retro.pc98studio.graphics.1.0'
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
except Exception:
    pass

def resource_path(relative_path: str) -> str:
    """Resolves absolute path to resource, working for dev and PyInstaller single-file."""
    base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)

print("=" * 55)
print("[PC-98 STUDIO] [1/4] Starting Python runtime...")
print(f"[PC-98 STUDIO] Executable: {sys.executable}")

try:
    import numpy as np
    from PIL import Image, ImageEnhance, ImageFilter
    print("[PC-98 STUDIO] [2/4] NumPy and Pillow loaded.")
except ImportError as e:
    print(f"\n[ERROR] Missing core library: {e}")
    print("Please run: venv\\Scripts\\pip install numpy pillow PyQt6")
    input("\nPress Enter to exit...")
    sys.exit(1)

try:
    from PyQt6.QtCore import Qt, QSize, pyqtSignal, QPoint, QPointF, QRect, QRectF
    from PyQt6.QtGui import (
        QImage, QPixmap, QColor, QIcon, QPainter, QCursor,
        QPen, QBrush, QFont, QKeySequence, QShortcut,
        QConicalGradient, QPainterPath
    )
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QPushButton, QSlider, QComboBox, QCheckBox, QFileDialog,
        QGroupBox, QScrollArea, QColorDialog, QSplitter, QMessageBox, QSpinBox,
        QStyle, QStyleOptionSlider
    )
    print("[PC-98 STUDIO] [3/4] PyQt6 GUI engine loaded.")
except ImportError as e:
    print(f"\n[ERROR] PyQt6 failed to load: {e}")
    print("Please run: venv\\Scripts\\pip install PyQt6")
    input("\nPress Enter to exit...")
    sys.exit(1)


# --- Bayer Matrices for Dithering ---
def get_bayer_matrix(n: int) -> np.ndarray:
    if n == 2:
        return np.array([[0, 2], [3, 1]], dtype=np.float32)
    sub = get_bayer_matrix(n // 2)
    top = np.hstack([4 * sub, 4 * sub + 2])
    bot = np.hstack([4 * sub + 3, 4 * sub + 1])
    return np.vstack([top, bot])

BAYER_2X2 = get_bayer_matrix(2) / 4.0 - 0.5
BAYER_4X4 = get_bayer_matrix(4) / 16.0 - 0.5
BAYER_8X8 = get_bayer_matrix(8) / 64.0 - 0.5

# Authentic PC-98 Hardware Palettes
YUNO_PALETTE = np.array([
    [0, 0, 0], [153, 170, 187], [255, 255, 255], [119, 51, 51],
    [187, 119, 102], [238, 170, 153], [255, 221, 204], [85, 102, 204],
    [187, 204, 255], [34, 34, 34], [68, 68, 68], [85, 102, 102],
    [51, 153, 136], [255, 187, 102], [221, 68, 85], [255, 153, 170]
], dtype=np.uint8)

POSSESSIONER_PALETTE = np.array([
    [0, 0, 0], [187, 187, 187], [255, 255, 255], [136, 68, 34],
    [204, 102, 85], [238, 153, 136], [255, 187, 170], [0, 51, 102],
    [34, 119, 136], [34, 170, 187], [68, 119, 68], [34, 153, 68],
    [153, 187, 136], [255, 204, 0], [119, 0, 51], [238, 0, 0]
], dtype=np.uint8)

ACCENT_RAMPS = {
    'purple': np.array([[85, 34, 119], [136, 51, 170], [187, 85, 221], [238, 170, 255]], dtype=np.uint8),
    'green': np.array([[17, 68, 34], [34, 136, 68], [68, 204, 102], [170, 255, 187]], dtype=np.uint8),
    'red': np.array([[102, 17, 34], [170, 34, 51], [238, 51, 68], [255, 153, 170]], dtype=np.uint8),
    'blue': np.array([[17, 34, 85], [34, 85, 170], [51, 153, 238], [170, 221, 255]], dtype=np.uint8),
}

MASTER_SKIN_RAMP = np.array([
    [85,  34,  34],   # Deep terracotta contour shadow
    [136, 51,  51],   # Deep reddish shadow
    [170, 85,  68],   # Rich warm terracotta
    [204, 119, 85],   # Deep warm orange flesh
    [221, 153, 119],  # Core healthy natural orange midtone
    [238, 187, 153],  # Soft peach
    [255, 204, 170],  # Pale warm blush highlight
    [255, 238, 187],  # Bright warm creamy yellow highlight
], dtype=np.float32)


def snap_to_rgb444(palette: np.ndarray) -> np.ndarray:
    return np.clip(np.round(palette.astype(np.float32) / 17.0) * 17, 0, 255).astype(np.uint8)


def is_plausible_skin(r: int, g: int, b: int) -> bool:
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    if not (65 <= lum <= 230):
        return False
    if not (r > g and g >= b):
        return False
    rg = r - g
    gb = g - b
    if not (14 <= rg <= 80) or not (10 <= gb <= 65):
        return False
    diff = r - b
    sat = diff / max(1.0, float(r))
    return 0.15 <= sat <= 0.70


def build_skin_ramp_8(base_pal: np.ndarray) -> np.ndarray:
    skins = []
    for c in base_pal:
        if is_plausible_skin(int(c[0]), int(c[1]), int(c[2])):
            skins.append(c.astype(np.float32))

    if len(skins) > 0:
        avg_skin = np.mean(skins, axis=0)
        ref_mid = MASTER_SKIN_RAMP[4]
        delta = np.clip((avg_skin - ref_mid) * 0.35, -20.0, 20.0)
        weights = np.array([0.0, 0.2, 0.6, 1.0, 1.0, 0.7, 0.3, 0.0], dtype=np.float32)[:, None]
        ramp = MASTER_SKIN_RAMP + delta[None, :] * weights
        return snap_to_rgb444(np.clip(ramp, 0, 255))
    else:
        return snap_to_rgb444(MASTER_SKIN_RAMP)


def resample_non_skin_colors(candidate_pal: np.ndarray, excluded_colors: list, num_needed: int) -> list:
    filtered = []
    for c in candidate_pal:
        dists = [np.linalg.norm(c.astype(float) - np.array(exc).astype(float)) for exc in excluded_colors]
        if min(dists) > 24.0:
            filtered.append(c.astype(np.float32))

    if len(filtered) == 0:
        filtered = [
            np.array([0, 0, 0], dtype=np.float32),
            np.array([34, 34, 51], dtype=np.float32),
            np.array([68, 68, 85], dtype=np.float32),
            np.array([102, 102, 119], dtype=np.float32),
            np.array([136, 136, 153], dtype=np.float32),
            np.array([170, 187, 204], dtype=np.float32),
            np.array([204, 221, 238], dtype=np.float32),
            np.array([255, 255, 255], dtype=np.float32),
        ]

    chosen = []
    has_black = any(np.linalg.norm(np.array(exc).astype(float) - np.array([0, 0, 0])) < 22.0 for exc in excluded_colors)
    if not has_black:
        chosen.append(np.array([0, 0, 0], dtype=np.float32))

    has_white = any(np.linalg.norm(np.array(exc).astype(float) - np.array([255, 255, 255])) < 25.0 for exc in excluded_colors)
    filtered_arr = np.array(filtered)
    lums = 0.299 * filtered_arr[:, 0] + 0.587 * filtered_arr[:, 1] + 0.114 * filtered_arr[:, 2]
    brightest_idx = np.argmax(lums)
    if not has_white and lums[brightest_idx] > 180.0:
        chosen.append(filtered[brightest_idx])

    cands = [f for i, f in enumerate(filtered) if not any(np.array_equal(f, ch) for ch in chosen)]

    while len(chosen) < num_needed and len(cands) > 0:
        c_arr = np.array(cands)
        ch_arr = np.array(chosen)
        dists = np.linalg.norm(c_arr[:, None, :] - ch_arr[None, :, :], axis=2)
        min_dists = np.min(dists, axis=1)

        c_lums = 0.299 * c_arr[:, 0] + 0.587 * c_arr[:, 1] + 0.114 * c_arr[:, 2]
        ch_lums = 0.299 * ch_arr[:, 0] + 0.587 * ch_arr[:, 1] + 0.114 * ch_arr[:, 2]
        lum_spread = np.min(np.abs(c_lums[:, None] - ch_lums[None, :]), axis=1)

        c_sats = np.max(c_arr, axis=1) - np.min(c_arr, axis=1)

        scores = min_dists + 0.45 * lum_spread + 0.20 * c_sats
        best_idx = np.argmax(scores)
        chosen.append(cands.pop(best_idx))

    fallback_spectrum = [
        [0, 0, 0], [255, 255, 255], [34, 34, 51], [68, 85, 102],
        [153, 170, 187], [102, 51, 85], [51, 102, 102], [221, 221, 238],
        [51, 51, 68], [119, 136, 153], [85, 102, 119], [187, 204, 221]
    ]
    for fb in fallback_spectrum:
        if len(chosen) >= num_needed:
            break
        arr_fb = np.array(fb, dtype=np.float32)
        if min(np.linalg.norm(arr_fb - ch) for ch in chosen) > 20.0:
            chosen.append(arr_fb)

    return [np.array(c, dtype=np.uint8) for c in chosen[:num_needed]]


def build_skin_accent_palette(base_pal: np.ndarray, hue_type: str, num_colors: int = 16, skin_focus: bool = False) -> np.ndarray:
    skin_ramp = build_skin_ramp_8(base_pal)
    accent_ramp = ACCENT_RAMPS[hue_type]

    if num_colors == 8:
        out = np.zeros((8, 3), dtype=np.uint8)
        out[0] = [0, 0, 0]
        out[1:4] = skin_ramp[1:4]
        out[4:7] = accent_ramp[1:4]
        out[7] = [255, 255, 255]
        return snap_to_rgb444(out)

    if skin_focus:
        chosen_skins = list(skin_ramp[:8])
        chosen_accents = list(accent_ramp[:4])
        excluded = chosen_skins + chosen_accents
        other_extras = resample_non_skin_colors(base_pal, excluded, 4)
        full = chosen_skins + chosen_accents + other_extras
        return snap_to_rgb444(np.array(full, dtype=np.uint8))
    else:
        chosen_skins = list(skin_ramp[::2])
        chosen_accents = list(accent_ramp[:4])
        excluded = chosen_skins + chosen_accents
        other_extras = resample_non_skin_colors(base_pal, excluded, 8)
        full = chosen_skins + chosen_accents + other_extras
        return snap_to_rgb444(np.array(full, dtype=np.uint8))


def apply_skin_focus_to_palette(pal: np.ndarray, base_pal: np.ndarray, num_colors: int = 16) -> np.ndarray:
    num_skin = num_colors // 2
    num_other = num_colors - num_skin

    skin_ramp = list(build_skin_ramp_8(base_pal)[:num_skin])
    other_colors = resample_non_skin_colors(pal, skin_ramp, num_other)
    other_colors.sort(key=lambda c: 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2])

    full = skin_ramp + other_colors
    res = np.zeros((16, 3), dtype=np.uint8)
    res[:num_colors] = np.array(full[:num_colors], dtype=np.uint8)
    return snap_to_rgb444(res)


def extract_balanced_palette(pil_img: Image.Image, k: int = 16) -> np.ndarray:
    small = pil_img.resize((320, 200), Image.Resampling.BILINEAR)
    quant_48 = small.quantize(colors=48, method=Image.Quantize.MEDIANCUT)
    pal_48 = np.array(quant_48.getpalette()[:48 * 3]).reshape(48, 3).astype(np.float32)

    lum = 0.299 * pal_48[:, 0] + 0.587 * pal_48[:, 1] + 0.114 * pal_48[:, 2]

    sorted_lum_idx = np.argsort(lum)
    darkest = pal_48[sorted_lum_idx[0]]
    brightest = pal_48[sorted_lum_idx[-1]]

    chosen = [darkest, brightest]
    cands = [pal_48[i] for i in range(len(pal_48)) if i != sorted_lum_idx[0] and i != sorted_lum_idx[-1]]

    while len(chosen) < k and len(cands) > 0:
        c_arr = np.array(cands)
        ch_arr = np.array(chosen)
        dists = np.linalg.norm(c_arr[:, None, :] - ch_arr[None, :, :], axis=2)
        min_dists = np.min(dists, axis=1)
        c_sats = np.max(c_arr, axis=1) - np.min(c_arr, axis=1)
        scores = min_dists + 0.15 * c_sats
        best_idx = np.argmax(scores)
        chosen.append(cands.pop(best_idx))

    while len(chosen) < k:
        chosen.append(np.array([128, 128, 128], dtype=np.float32))

    arr_chosen = np.array(chosen[:k], dtype=np.uint8)
    ch_lum = 0.299 * arr_chosen[:, 0] + 0.587 * arr_chosen[:, 1] + 0.114 * arr_chosen[:, 2]
    return arr_chosen[np.argsort(ch_lum)]


def adjust_palette_accents(base_pal: np.ndarray, mode: str) -> np.ndarray:
    out = base_pal.astype(np.float32).copy()
    for i in range(len(out)):
        r, g, b = out[i]
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        sat = max(r, g, b) - min(r, g, b)

        if sat > 18.0 and 22.0 < lum < 238.0:
            if mode == "vibrant":
                out[i] = np.clip(lum + (out[i] - lum) * 1.45, 0, 255)
            elif mode == "warm":
                out[i, 0] = np.clip(out[i, 0] * 1.18 + 10, 0, 255)
                out[i, 1] = np.clip(out[i, 1] * 1.05, 0, 255)
                out[i, 2] = np.clip(out[i, 2] * 0.82 - 8, 0, 255)
            elif mode == "cool":
                out[i, 0] = np.clip(out[i, 0] * 0.82 - 8, 0, 255)
                out[i, 1] = np.clip(out[i, 1] * 1.08, 0, 255)
                out[i, 2] = np.clip(out[i, 2] * 1.22 + 12, 0, 255)

    return np.clip(out, 0, 255).astype(np.uint8)


# --- Vectorized Fast HSL Color Engine ---
def fast_rgb_to_hsl(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Vectorized conversion of float32 RGB [0, 1] to HSL (H in [0, 360], S/L in [0, 1])."""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    maxc = np.maximum(np.maximum(r, g), b)
    minc = np.minimum(np.minimum(r, g), b)
    l = (maxc + minc) * 0.5
    delta = maxc - minc

    mask = delta > 1e-5
    s = np.zeros_like(l)
    denom = np.where(l <= 0.5, maxc + minc, 2.0 - maxc - minc)
    denom = np.where(mask, denom, 1.0)
    s[mask] = delta[mask] / denom[mask]

    h = np.zeros_like(l)
    delta_safe = np.where(mask, delta, 1.0)
    r_mask = mask & (maxc == r)
    g_mask = mask & (maxc == g) & (~r_mask)
    b_mask = mask & (maxc == b) & (~r_mask) & (~g_mask)

    h[r_mask] = ((g[r_mask] - b[r_mask]) / delta_safe[r_mask]) % 6.0
    h[g_mask] = ((b[g_mask] - r[g_mask]) / delta_safe[g_mask]) + 2.0
    h[b_mask] = ((r[b_mask] - g[b_mask]) / delta_safe[b_mask]) + 4.0
    h = h * 60.0
    return h, s, l


def fast_hsl_to_rgb(h: np.ndarray, s: np.ndarray, l: np.ndarray) -> np.ndarray:
    """Vectorized conversion of HSL to float32 RGB [0, 1] using direct sector masks."""
    h = h % 360.0
    s = np.clip(s, 0.0, 1.0)
    l = np.clip(l, 0.0, 1.0)

    c = (1.0 - np.abs(2.0 * l - 1.0)) * s
    x = c * (1.0 - np.abs(((h / 60.0) % 2.0) - 1.0))
    m = l - c * 0.5

    h_idx = (h / 60.0).astype(np.int32) % 6

    r = np.zeros_like(h)
    g = np.zeros_like(h)
    b = np.zeros_like(h)

    m0 = (h_idx == 0)
    m1 = (h_idx == 1)
    m2 = (h_idx == 2)
    m3 = (h_idx == 3)
    m4 = (h_idx == 4)
    m5 = (h_idx == 5)

    r[m0] = c[m0]; g[m0] = x[m0]
    r[m1] = x[m1]; g[m1] = c[m1]
    g[m2] = c[m2]; b[m2] = x[m2]
    g[m3] = x[m3]; b[m3] = c[m3]
    r[m4] = x[m4]; b[m4] = c[m4]
    r[m5] = c[m5]; b[m5] = x[m5]

    rgb = np.stack([r + m, g + m, b + m], axis=-1)
    return np.clip(rgb, 0.0, 1.0)


def compute_hue_weight_vectorized(h_arr: np.ndarray, soft_min: float, hard_min: float, hard_max: float, soft_max: float) -> np.ndarray:
    """Computes a C1 continuous weight [0, 1] for each hue given 4 angular limits."""
    ref = soft_min % 360.0
    t_h = (h_arr - ref) % 360.0
    t_hard_min = (hard_min - ref) % 360.0
    t_hard_max = (hard_max - ref) % 360.0
    t_soft_max = (soft_max - ref) % 360.0

    w = np.zeros_like(t_h, dtype=np.float32)

    if t_hard_min > 1e-4:
        mask_up = (t_h >= 0.0) & (t_h < t_hard_min)
        u = t_h[mask_up] / t_hard_min
        w[mask_up] = u * u * (3.0 - 2.0 * u)

    mask_plat = (t_h >= t_hard_min) & (t_h <= t_hard_max)
    w[mask_plat] = 1.0

    if t_soft_max > t_hard_max + 1e-4:
        mask_down = (t_h > t_hard_max) & (t_h <= t_soft_max)
        v = (t_soft_max - t_h[mask_down]) / (t_soft_max - t_hard_max)
        w[mask_down] = v * v * (3.0 - 2.0 * v)

    return w


def apply_hsl_transform(rgb_arr: np.ndarray, master_hsl: list, color_hsl_data: dict) -> np.ndarray:
    """Applies master HSL and selective 4-point range color adjustments to an RGB array."""
    is_master_zero = (master_hsl[0] == 0 and master_hsl[1] == 0 and master_hsl[2] == 0)
    has_color_active = any(
        d['shifts'][0] != 0 or d['shifts'][1] != 0 or d['shifts'][2] != 0
        for d in color_hsl_data.values()
    )
    if is_master_zero and not has_color_active:
        return rgb_arr

    arr_norm = rgb_arr.astype(np.float32) / 255.0
    h, s, l = fast_rgb_to_hsl(arr_norm)

    if has_color_active:
        tot_h_shift = np.zeros_like(h)
        tot_s_mult = np.ones_like(s)
        tot_l_shift = np.zeros_like(l)

        for data in color_hsl_data.values():
            dh, ds, dl = data['shifts']
            if dh == 0 and ds == 0 and dl == 0:
                continue
            p0, p1, p2, p3 = data['range']
            weight = compute_hue_weight_vectorized(h, p0, p1, p2, p3) * (s > 0.04)

            if dh != 0:
                tot_h_shift += weight * dh
            if ds != 0:
                tot_s_mult += weight * (ds / 100.0)
            if dl != 0:
                tot_l_shift += weight * (dl / 200.0)

        h = (h + tot_h_shift) % 360.0
        s = np.clip(s * np.maximum(0.0, tot_s_mult), 0.0, 1.0)
        l = np.clip(l + tot_l_shift, 0.0, 1.0)

    mh, ms, ml = master_hsl
    if mh != 0:
        h = (h + mh) % 360.0
    if ms != 0:
        s = np.clip(s * max(0.0, 1.0 + ms / 100.0), 0.0, 1.0)
    if ml != 0:
        if ml > 0:
            l = l + (1.0 - l) * (ml / 100.0)
        else:
            l = l * (1.0 + ml / 100.0)

    rgb_transformed = fast_hsl_to_rgb(h, s, l)
    return rgb_transformed * 255.0


# --- Interactive Photoshop/Affinity HSL Wheel Widget ---
class HSLColorWheel(QWidget):
    range_changed = pyqtSignal(list)
    range_editing_finished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(210, 210)
        self.setMouseTracking(True)

        self.color_key = 'master'
        self.color_range = [325.0, 342.5, 17.5, 35.0]

        self.r_outer = 84.0
        self.r_inner = 64.0
        self.handle_radius = 6.0

        self.active_handle = None
        self.hovered_handle = None
        self.last_drag_angle = 0.0

        self.wheel_pixmap = self.generate_wheel_pixmap(210, 210, self.r_outer, self.r_inner)

    def generate_wheel_pixmap(self, w: int, h: int, r_out: float, r_in: float) -> QPixmap:
        pix = QPixmap(w, h)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        cx, cy = w / 2.0, h / 2.0
        grad = QConicalGradient(cx, cy, 0.0)
        for deg in range(0, 361, 15):
            grad.setColorAt(deg / 360.0, QColor.fromHsvF(((360 - deg) % 360) / 360.0, 1.0, 1.0))

        path = QPainterPath()
        path.setFillRule(Qt.FillRule.OddEvenFill)
        path.addEllipse(QPointF(cx, cy), r_out, r_out)
        path.addEllipse(QPointF(cx, cy), r_in, r_in)
        painter.fillPath(path, QBrush(grad))

        painter.setPen(QPen(QColor(40, 40, 50, 180), 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), r_out, r_out)
        painter.drawEllipse(QPointF(cx, cy), r_in, r_in)
        painter.end()
        return pix

    def set_color_data(self, key: str, color_range: list):
        self.color_key = key
        self.color_range = list(color_range)
        self.active_handle = None
        self.update()

    def angle_to_point(self, r: float, deg: float) -> QPointF:
        cx, cy = self.width() / 2.0, self.height() / 2.0
        rad = math.radians(deg)
        return QPointF(cx + r * math.cos(rad), cy + r * math.sin(rad))

    def get_handle_positions(self) -> list:
        p0, p1, p2, p3 = self.color_range
        return [
            self.angle_to_point(self.r_outer, p0),
            self.angle_to_point(self.r_inner, p1),
            self.angle_to_point(self.r_inner, p2),
            self.angle_to_point(self.r_outer, p3),
        ]

    def hit_test_handle(self, pt: QPointF):
        if self.color_key == 'master':
            return None
        positions = self.get_handle_positions()
        for idx, h_pos in enumerate(positions):
            dist = math.hypot(pt.x() - h_pos.x(), pt.y() - h_pos.y())
            # Generous 16.5px hit radius (increased from 10px) for effortless clicking and dragging
            if dist <= self.handle_radius + 10.5:
                return idx
        return None

    def is_on_hard_arc(self, pt: QPointF) -> bool:
        if self.color_key == 'master':
            return False
        cx, cy = self.width() / 2.0, self.height() / 2.0
        dist = math.hypot(pt.x() - cx, pt.y() - cy)
        if not (self.r_inner - 10.0 <= dist <= self.r_outer + 10.0):
            return False

        angle = (math.degrees(math.atan2(pt.y() - cy, pt.x() - cx))) % 360.0
        p1, p2 = self.color_range[1], self.color_range[2]
        rel_angle = (angle - p1) % 360.0
        span = (p2 - p1) % 360.0
        return rel_angle <= span

    def update_handle_position(self, handle_idx: int, new_angle: float):
        p = list(self.color_range)
        d_hard = (p[2] - p[1]) % 360.0
        center = (p[1] + d_hard * 0.5) % 360.0
        anti_center = (center + 180.0) % 360.0

        q = [(x - anti_center) % 360.0 for x in p]
        q_new = (new_angle - anti_center) % 360.0
        min_gap = 2.0

        if handle_idx == 0:
            q[0] = min(q_new, q[1] - min_gap)
        elif handle_idx == 1:
            q[1] = max(q[0] + min_gap, min(q_new, q[2] - min_gap))
        elif handle_idx == 2:
            q[2] = max(q[1] + min_gap, min(q_new, q[3] - min_gap))
        elif handle_idx == 3:
            q[3] = max(q[2] + min_gap, q_new)

        self.color_range = [(val + anti_center) % 360.0 for val in q]
        self.range_changed.emit(self.color_range)

    def rotate_range(self, delta_deg: float):
        self.color_range = [(x + delta_deg) % 360.0 for x in self.color_range]
        self.range_changed.emit(self.color_range)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pt = event.position()
            hit_idx = self.hit_test_handle(pt)
            if hit_idx is not None:
                self.active_handle = hit_idx
            elif self.is_on_hard_arc(pt):
                self.active_handle = 'arc'
                cx, cy = self.width() / 2.0, self.height() / 2.0
                self.last_drag_angle = (math.degrees(math.atan2(pt.y() - cy, pt.x() - cx))) % 360.0
            self.update()

    def mouseMoveEvent(self, event):
        pt = event.position()
        cx, cy = self.width() / 2.0, self.height() / 2.0
        cur_angle = (math.degrees(math.atan2(pt.y() - cy, pt.x() - cx))) % 360.0

        if self.active_handle is not None and self.color_key != 'master':
            if isinstance(self.active_handle, int):
                self.update_handle_position(self.active_handle, cur_angle)
            elif self.active_handle == 'arc':
                delta = (cur_angle - self.last_drag_angle)
                norm_delta = (delta + 180.0) % 360.0 - 180.0
                self.rotate_range(norm_delta)
                self.last_drag_angle = cur_angle
            self.update()
        else:
            old_hover = self.hovered_handle
            self.hovered_handle = self.hit_test_handle(pt)
            if self.hovered_handle is not None:
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            elif self.is_on_hard_arc(pt):
                self.setCursor(Qt.CursorShape.SizeAllCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            if old_hover != self.hovered_handle:
                self.update()

    def mouseReleaseEvent(self, event):
        if self.active_handle is not None:
            self.active_handle = None
            self.range_editing_finished.emit()
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.drawPixmap(0, 0, self.wheel_pixmap)

        if self.color_key == 'master':
            painter.setPen(QColor(130, 140, 160))
            font = QFont("Segoe UI", 11, QFont.Weight.Bold)
            painter.setFont(font)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "ALL")
            painter.end()
            return

        p0, p1, p2, p3 = self.color_range
        pts = self.get_handle_positions()

        span = (p2 - p1) % 360.0
        steps = max(2, int(span / 3.0))
        path = QPainterPath()
        path.moveTo(pts[0])
        path.lineTo(pts[1])
        for i in range(1, steps + 1):
            deg = (p1 + (span * i / steps)) % 360.0
            path.lineTo(self.angle_to_point(self.r_inner, deg))
        path.lineTo(pts[3])

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(15, 15, 20, 220), 4.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawPath(path)
        painter.setPen(QPen(QColor(255, 255, 255, 240), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawPath(path)

        for i, pos in enumerate(pts):
            is_active = (i == self.active_handle or i == self.hovered_handle)
            r = self.handle_radius + (1.5 if is_active else 0.0)

            painter.setPen(QPen(QColor(20, 20, 25), 1.5))
            fill_color = QColor(255, 255, 255) if is_active else QColor(215, 220, 230)
            painter.setBrush(QBrush(fill_color))
            painter.drawEllipse(pos, r, r)

        painter.end()


# --- Custom Interactive Swatch Button ---
class ColorOptionButton(QPushButton):
    def __init__(self, key: str, color_hex: str | None = None, is_master: bool = False, parent=None):
        super().__init__(parent)
        self.key = key
        self.color_hex = color_hex
        self.is_master = is_master
        self.is_selected = False
        self.current_qcolor = QColor(color_hex) if color_hex else None
        self.setFixedSize(28, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def setSelected(self, selected: bool):
        self.is_selected = selected
        self.update()

    def set_color_from_hue(self, hue_deg: float):
        if not self.is_master:
            self.current_qcolor = QColor.fromHslF((hue_deg % 360.0) / 360.0, 1.0, 0.5)
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        cx, cy = self.width() / 2.0, self.height() / 2.0

        if self.is_master:
            grad = QConicalGradient(cx, cy, 0.0)
            for deg in range(0, 361, 30):
                grad.setColorAt(deg / 360.0, QColor.fromHsvF(((360 - deg) % 360) / 360.0, 1.0, 1.0))
            painter.setBrush(QBrush(grad))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(cx, cy), 11.5, 11.5)
        else:
            col = self.current_qcolor if self.current_qcolor else QColor(self.color_hex)
            painter.setBrush(QBrush(col))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(cx, cy), 11.5, 11.5)

        if self.is_selected:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(255, 255, 255), 2.5))
            painter.drawEllipse(QPointF(cx, cy), 12.5, 12.5)
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(45, 45, 55), 1.0))
            painter.drawEllipse(QPointF(cx, cy), 12.0, 12.0)

        painter.end()


# --- Wheel-Proof Controls for Scroll Areas ---
class NoWheelComboBox(QComboBox):
    def wheelEvent(self, event):
        event.ignore()


class NoWheelSpinBox(QSpinBox):
    def wheelEvent(self, event):
        event.ignore()


# --- Interactive Clickable Number SpinBox for Sliders ---
class ValueSpinBox(QSpinBox):
    def __init__(self, min_val: int, max_val: int, default_val: int, suffix: str = "", parent=None):
        super().__init__(parent)
        self.setRange(min_val, max_val)
        self.setValue(default_val)
        self.setSuffix(suffix)
        self.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setFixedWidth(54)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.setStyleSheet("""
            QSpinBox {
                background-color: #24242e;
                border: 1px solid #3a3a48;
                border-radius: 3px;
                color: #ffffff;
                font-family: 'Segoe UI', Arial;
                font-size: 11px;
                font-weight: bold;
                padding: 1px 3px;
            }
            QSpinBox:hover {
                border-color: #555566;
            }
            QSpinBox:focus {
                border: 1px solid #5a88c8;
                background-color: #1a1a24;
            }
        """)

    def wheelEvent(self, event):
        event.ignore()

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self.selectAll()

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.selectAll()


class ResetableSlider(QSlider):
    reset_requested = pyqtSignal()

    def __init__(self, orientation=Qt.Orientation.Horizontal, default_val=0, parent=None):
        super().__init__(orientation, parent)
        self.default_val = default_val

    def wheelEvent(self, event):
        event.ignore()

    def mouseDoubleClickEvent(self, event):
        self.setValue(self.default_val)
        self.reset_requested.emit()
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            opt = QStyleOptionSlider()
            self.initStyleOption(opt)
            sr = self.style().subControlRect(
                QStyle.ComplexControl.CC_Slider, opt,
                QStyle.SubControl.SC_SliderHandle, self
            )
            # Generous hit area around the circular slider handle (+12 pixels radius)
            expanded_rect = sr.adjusted(-12, -12, 12, 12)
            if expanded_rect.contains(event.position().toPoint()):
                super().mousePressEvent(event)
            else:
                handle_half = sr.width() / 2.0
                track_len = max(1.0, float(self.width() - sr.width()))
                rel_x = max(0.0, min(track_len, event.position().x() - handle_half))
                val_range = self.maximum() - self.minimum()
                new_val = int(round(self.minimum() + (rel_x / track_len) * val_range))
                self.setValue(new_val)
                super().mousePressEvent(event)
        else:
            super().mousePressEvent(event)


class ZoomablePreviewCanvas(QWidget):
    zoom_changed = pyqtSignal(float)
    pan_changed = pyqtSignal(float, float)
    load_image_requested = pyqtSignal()

    def __init__(self, title="PC-98 STUDIO", parent=None):
        super().__init__(parent)
        self.title = title
        self.current_qimg = None
        self.aspect_stretch = 1.0

        self.zoom_factor = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0

        self.is_dragging = False
        self.last_mouse_pos = QPoint()
        self.setMouseTracking(True)
        self.setStyleSheet("""
            ZoomablePreviewCanvas {
                background-color: #121214;
                border: 1px solid #2a2a2e;
                border-radius: 4px;
            }
        """)

        self.empty_overlay = QWidget(self)
        self.empty_overlay.setStyleSheet("background: transparent; border: none;")
        empty_layout = QVBoxLayout(self.empty_overlay)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.setSpacing(14)

        display_title = "PC-98 STUDIO" if self.title in ("PC-98 STUDIO", "PC-98 EMULATION") else self.title
        self.lbl_empty_title = QLabel(display_title)
        self.lbl_empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_empty_title.setStyleSheet("""
            QLabel {
                border: none;
                background: transparent;
                color: #778899;
                font-family: 'Segoe UI', Arial;
                font-size: 18px;
                font-weight: bold;
                letter-spacing: 2px;
            }
        """)
        empty_layout.addWidget(self.lbl_empty_title)

        self.btn_empty_load = QPushButton("Load Image")
        self.btn_empty_load.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_empty_load.setStyleSheet("""
            QPushButton {
                background-color: #2a2a34;
                border: 1px solid #444455;
                border-radius: 4px;
                color: #dcdce0;
                font-family: 'Segoe UI', Arial;
                font-size: 12px;
                font-weight: bold;
                padding: 6px 18px;
            }
            QPushButton:hover {
                background-color: #383848;
                border-color: #667799;
                color: #ffffff;
            }
            QPushButton:pressed {
                background-color: #1f1f27;
            }
        """)
        self.btn_empty_load.clicked.connect(self.load_image_requested.emit)
        empty_layout.addWidget(self.btn_empty_load, alignment=Qt.AlignmentFlag.AlignCenter)

        self.update_empty_overlay()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.empty_overlay.setGeometry(self.rect())

    def update_empty_overlay(self):
        has_image = self.current_qimg is not None and not self.current_qimg.isNull()
        self.empty_overlay.setVisible(not has_image)

    def set_image(self, qimg: QImage, aspect_stretch: float = 1.0):
        self.current_qimg = qimg
        self.aspect_stretch = aspect_stretch
        self.update_empty_overlay()
        self.update()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self.zoom_factor = min(16.0, self.zoom_factor * 1.15)
            elif delta < 0:
                self.zoom_factor = max(0.05, self.zoom_factor / 1.15)

            if abs(self.zoom_factor - 1.0) < 0.03:
                self.pan_x = 0.0
                self.pan_y = 0.0

            self.zoom_changed.emit(self.zoom_factor)
            self.pan_changed.emit(self.pan_x, self.pan_y)
            self.update()
            event.accept()
        else:
            dy = event.angleDelta().y() * 0.75
            dx = event.angleDelta().x() * 0.75
            if self.zoom_factor > 1.0:
                self.pan_x += dx
                self.pan_y += dy
                self.pan_changed.emit(self.pan_x, self.pan_y)
                self.update()
            event.accept()

    def mousePressEvent(self, event):
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
            self.is_dragging = True
            self.last_mouse_pos = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()

    def mouseMoveEvent(self, event):
        if self.is_dragging:
            cur = event.position().toPoint()
            dx = cur.x() - self.last_mouse_pos.x()
            dy = cur.y() - self.last_mouse_pos.y()
            self.last_mouse_pos = cur
            self.pan_x += dx
            self.pan_y += dy
            self.pan_changed.emit(self.pan_x, self.pan_y)
            self.update()
            event.accept()
        else:
            self.setCursor(Qt.CursorShape.OpenHandCursor if self.zoom_factor > 1.0 else Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event):
        self.is_dragging = False
        self.setCursor(Qt.CursorShape.OpenHandCursor if self.zoom_factor > 1.0 else Qt.CursorShape.ArrowCursor)
        event.accept()

    def mouseDoubleClickEvent(self, event):
        self.zoom_factor = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.zoom_changed.emit(self.zoom_factor)
        self.pan_changed.emit(self.pan_x, self.pan_y)
        self.update()
        event.accept()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        vw, vh = self.width(), self.height()
        painter.fillRect(0, 0, vw, vh, QColor("#121214"))

        if self.current_qimg is None or self.current_qimg.isNull():
            painter.end()
            return

        iw = self.current_qimg.width()
        ih = self.current_qimg.height()
        eff_h = ih * self.aspect_stretch

        scale_fit = min(vw / iw, vh / eff_h)
        scale = scale_fit * self.zoom_factor

        dw = int(round(iw * scale))
        dh = int(round(eff_h * scale))

        cx = int(round(vw / 2.0 + self.pan_x))
        cy = int(round(vh / 2.0 + self.pan_y))

        dest_rect = QRect(cx - dw // 2, cy - dh // 2, dw, dh)
        painter.drawImage(dest_rect, self.current_qimg)
        painter.end()


class ScreenPickerOverlay(QWidget):
    color_picked = pyqtSignal(tuple)
    canceled = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.BlankCursor)

        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        self.dpr = screen.devicePixelRatio()
        geo = screen.geometry()
        self.setGeometry(geo)

        self.screenshot_pixmap = screen.grabWindow(0)
        self.screenshot_img = self.screenshot_pixmap.toImage()
        self.mouse_pos = QPoint(geo.width() // 2, geo.height() // 2)

    def mouseMoveEvent(self, event):
        self.mouse_pos = event.position().toPoint()
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            px = int(round(self.mouse_pos.x() * self.dpr))
            py = int(round(self.mouse_pos.y() * self.dpr))
            px = max(0, min(self.screenshot_img.width() - 1, px))
            py = max(0, min(self.screenshot_img.height() - 1, py))
            qcol = self.screenshot_img.pixelColor(px, py)
            self.color_picked.emit((qcol.red(), qcol.green(), qcol.blue()))
            self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.canceled.emit()
            self.close()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self.screenshot_pixmap)

        painter.fillRect(0, 0, self.width(), 32, QColor(15, 15, 22, 220))
        painter.setPen(QColor(240, 240, 255))
        font = QFont("Segoe UI", 10, QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(20, 21, "🔍 EYEDROPPER: Click anywhere to sample color | Press ESC to cancel")

        mx, my = self.mouse_pos.x(), self.mouse_pos.y()
        px = int(round(mx * self.dpr))
        py = int(round(my * self.dpr))
        px = max(0, min(self.screenshot_img.width() - 1, px))
        py = max(0, min(self.screenshot_img.height() - 1, py))
        curr_col = self.screenshot_img.pixelColor(px, py)

        loupe_radius = 56
        lx = mx + 25 if mx + loupe_radius * 2 + 50 < self.width() else mx - loupe_radius * 2 - 25
        ly = my + 25 if my + loupe_radius * 2 + 80 < self.height() else my - loupe_radius * 2 - 25

        grid_dim = 15
        half = grid_dim // 2
        sample_rect = QRect(px - half, py - half, grid_dim, grid_dim)
        cropped_sample = self.screenshot_img.copy(sample_rect)

        loupe_size = loupe_radius * 2
        painter.save()
        painter.setBrush(QBrush(QColor(0, 0, 0)))
        painter.setPen(QPen(QColor(255, 255, 255), 3))
        painter.drawEllipse(lx, ly, loupe_size, loupe_size)
        painter.setClipRegion(painter.clipRegion().united(QRect(lx, ly, loupe_size, loupe_size)))
        painter.drawImage(QRect(lx, ly, loupe_size, loupe_size), cropped_sample)

        painter.setPen(QPen(QColor(255, 0, 50, 220), 2))
        cx, cy = lx + loupe_radius, ly + loupe_radius
        cw = loupe_size / grid_dim
        painter.drawRect(int(cx - cw / 2), int(cy - cw / 2), int(cw), int(cw))
        painter.restore()

        badge_y = ly + loupe_size + 6
        painter.fillRect(lx - 10, badge_y, loupe_size + 20, 38, QColor(10, 10, 15, 240))
        painter.setPen(QPen(curr_col, 2))
        painter.drawRect(lx - 10, badge_y, loupe_size + 20, 38)

        painter.setBrush(QBrush(curr_col))
        painter.drawEllipse(lx - 2, badge_y + 9, 20, 20)
        painter.setPen(QColor(255, 255, 255))
        font.setPointSize(8)
        painter.setFont(font)
        hex_str = f"#{curr_col.red():02X}{curr_col.green():02X}{curr_col.blue():02X}"
        rgb_str = f"{curr_col.red()}, {curr_col.green()}, {curr_col.blue()}"
        painter.drawText(lx + 24, badge_y + 18, hex_str)
        painter.setPen(QColor(180, 180, 190))
        painter.drawText(lx + 24, badge_y + 31, rgb_str)

        painter.end()


class ColorSelectionDialog(QColorDialog):
    def __init__(self, initial_color, parent=None, title="Set Color"):
        super().__init__(initial_color, parent)
        self.setWindowTitle(title)
        self.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog, True)

        self.eyedropper_btn = None
        for btn in self.findChildren(QPushButton):
            txt = btn.text().replace("&", "").strip().lower()
            if "pick screen" in txt or "screen" in txt:
                self.eyedropper_btn = btn
                break

        if self.eyedropper_btn is not None:
            try:
                self.eyedropper_btn.clicked.disconnect()
            except Exception:
                pass
            self.eyedropper_btn.clicked.connect(self.start_loupe_eyedropper)
            self.eyedropper_btn.setText("🔍 Pick Screen Color (Magnifier)")
        else:
            self.eyedropper_btn = QPushButton("🔍 Pick Screen Color (Magnifier)")
            self.eyedropper_btn.clicked.connect(self.start_loupe_eyedropper)
            if self.layout() is not None:
                self.layout().addWidget(self.eyedropper_btn)

    def start_loupe_eyedropper(self):
        self.hide()
        self.overlay = ScreenPickerOverlay()
        self.overlay.color_picked.connect(self.on_color_picked)
        self.overlay.canceled.connect(self.on_eyedropper_canceled)
        self.overlay.show()

    def on_color_picked(self, rgb: tuple):
        self.setCurrentColor(QColor(int(rgb[0]), int(rgb[1]), int(rgb[2])))
        self.show()
        self.raise_()
        self.activateWindow()

    def on_eyedropper_canceled(self):
        self.show()
        self.raise_()
        self.activateWindow()


# --- Main Application Controller ---
class PC98Studio(QMainWindow):
    DEFAULT_COLOR_HSL = {
        'red':     {'shifts': [0, 0, 0], 'range': [325.0, 342.5, 17.5, 35.0]},
        'orange':  {'shifts': [0, 0, 0], 'range': [355.0, 12.5, 47.5, 65.0]},
        'yellow':  {'shifts': [0, 0, 0], 'range': [25.0, 42.5, 77.5, 95.0]},
        'green':   {'shifts': [0, 0, 0], 'range': [85.0, 102.5, 137.5, 155.0]},
        'cyan':    {'shifts': [0, 0, 0], 'range': [145.0, 162.5, 197.5, 215.0]},
        'blue':    {'shifts': [0, 0, 0], 'range': [205.0, 222.5, 257.5, 275.0]},
        'magenta': {'shifts': [0, 0, 0], 'range': [265.0, 282.5, 317.5, 335.0]}
    }

    SWATCH_DEFS = [
        ('master', None, True),
        ('red', '#e53935', False),
        ('orange', '#fb8c00', False),
        ('yellow', '#fdd835', False),
        ('green', '#43a047', False),
        ('cyan', '#00acc1', False),
        ('blue', '#1e88e5', False),
        ('magenta', '#d81b60', False),
    ]

    def __init__(self):
        super().__init__()
        self.setWindowTitle("PC-98 STUDIO")

        icon_path = resource_path("app_icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.resize(1260, 780)

        self.source_image = None
        self.cached_framed_image = None
        self.processed_indices = None
        self.original_image_palette = YUNO_PALETTE.copy()
        self.active_palette = YUNO_PALETTE.copy()
        self.generated_palettes = []

        self.selected_swatch_idx = 0
        self.locked_colors = [False] * 16
        self.all_sliders = []
        self.is_updating = False

        # Photoshop / Affinity style HSL state
        self.master_hsl = [0, 0, 0]
        self.color_hsl = {
            k: {'shifts': list(v['shifts']), 'range': list(v['range'])}
            for k, v in self.DEFAULT_COLOR_HSL.items()
        }
        self.current_color_key = 'master'
        self.swatch_buttons = {}

        # Undo State Tracking
        self.undo_stack = []
        self.committed_state = None
        self.is_undoing = False
        self.is_slider_down = False

        self.init_ui()
        self.apply_dark_theme()
        self.populate_palette_dropdown()

        self.undo_shortcut = QShortcut(QKeySequence.StandardKey.Undo, self)
        self.undo_shortcut.activated.connect(self.undo)

    def init_ui(self):
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(main_splitter)

        viewport_container = QWidget()
        v_layout = QVBoxLayout(viewport_container)
        v_layout.setContentsMargins(10, 10, 10, 10)

        top_bar = QHBoxLayout()
        self.compare_toggle = QCheckBox("Compare with Original")
        self.compare_toggle.setChecked(False)
        self.compare_toggle.stateChanged.connect(lambda: self.update_compare_layout())
        top_bar.addWidget(self.compare_toggle)

        self.compare_combo = NoWheelComboBox()
        self.compare_combo.addItems([
            "Above / Below (Original on Top)",
            "Side by Side (Original on Left)"
        ])
        self.compare_combo.currentIndexChanged.connect(lambda: self.update_compare_layout())
        self.compare_combo.setEnabled(False)
        top_bar.addWidget(self.compare_combo)

        self.lbl_split = QLabel("View Split:")
        top_bar.addWidget(self.lbl_split)
        self.slider_split = ResetableSlider(Qt.Orientation.Horizontal, default_val=50)
        self.slider_split.setRange(15, 85)
        self.slider_split.setValue(50)
        self.slider_split.setFixedWidth(80)
        self.slider_split.valueChanged.connect(self.on_split_slider_moved)
        self.slider_split.setEnabled(False)
        top_bar.addWidget(self.slider_split)

        self.spin_split = ValueSpinBox(15, 85, 50, "%")
        self.spin_split.setFixedWidth(46)
        self.spin_split.setEnabled(False)
        self.slider_split.valueChanged.connect(self.spin_split.setValue)
        self.spin_split.valueChanged.connect(self.slider_split.setValue)
        top_bar.addWidget(self.spin_split)

        top_bar.addSpacing(14)
        self.aspect_toggle = QCheckBox("CRT 1:1.2 Stretch")
        self.aspect_toggle.setChecked(False)
        self.aspect_toggle.toggled.connect(lambda: self.update_preview_display())
        top_bar.addWidget(self.aspect_toggle)

        top_bar.addSpacing(14)
        top_bar.addWidget(QLabel("Zoom:"))
        self.slider_view_zoom = ResetableSlider(Qt.Orientation.Horizontal, default_val=100)
        self.slider_view_zoom.setRange(5, 800)
        self.slider_view_zoom.setValue(100)
        self.slider_view_zoom.setFixedWidth(80)
        self.slider_view_zoom.valueChanged.connect(lambda v: self.set_viewport_zoom(v / 100.0))
        top_bar.addWidget(self.slider_view_zoom)

        self.spin_view_zoom = ValueSpinBox(5, 800, 100, "%")
        self.spin_view_zoom.setFixedWidth(52)
        self.slider_view_zoom.valueChanged.connect(self.spin_view_zoom.setValue)
        self.spin_view_zoom.valueChanged.connect(lambda v: self.set_viewport_zoom(v / 100.0))
        top_bar.addWidget(self.spin_view_zoom)

        btn_fit = QPushButton("↺ Fit")
        btn_fit.setToolTip("Reset Zoom to 100% (Fit) and center view")
        btn_fit.clicked.connect(lambda: self.set_viewport_zoom(1.0, reset_pan=True))
        top_bar.addWidget(btn_fit)

        top_bar.addStretch()
        v_layout.addLayout(top_bar)

        self.preview_splitter = QSplitter(Qt.Orientation.Vertical)
        self.preview_splitter.setHandleWidth(12)
        v_layout.addWidget(self.preview_splitter, stretch=1)

        self.canvas_orig = ZoomablePreviewCanvas(title="ORIGINAL SOURCE")
        self.canvas_orig.zoom_changed.connect(self.on_sync_zoom)
        self.canvas_orig.pan_changed.connect(self.on_sync_pan)
        self.canvas_orig.load_image_requested.connect(self.open_image)
        self.preview_splitter.addWidget(self.canvas_orig)
        self.canvas_orig.hide()

        self.canvas_edited = ZoomablePreviewCanvas(title="PC-98 STUDIO")
        self.canvas_edited.zoom_changed.connect(self.on_sync_zoom)
        self.canvas_edited.pan_changed.connect(self.on_sync_pan)
        self.canvas_edited.load_image_requested.connect(self.open_image)
        self.preview_splitter.addWidget(self.canvas_edited)

        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #888899;")
        v_layout.addWidget(self.status_label, alignment=Qt.AlignmentFlag.AlignRight)
        main_splitter.addWidget(viewport_container)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(490)
        controls_widget = QWidget()
        layout = QVBoxLayout(controls_widget)
        layout.setSpacing(10)

        # 1. Resolution & Framing
        io_group = QGroupBox("1. Resolution & Framing")
        io_layout = QVBoxLayout(io_group)
        btn_open = QPushButton("Open Source Image")
        btn_open.setStyleSheet("background-color: #2b3b52; font-weight: bold; padding: 8px;")
        btn_open.clicked.connect(self.open_image)
        io_layout.addWidget(btn_open)

        res_box = QHBoxLayout()
        res_box.addWidget(QLabel("Resolution Scale:"))
        self.res_combo = NoWheelComboBox()
        self.res_combo.addItems([
            "x1 Base (640x400 standard)",
            "x0.5 Half (320x200 low-res)",
            "x2 Double (1280x800)",
            "x4 Ultra (2560x1600)"
        ])
        self.res_combo.currentIndexChanged.connect(self.on_framing_changed)
        res_box.addWidget(self.res_combo)
        io_layout.addLayout(res_box)

        aspect_box = QHBoxLayout()
        aspect_box.addWidget(QLabel("Aspect Ratio Frame:"))
        self.crop_aspect_combo = NoWheelComboBox()
        self.crop_aspect_combo.addItems([
            "PC-98 Standard (16:10 / 640x400)",
            "Original",
            "Custom Dimensions"
        ])
        self.crop_aspect_combo.currentIndexChanged.connect(self.on_aspect_mode_changed)
        aspect_box.addWidget(self.crop_aspect_combo)
        io_layout.addLayout(aspect_box)

        self.custom_dim_widget = QWidget()
        custom_layout = QHBoxLayout(self.custom_dim_widget)
        custom_layout.setContentsMargins(0, 0, 0, 0)
        custom_layout.addWidget(QLabel("Width:"))
        self.spin_custom_w = NoWheelSpinBox()
        self.spin_custom_w.setRange(16, 3840)
        self.spin_custom_w.setValue(640)
        self.spin_custom_w.valueChanged.connect(self.on_framing_changed)
        custom_layout.addWidget(self.spin_custom_w)
        custom_layout.addWidget(QLabel("Height:"))
        self.spin_custom_h = NoWheelSpinBox()
        self.spin_custom_h.setRange(16, 2160)
        self.spin_custom_h.setValue(480)
        self.spin_custom_h.valueChanged.connect(self.on_framing_changed)
        custom_layout.addWidget(self.spin_custom_h)
        io_layout.addWidget(self.custom_dim_widget)
        self.custom_dim_widget.hide()

        self.slider_zoom = self.create_slider("Crop Zoom", 100, 400, 100, io_layout, "%", callback=self.on_framing_changed)
        self.slider_pan_x = self.create_slider("Crop Pan X", 0, 100, 50, io_layout, "%", callback=self.on_framing_changed)
        self.slider_pan_y = self.create_slider("Crop Pan Y", 0, 100, 50, io_layout, "%", callback=self.on_framing_changed)

        btn_rst_framing = QPushButton("↺ Reset Crop & Framing")
        btn_rst_framing.clicked.connect(self.reset_framing)
        io_layout.addWidget(btn_rst_framing)
        layout.addWidget(io_group)

        # 2. Pre-Adjustments (Sharpness + Photoshop/Affinity HSL Color Wheel)
        pre_group = QGroupBox("2. Pre-Adjustments (Image Source)")
        pre_layout = QVBoxLayout(pre_group)

        self.slider_sharp = self.create_slider("Sharpness", -100, 100, 0, pre_layout, callback=self.on_preprocessing_changed)

        lbl_wheel_title = QLabel("HSL Spectrum & Range:")
        lbl_wheel_title.setStyleSheet("color: #a0b0d0; font-weight: bold; margin-top: 4px;")
        pre_layout.addWidget(lbl_wheel_title)

        wheel_container = QHBoxLayout()
        self.hsl_wheel = HSLColorWheel()
        self.hsl_wheel.range_changed.connect(self.on_wheel_range_changed)
        self.hsl_wheel.range_editing_finished.connect(self.commit_state)
        wheel_container.addStretch()
        wheel_container.addWidget(self.hsl_wheel)
        wheel_container.addStretch()
        pre_layout.addLayout(wheel_container)

        swatches_row = QHBoxLayout()
        swatches_row.setSpacing(6)
        swatches_row.addStretch()
        for key, color_hex, is_master in self.SWATCH_DEFS:
            btn = ColorOptionButton(key, color_hex, is_master=is_master)
            btn.clicked.connect(lambda checked, k=key: self.select_color_swatch(k))
            self.swatch_buttons[key] = btn
            swatches_row.addWidget(btn)
        swatches_row.addStretch()
        pre_layout.addLayout(swatches_row)

        self.lbl_active_target = QLabel("Overall Shifts:")
        self.lbl_active_target.setStyleSheet("color: #a0b0d0; font-weight: bold; margin-top: 4px;")
        pre_layout.addWidget(self.lbl_active_target)

        self.slider_hue_shift = self.create_slider("Hue Shift", -180, 180, 0, pre_layout, "°", callback=self.on_active_hsl_slider_changed)
        self.slider_sat_shift = self.create_slider("Saturation Shift", -100, 100, 0, pre_layout, "%", callback=self.on_active_hsl_slider_changed)
        self.slider_light_shift = self.create_slider("Lightness Shift", -100, 100, 0, pre_layout, "%", callback=self.on_active_hsl_slider_changed)

        # Hook Hue Shift reset to restore 0 AND restore original range parameters on the wheel
        btn_rst_hue = self.slider_hue_shift.property("reset_button")
        if btn_rst_hue:
            try:
                btn_rst_hue.clicked.disconnect()
            except Exception:
                pass
            btn_rst_hue.clicked.connect(self.reset_hue_shift)
            btn_rst_hue.setToolTip("Reset Hue Shift to 0° and restore original range parameters")

        self.slider_hue_shift.reset_requested.connect(self.reset_hue_shift)

        btn_row_pre = QHBoxLayout()
        btn_rst_target = QPushButton("↺ Reset Selected Color")
        btn_rst_target.setToolTip("Resets Hue/Sat/Light and range limits for the currently selected color")
        btn_rst_target.clicked.connect(self.reset_current_color_hsl)
        btn_row_pre.addWidget(btn_rst_target)

        btn_rst_pre = QPushButton("↺ Reset All Pre-Adjustments")
        btn_rst_pre.clicked.connect(self.reset_image_adjustments)
        btn_row_pre.addWidget(btn_rst_pre)
        pre_layout.addLayout(btn_row_pre)

        layout.addWidget(pre_group)

        # 3. Post-Color Editing
        post_group = QGroupBox("3. Post-Color Editing (Current Palette)")
        post_layout = QVBoxLayout(post_group)
        post_desc = QLabel("Biases colors brighter & more saturated using the current palette:")
        post_desc.setStyleSheet("color: #8899aa; font-size: 11px;")
        post_layout.addWidget(post_desc)

        self.slider_post_bright = self.create_slider("Post Brightness", -100, 100, 0, post_layout, callback=self.process_render)
        self.slider_post_sat = self.create_slider("Post Saturation", -100, 100, 0, post_layout, callback=self.process_render)

        btn_rst_post = QPushButton("↺ Reset Post-Color Editing")
        btn_rst_post.clicked.connect(self.reset_post_color_editing)
        post_layout.addWidget(btn_rst_post)
        layout.addWidget(post_group)

        # 4. Shading & Dithering
        dither_group = QGroupBox("4. Shading & Dithering")
        dither_layout = QVBoxLayout(dither_group)
        algo_box = QHBoxLayout()
        algo_box.addWidget(QLabel("Algorithm:"))
        self.algo_combo = NoWheelComboBox()
        self.algo_combo.addItems([
            "Bayer 4x4 (Classic PC-98 Crosshatch)",
            "Bayer 2x2 (Coarse)",
            "Bayer 8x8 (Fine)",
            "Floyd-Steinberg (Error Diffusion)",
            "None (Posterized)"
        ])
        self.algo_combo.currentIndexChanged.connect(self.process_render)
        algo_box.addWidget(self.algo_combo)
        dither_layout.addLayout(algo_box)

        self.slider_dither = self.create_slider("Dither Strength", 0, 100, 50, dither_layout, "%", callback=self.process_render)
        self.check_perceptual = QCheckBox("Perceptually Weighted Color Distance")
        self.check_perceptual.setChecked(True)
        self.check_perceptual.stateChanged.connect(self.process_render)
        dither_layout.addWidget(self.check_perceptual)
        layout.addWidget(dither_group)

        # 5. Palette Studio
        pal_group = QGroupBox("5. Palette Studio")
        pal_layout = QVBoxLayout(pal_group)

        self.palette_combo = NoWheelComboBox()
        self.palette_combo.setIconSize(QSize(180, 16))
        self.palette_combo.currentIndexChanged.connect(self.on_preset_changed)
        pal_layout.addWidget(self.palette_combo)

        pal_opts_layout = QHBoxLayout()
        self.snap_toggle = QCheckBox("Snap 12-Bit (RGB444)")
        self.snap_toggle.setChecked(True)
        self.snap_toggle.stateChanged.connect(self.on_snap_toggled)
        pal_opts_layout.addWidget(self.snap_toggle)

        self.eight_color_toggle = QCheckBox("8 Colors (PC-88 Mode)")
        self.eight_color_toggle.setChecked(False)
        self.eight_color_toggle.stateChanged.connect(self.on_eight_color_toggled)
        pal_opts_layout.addWidget(self.eight_color_toggle)

        self.skin_focus_toggle = QCheckBox("Skin Tone Focus")
        self.skin_focus_toggle.setChecked(False)
        self.skin_focus_toggle.setToolTip("Dedicates half of the palette to full-spectrum skin tones from red-contour to yellow-highlight")
        self.skin_focus_toggle.stateChanged.connect(self.on_skin_focus_toggled)
        pal_opts_layout.addWidget(self.skin_focus_toggle)
        pal_layout.addLayout(pal_opts_layout)

        lock_btn_layout = QHBoxLayout()
        btn_lock_all = QPushButton("🔒 Lock All")
        btn_lock_all.clicked.connect(self.lock_all_colors)
        btn_unlock_all = QPushButton("🔓 Unlock All")
        btn_unlock_all.clicked.connect(self.unlock_all_colors)
        lock_btn_layout.addWidget(btn_lock_all)
        lock_btn_layout.addWidget(btn_unlock_all)
        pal_layout.addLayout(lock_btn_layout)

        grid_container = QWidget()
        grid = QVBoxLayout(grid_container)
        grid.setContentsMargins(0, 4, 0, 4)

        self.color_buttons = []
        self.lock_boxes = []
        for row in range(4):
            r_box = QHBoxLayout()
            for col in range(4):
                idx = row * 4 + col
                btn = QPushButton()
                btn.setFixedSize(48, 28)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.clicked.connect(lambda checked, i=idx: self.select_and_edit_color(i))
                self.color_buttons.append(btn)

                chk = QCheckBox()
                chk.setToolTip(f"Lock Color #{idx + 1}")
                chk.stateChanged.connect(lambda state, i=idx: self.toggle_lock(i, state))
                self.lock_boxes.append(chk)

                c_box = QVBoxLayout()
                c_box.setSpacing(2)
                c_box.addWidget(btn)
                c_box.addWidget(chk, alignment=Qt.AlignmentFlag.AlignCenter)
                r_box.addLayout(c_box)
            grid.addLayout(r_box)
        pal_layout.addWidget(grid_container)

        tools_layout = QHBoxLayout()
        btn_rst_pal = QPushButton("↺ Reset Palette to Default")
        btn_rst_pal.clicked.connect(self.reset_palette_settings)
        tools_layout.addWidget(btn_rst_pal)
        pal_layout.addLayout(tools_layout)

        io_pal_box = QHBoxLayout()
        btn_import = QPushButton("Import Palette")
        btn_import.clicked.connect(self.import_palette)
        btn_export_pal = QPushButton("Export Palette")
        btn_export_pal.clicked.connect(self.export_palette)
        io_pal_box.addWidget(btn_import)
        io_pal_box.addWidget(btn_export_pal)
        pal_layout.addLayout(io_pal_box)
        layout.addWidget(pal_group)

        # 6. Export Pipeline
        export_group = QGroupBox("6. Export Pipeline")
        exp_layout = QVBoxLayout(export_group)

        exp_scale_box = QHBoxLayout()
        exp_scale_box.addWidget(QLabel("Export Upscale:"))
        self.export_upscale_combo = NoWheelComboBox()
        self.export_upscale_combo.addItems([
            "1x (Native Resolution)",
            "2x (Crisp Integer - Default)",
            "4x (Crisp Integer)",
            "8x (Crisp Integer)"
        ])
        self.export_upscale_combo.setCurrentIndex(1)
        exp_scale_box.addWidget(self.export_upscale_combo)
        exp_layout.addLayout(exp_scale_box)

        btn_save = QPushButton("Save Image (Indexed PNG / BMP)")
        btn_save.setStyleSheet("background-color: #2e5c8a; font-weight: bold; padding: 10px;")
        btn_save.clicked.connect(self.save_image)
        exp_layout.addWidget(btn_save)
        layout.addWidget(export_group)

        scroll.setWidget(controls_widget)
        main_splitter.addWidget(scroll)
        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 0)

        self.select_color_swatch('master')
        self.update_swatch_icons()

    def create_slider(self, label: str, min_val: int, max_val: int, default: int,
                      parent_layout: QVBoxLayout, suffix="", callback=None):
        box = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setFixedWidth(130)

        slider = ResetableSlider(Qt.Orientation.Horizontal, default_val=default)
        slider.setRange(min_val, max_val)
        slider.setValue(default)
        slider.setToolTip("Tip: Double-click slider to reset")

        spin = ValueSpinBox(min_val, max_val, default, suffix)

        btn_rst = QPushButton("↺")
        btn_rst.setFixedSize(26, 24)
        btn_rst.setStyleSheet("""
            QPushButton {
                padding: 0px;
                margin: 0px;
                font-family: 'Segoe UI', Arial;
                font-size: 14px;
                font-weight: bold;
                background-color: #2a2a34;
                border: 1px solid #444455;
                border-radius: 4px;
                color: #dcdce0;
            }
            QPushButton:hover {
                background-color: #383848;
                border-color: #667799;
            }
        """)
        btn_rst.setToolTip(f"Reset {label} to {default}{suffix}")
        btn_rst.clicked.connect(lambda: slider.setValue(default))

        # Bidirectional synchronization between Slider and ValueSpinBox
        slider.valueChanged.connect(spin.setValue)
        spin.valueChanged.connect(slider.setValue)
        spin.editingFinished.connect(self.commit_state)

        if callback:
            slider.valueChanged.connect(callback)

        slider.sliderPressed.connect(self.on_slider_pressed)
        slider.sliderReleased.connect(self.on_slider_released)

        box.addWidget(lbl)
        box.addWidget(slider)
        box.addWidget(spin)
        box.addWidget(btn_rst)
        parent_layout.addLayout(box)

        slider.setProperty("default_value", default)
        slider.setProperty("spin_box", spin)
        slider.setProperty("suffix", suffix)
        slider.setProperty("reset_button", btn_rst)
        self.all_sliders.append(slider)
        return slider

    def on_slider_pressed(self):
        self.is_slider_down = True

    def on_slider_released(self):
        self.is_slider_down = False
        self.commit_state()

    def update_swatch_icons(self):
        """Updates the swatch buttons to represent the target color range defined on the wheel."""
        for key, data in self.color_hsl.items():
            if key in self.swatch_buttons:
                p0, p1, p2, p3 = data['range']
                d_hard = (p2 - p1) % 360.0
                center_h = (p1 + d_hard * 0.5) % 360.0
                self.swatch_buttons[key].set_color_from_hue(center_h)

    def select_color_swatch(self, key: str):
        self.current_color_key = key
        for k, btn in self.swatch_buttons.items():
            btn.setSelected(k == key)

        if key == 'master':
            self.lbl_active_target.setText("Overall Shifts:")
            self.hsl_wheel.set_color_data('master', [0, 0, 0, 0])
            h, s, l = self.master_hsl
        else:
            name_cap = key.capitalize()
            self.lbl_active_target.setText(f"{name_cap} Shifts:")
            c_data = self.color_hsl[key]
            self.hsl_wheel.set_color_data(key, c_data['range'])
            h, s, l = c_data['shifts']

        self.slider_hue_shift.blockSignals(True)
        self.slider_sat_shift.blockSignals(True)
        self.slider_light_shift.blockSignals(True)

        self.slider_hue_shift.setValue(h)
        self.slider_sat_shift.setValue(s)
        self.slider_light_shift.setValue(l)

        for s_widget, val in [
            (self.slider_hue_shift, h),
            (self.slider_sat_shift, s),
            (self.slider_light_shift, l)
        ]:
            spin = s_widget.property("spin_box")
            if spin:
                spin.blockSignals(True)
                spin.setValue(val)
                spin.blockSignals(False)

        self.slider_hue_shift.blockSignals(False)
        self.slider_sat_shift.blockSignals(False)
        self.slider_light_shift.blockSignals(False)

    def on_active_hsl_slider_changed(self):
        if self.is_updating:
            return
        h = self.slider_hue_shift.value()
        s = self.slider_sat_shift.value()
        l = self.slider_light_shift.value()

        if self.current_color_key == 'master':
            self.master_hsl = [h, s, l]
        else:
            self.color_hsl[self.current_color_key]['shifts'] = [h, s, l]

        self.on_preprocessing_changed()

    def on_wheel_range_changed(self, new_range: list):
        if self.current_color_key != 'master':
            self.color_hsl[self.current_color_key]['range'] = list(new_range)
            self.update_swatch_icons()
            self.on_preprocessing_changed()

    def reset_hue_shift(self):
        """Resets the active Hue shift to 0 and restores the original range parameters on the wheel."""
        self.slider_hue_shift.setValue(0)
        if self.current_color_key == 'master':
            self.master_hsl[0] = 0
        else:
            def_range = self.DEFAULT_COLOR_HSL[self.current_color_key]['range']
            self.color_hsl[self.current_color_key]['shifts'][0] = 0
            self.color_hsl[self.current_color_key]['range'] = list(def_range)
            self.hsl_wheel.set_color_data(self.current_color_key, def_range)
        self.update_swatch_icons()
        self.on_preprocessing_changed()
        self.commit_state()

    def reset_current_color_hsl(self):
        """Resets all shifts (Hue, Sat, Light) and range parameters of the selected color."""
        if self.current_color_key == 'master':
            self.master_hsl = [0, 0, 0]
        else:
            def_range = self.DEFAULT_COLOR_HSL[self.current_color_key]['range']
            self.color_hsl[self.current_color_key] = {
                'shifts': [0, 0, 0],
                'range': list(def_range)
            }
            self.hsl_wheel.set_color_data(self.current_color_key, def_range)

        self.select_color_swatch(self.current_color_key)
        self.update_swatch_icons()
        self.on_preprocessing_changed()
        self.commit_state()

    def serialize_state(self):
        return {
            "sharp": self.slider_sharp.value(),
            "master_hsl": list(self.master_hsl),
            "color_hsl": {
                k: {'shifts': list(v['shifts']), 'range': list(v['range'])}
                for k, v in self.color_hsl.items()
            },
            "active_color_key": self.current_color_key,
            "post_bright": self.slider_post_bright.value(),
            "post_sat": self.slider_post_sat.value(),
            "algo_idx": self.algo_combo.currentIndex(),
            "dither": self.slider_dither.value(),
            "perceptual": self.check_perceptual.isChecked(),
            "palette_idx": self.palette_combo.currentIndex(),
            "snap": self.snap_toggle.isChecked(),
            "eight_color": self.eight_color_toggle.isChecked(),
            "skin_focus": self.skin_focus_toggle.isChecked(),
            "active_palette": self.active_palette.copy(),
            "locked_colors": list(self.locked_colors),
            "res_idx": self.res_combo.currentIndex(),
            "aspect_idx": self.crop_aspect_combo.currentIndex(),
            "custom_w": self.spin_custom_w.value(),
            "custom_h": self.spin_custom_h.value(),
            "crop_zoom": self.slider_zoom.value(),
            "crop_pan_x": self.slider_pan_x.value(),
            "crop_pan_y": self.slider_pan_y.value(),
            "aspect_toggle": self.aspect_toggle.isChecked(),
            "compare_toggle": self.compare_toggle.isChecked(),
            "compare_idx": self.compare_combo.currentIndex(),
            "split_val": self.slider_split.value(),
        }

    def state_equals(self, s1, s2):
        if s1 is None or s2 is None:
            return s1 == s2
        for k in s1:
            v1, v2 = s1[k], s2[k]
            if isinstance(v1, np.ndarray):
                if not np.array_equal(v1, v2):
                    return False
            elif isinstance(v1, dict):
                if v1 != v2:
                    return False
            elif v1 != v2:
                return False
        return True

    def commit_state(self):
        if self.is_updating or self.is_undoing or self.is_slider_down:
            return
        current = self.serialize_state()
        if self.committed_state is None:
            self.committed_state = current
            return
        if not self.state_equals(current, self.committed_state):
            self.undo_stack.append(self.committed_state)
            if len(self.undo_stack) > 50:
                self.undo_stack.pop(0)
            self.committed_state = current

    def undo(self):
        if not self.undo_stack:
            self.status_label.setText("Nothing to undo")
            return
        prev = self.undo_stack.pop()
        self.apply_state(prev)

    def apply_state(self, state):
        if state is None:
            return
        self.is_undoing = True
        self.is_updating = True
        self.cached_framed_image = None

        self.slider_sharp.setValue(state["sharp"])
        self.master_hsl = list(state["master_hsl"])
        self.color_hsl = {
            k: {'shifts': list(v['shifts']), 'range': list(v['range'])}
            for k, v in state["color_hsl"].items()
        }
        self.select_color_swatch(state["active_color_key"])

        self.slider_post_bright.setValue(state["post_bright"])
        self.slider_post_sat.setValue(state["post_sat"])
        self.algo_combo.setCurrentIndex(state["algo_idx"])
        self.slider_dither.setValue(state["dither"])
        self.check_perceptual.setChecked(state["perceptual"])

        self.eight_color_toggle.setChecked(state["eight_color"])
        self.skin_focus_toggle.setChecked(state["skin_focus"])
        self.snap_toggle.setChecked(state["snap"])
        self.aspect_toggle.setChecked(state["aspect_toggle"])
        self.compare_toggle.setChecked(state["compare_toggle"])
        self.compare_combo.setCurrentIndex(state["compare_idx"])
        self.slider_split.setValue(state["split_val"])

        self.res_combo.setCurrentIndex(state["res_idx"])
        self.crop_aspect_combo.setCurrentIndex(state["aspect_idx"])
        self.spin_custom_w.setValue(state["custom_w"])
        self.spin_custom_h.setValue(state["custom_h"])
        self.slider_zoom.setValue(state["crop_zoom"])
        self.slider_pan_x.setValue(state["crop_pan_x"])
        self.slider_pan_y.setValue(state["crop_pan_y"])

        self.locked_colors = list(state["locked_colors"])
        for i, chk in enumerate(self.lock_boxes):
            chk.blockSignals(True)
            chk.setChecked(self.locked_colors[i])
            chk.blockSignals(False)

        self.active_palette = state["active_palette"].copy()

        if self.source_image is not None:
            small_src = self.source_image.resize((320, 200), Image.Resampling.BILINEAR)
            pre_adjusted_small = Image.fromarray(self.apply_preprocessing(small_src).astype(np.uint8))
            self.original_image_palette = self.extract_base_palette(pre_adjusted_small)

        self.populate_palette_dropdown()
        self.palette_combo.blockSignals(True)
        self.palette_combo.setCurrentIndex(state["palette_idx"])
        self.palette_combo.blockSignals(False)

        self.update_palette_swatches()
        self.update_swatch_icons()
        self.is_updating = False
        self.process_render()
        self.update_compare_layout()
        self.is_undoing = False
        self.committed_state = self.serialize_state()
        self.status_label.setText("Undo successful")

    def apply_dark_theme(self):
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1a1a1e;
            }
            QWidget {
                color: #dcdce0;
                font-family: 'Segoe UI', Arial;
                font-size: 12px;
            }
            QScrollArea, QScrollArea > QWidget > QWidget {
                background-color: #1a1a1e;
                border: none;
            }
            QGroupBox {
                background-color: #1a1a1e;
                border: 1px solid #33333d;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 10px;
                font-weight: bold;
                color: #a0b0d0;
            }
            QPushButton {
                background-color: #2a2a34;
                border: 1px solid #444455;
                border-radius: 4px;
                padding: 5px 10px;
                color: #dcdce0;
            }
            QPushButton:hover {
                background-color: #383848;
                border-color: #667799;
                color: #ffffff;
            }
            QPushButton:pressed {
                background-color: #1f1f27;
            }
            QComboBox, QSpinBox {
                background-color: #24242e;
                border: 1px solid #444455;
                border-radius: 4px;
                padding: 4px;
                color: #ffffff;
            }
            QComboBox QAbstractItemView {
                background-color: #24242e;
                color: #ffffff;
                selection-background-color: #383848;
                border: 1px solid #444455;
            }
            QSlider::groove:horizontal {
                height: 4px;
                background: #333340;
                border-radius: 2px;
            }
            QSlider::sub-page:horizontal {
                background: #4a77a8;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #d0d0e0;
                width: 16px;
                margin-top: -6px;
                margin-bottom: -6px;
                border-radius: 8px;
            }
            QSlider::handle:horizontal:hover {
                background: #ffffff;
            }
            QSplitter::handle {
                background-color: #2f2f3d;
                border: 1px solid #444455;
                border-radius: 4px;
            }
            QSplitter::handle:hover {
                background-color: #4a77a8;
            }
        """)

    def update_compare_layout(self):
        is_compare = self.compare_toggle.isChecked()
        self.compare_combo.setEnabled(is_compare)
        self.slider_split.setEnabled(is_compare)
        self.spin_split.setEnabled(is_compare)

        if not is_compare:
            self.canvas_orig.hide()
            self.canvas_edited.show()
        else:
            self.canvas_orig.show()
            self.canvas_edited.show()
            mode = self.compare_combo.currentIndex()
            if mode == 0:
                self.preview_splitter.setOrientation(Qt.Orientation.Vertical)
            else:
                self.preview_splitter.setOrientation(Qt.Orientation.Horizontal)
            self.on_split_slider_moved(self.slider_split.value())

        self.update_preview_display()
        self.commit_state()

    def on_split_slider_moved(self, val: int):
        total = sum(self.preview_splitter.sizes())
        if total > 0:
            s1 = int(total * (val / 100.0))
            s2 = total - s1
            self.preview_splitter.setSizes([s1, s2])

    def on_sync_zoom(self, z: float):
        val_int = int(z * 100)
        self.slider_view_zoom.blockSignals(True)
        self.slider_view_zoom.setValue(val_int)
        self.slider_view_zoom.blockSignals(False)

        self.spin_view_zoom.blockSignals(True)
        self.spin_view_zoom.setValue(val_int)
        self.spin_view_zoom.blockSignals(False)

        self.canvas_orig.zoom_factor = z
        self.canvas_edited.zoom_factor = z
        self.canvas_orig.update()
        self.canvas_edited.update()

    def on_sync_pan(self, px: float, py: float):
        self.canvas_orig.pan_x = px
        self.canvas_orig.pan_y = py
        self.canvas_edited.pan_x = px
        self.canvas_edited.pan_y = py
        self.canvas_orig.update()
        self.canvas_edited.update()

    def set_viewport_zoom(self, zoom: float, reset_pan: bool = False):
        if reset_pan:
            self.canvas_orig.pan_x = 0.0
            self.canvas_orig.pan_y = 0.0
            self.canvas_edited.pan_x = 0.0
            self.canvas_edited.pan_y = 0.0

        self.canvas_orig.zoom_factor = zoom
        self.canvas_edited.zoom_factor = zoom
        val_int = int(zoom * 100)

        self.slider_view_zoom.blockSignals(True)
        self.slider_view_zoom.setValue(val_int)
        self.slider_view_zoom.blockSignals(False)

        self.spin_view_zoom.blockSignals(True)
        self.spin_view_zoom.setValue(val_int)
        self.spin_view_zoom.blockSignals(False)

        self.canvas_orig.update()
        self.canvas_edited.update()

    def on_aspect_mode_changed(self):
        is_custom = (self.crop_aspect_combo.currentIndex() == 2)
        self.custom_dim_widget.setVisible(is_custom)
        self.on_framing_changed()

    # --- Section Resets ---
    def reset_framing(self):
        self.is_updating = True
        self.cached_framed_image = None
        self.slider_zoom.setValue(100)
        self.slider_pan_x.setValue(50)
        self.slider_pan_y.setValue(50)
        self.res_combo.setCurrentIndex(0)
        self.crop_aspect_combo.setCurrentIndex(0)
        self.is_updating = False
        self.on_framing_changed()
        self.commit_state()

    def reset_image_adjustments(self):
        self.is_updating = True
        self.slider_sharp.setValue(0)
        self.master_hsl = [0, 0, 0]
        self.color_hsl = {
            k: {'shifts': [0, 0, 0], 'range': list(v['range'])}
            for k, v in self.DEFAULT_COLOR_HSL.items()
        }
        self.select_color_swatch(self.current_color_key)
        self.is_updating = False
        self.on_preprocessing_changed()
        self.commit_state()

    def reset_post_color_editing(self):
        self.is_updating = True
        self.slider_post_bright.setValue(0)
        self.slider_post_sat.setValue(0)
        self.is_updating = False
        self.process_render()
        self.commit_state()

    def reset_palette_settings(self):
        self.is_updating = True
        self.eight_color_toggle.setChecked(False)
        self.skin_focus_toggle.setChecked(False)
        self.snap_toggle.setChecked(True)
        self.unlock_all_colors()
        self.is_updating = False

        if self.source_image is not None:
            small_src = self.source_image.resize((320, 200), Image.Resampling.BILINEAR)
            pre_adjusted_small = Image.fromarray(self.apply_preprocessing(small_src).astype(np.uint8))
            self.original_image_palette = self.extract_base_palette(pre_adjusted_small)
            self.populate_palette_dropdown()
            self.palette_combo.setCurrentIndex(0)
            self.on_preset_changed(0)
        else:
            self.populate_palette_dropdown()
        self.commit_state()

    # --- Core Pipeline Operations ---
    def open_image(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open Image", "", "Images (*.png *.jpg *.jpeg *.bmp *.webp)"
        )
        if not file_path:
            return
        self.source_image = Image.open(file_path).convert("RGB")
        self.cached_framed_image = None
        small_src = self.source_image.resize((320, 200), Image.Resampling.BILINEAR)
        pre_adjusted_small = Image.fromarray(self.apply_preprocessing(small_src).astype(np.uint8))
        self.original_image_palette = self.extract_base_palette(pre_adjusted_small)
        self.reset_framing()
        self.reset_image_adjustments()
        self.reset_post_color_editing()
        self.reset_palette_settings()
        self.undo_stack.clear()
        self.committed_state = self.serialize_state()

    def get_target_dimensions(self):
        if self.source_image is None:
            return 640, 400

        idx = self.res_combo.currentIndex()
        mult = 1.0 if idx == 0 else 0.5 if idx == 1 else 2.0 if idx == 2 else 4.0
        aspect_mode = self.crop_aspect_combo.currentIndex()
        sw, sh = self.source_image.width, self.source_image.height

        if aspect_mode == 0:
            tw = int(round(640 * mult))
            th = int(round(400 * mult))
        elif aspect_mode == 1:
            tw = int(round(640 * mult))
            th = int(round(tw * (sh / sw)))
            if tw % 2 != 0: tw += 1
            if th % 2 != 0: th += 1
        else:
            cw = self.spin_custom_w.value()
            ch = self.spin_custom_h.value()
            tw = int(round(cw * mult))
            th = int(round(ch * mult))
            if tw % 2 != 0: tw += 1
            if th % 2 != 0: th += 1

        return max(16, tw), max(16, th)

    def get_framed_image(self) -> Image.Image:
        if self.source_image is None:
            return None

        if self.cached_framed_image is not None:
            return self.cached_framed_image

        tw, th = self.get_target_dimensions()
        sw, sh = self.source_image.width, self.source_image.height
        zoom = max(1.0, self.slider_zoom.value() / 100.0)
        pan_x = self.slider_pan_x.value() / 100.0
        pan_y = self.slider_pan_y.value() / 100.0

        tgt_ratio = tw / th
        src_ratio = sw / sh

        if src_ratio >= tgt_ratio:
            base_h = sh
            base_w = min(sw, int(round(sh * tgt_ratio)))
        else:
            base_w = sw
            base_h = min(sh, int(round(sw / tgt_ratio)))

        crop_w = max(16, min(sw, int(round(base_w / zoom))))
        crop_h = max(16, min(sh, int(round(base_h / zoom))))
        left = int(round(max(0, sw - crop_w) * pan_x))
        top = int(round(max(0, sh - crop_h) * pan_y))

        cropped = self.source_image.crop((left, top, left + crop_w, top + crop_h))
        self.cached_framed_image = cropped.resize((tw, th), Image.Resampling.LANCZOS)
        return self.cached_framed_image

    def apply_preprocessing(self, img: Image.Image) -> np.ndarray:
        sh_val = self.slider_sharp.value()
        if sh_val > 0:
            factor = 1.0 + (sh_val / 50.0)
            img = ImageEnhance.Sharpness(img).enhance(factor)
        elif sh_val < 0:
            blur_radius = (-sh_val / 100.0) * 3.0
            img = img.filter(ImageFilter.GaussianBlur(radius=blur_radius))

        arr = np.array(img, dtype=np.float32)
        arr = apply_hsl_transform(arr, self.master_hsl, self.color_hsl)
        return arr

    def apply_post_color_editing(self, arr: np.ndarray) -> np.ndarray:
        post_b = self.slider_post_bright.value()
        post_s = self.slider_post_sat.value()

        if post_b == 0 and post_s == 0:
            return arr

        res = arr.copy()
        if post_b != 0:
            res += (post_b * 1.25)

        if post_s != 0:
            lum = 0.299 * res[:, :, 0] + 0.587 * res[:, :, 1] + 0.114 * res[:, :, 2]
            sat_mult = max(0.0, 1.0 + (post_s / 100.0))
            res = lum[:, :, None] + (res - lum[:, :, None]) * sat_mult

        return np.clip(res, 0, 255)

    def generate_palette_icon(self, palette_array: np.ndarray) -> QIcon:
        num = 8 if self.eight_color_toggle.isChecked() else 16
        img = QImage(160, 16, QImage.Format.Format_RGB888)
        painter = QPainter(img)
        w_step = 160.0 / num
        for i in range(num):
            c = palette_array[i]
            painter.fillRect(int(i * w_step), 0, int(w_step + 1), 16, QColor(int(c[0]), int(c[1]), int(c[2])))
        painter.end()
        return QIcon(QPixmap.fromImage(img))

    def extract_base_palette(self, pil_img: Image.Image) -> np.ndarray:
        num_colors = 8 if self.eight_color_toggle.isChecked() else 16
        pal = extract_balanced_palette(pil_img, k=num_colors)
        res = np.zeros((16, 3), dtype=np.uint8)
        res[:num_colors] = pal
        return snap_to_rgb444(res) if self.snap_toggle.isChecked() else res

    def populate_palette_dropdown(self):
        self.is_updating = True
        current_idx = self.palette_combo.currentIndex()
        self.palette_combo.clear()

        base_pal = self.original_image_palette.copy()
        if self.snap_toggle.isChecked():
            base_pal = snap_to_rgb444(base_pal)

        num_c = 8 if self.eight_color_toggle.isChecked() else 16
        skin_focus = self.skin_focus_toggle.isChecked()

        vibrant_pal = adjust_palette_accents(base_pal, "vibrant")
        warm_pal = adjust_palette_accents(base_pal, "warm")
        cool_pal = adjust_palette_accents(base_pal, "cool")

        if skin_focus:
            base_pal = apply_skin_focus_to_palette(base_pal, self.original_image_palette, num_c)
            vibrant_pal = apply_skin_focus_to_palette(vibrant_pal, self.original_image_palette, num_c)
            warm_pal = apply_skin_focus_to_palette(warm_pal, self.original_image_palette, num_c)
            cool_pal = apply_skin_focus_to_palette(cool_pal, self.original_image_palette, num_c)

        purple_pal = build_skin_accent_palette(self.original_image_palette, "purple", num_c, skin_focus)
        green_pal = build_skin_accent_palette(self.original_image_palette, "green", num_c, skin_focus)
        red_pal = build_skin_accent_palette(self.original_image_palette, "red", num_c, skin_focus)
        blue_pal = build_skin_accent_palette(self.original_image_palette, "blue", num_c, skin_focus)

        if self.snap_toggle.isChecked():
            vibrant_pal = snap_to_rgb444(vibrant_pal)
            warm_pal = snap_to_rgb444(warm_pal)
            cool_pal = snap_to_rgb444(cool_pal)

        self.generated_palettes = [
            base_pal,
            vibrant_pal,
            warm_pal,
            cool_pal,
            purple_pal,
            green_pal,
            red_pal,
            blue_pal,
            YUNO_PALETTE.copy(),
            POSSESSIONER_PALETTE.copy()
        ]

        items = [
            ("Default (Original Palette)", base_pal),
            ("Vibrant", vibrant_pal),
            ("Warm", warm_pal),
            ("Cool", cool_pal),
            ("Purple Accent", purple_pal),
            ("Green Accent", green_pal),
            ("Red Accent", red_pal),
            ("Blue Accent", blue_pal),
            ("YU-NO", YUNO_PALETTE),
            ("Possessioner", POSSESSIONER_PALETTE)
        ]

        for name, pal_array in items:
            self.palette_combo.addItem(self.generate_palette_icon(pal_array), name)

        target_idx = current_idx if (0 <= current_idx < len(items)) else 0
        self.palette_combo.setCurrentIndex(target_idx)
        self.is_updating = False

    def update_palette_swatches(self):
        num_active = 8 if self.eight_color_toggle.isChecked() else 16
        for i in range(16):
            is_enabled = (i < num_active)
            self.color_buttons[i].setEnabled(is_enabled)
            self.lock_boxes[i].setEnabled(is_enabled)

            if is_enabled:
                c = self.active_palette[i]
                luminance = 0.299 * float(c[0]) + 0.587 * float(c[1]) + 0.114 * float(c[2])
                text_color = "#000000" if luminance > 130 else "#ffffff"
                hex_color = f"#{c[0]:02x}{c[1]:02x}{c[2]:02x}"
                border_color = "#ffffff" if i == self.selected_swatch_idx else "#555"
                border_width = "2px" if i == self.selected_swatch_idx else "1px"
                self.color_buttons[i].setStyleSheet(
                    f"background-color: {hex_color}; color: {text_color}; "
                    f"border: {border_width} solid {border_color}; border-radius: 3px; font-weight: bold;"
                )
                self.color_buttons[i].setText(str(i + 1))
            else:
                self.color_buttons[i].setStyleSheet(
                    "background-color: #1a1a20; color: #444; border: 1px dashed #333; border-radius: 3px;"
                )
                self.color_buttons[i].setText("—")

    def select_and_edit_color(self, index: int):
        self.selected_swatch_idx = index
        self.update_palette_swatches()

        cur = self.active_palette[index]
        init_col = QColor(int(cur[0]), int(cur[1]), int(cur[2]))
        dlg = ColorSelectionDialog(init_col, self, f"Set Color #{index + 1}")
        if dlg.exec():
            col = dlg.currentColor()
            if col.isValid():
                c = np.array([col.red(), col.green(), col.blue()], dtype=np.uint8)
                self.active_palette[index] = snap_to_rgb444(c) if self.snap_toggle.isChecked() else c
                self.update_palette_swatches()
                self.process_render()
                self.commit_state()

    def toggle_lock(self, index: int, state: int):
        self.locked_colors[index] = (state == 2 or state == Qt.CheckState.Checked)
        self.commit_state()

    def lock_all_colors(self):
        num_active = 8 if self.eight_color_toggle.isChecked() else 16
        for i in range(num_active):
            self.lock_boxes[i].setChecked(True)
        self.commit_state()

    def unlock_all_colors(self):
        for chk in self.lock_boxes:
            chk.setChecked(False)
        self.commit_state()

    def on_eight_color_toggled(self):
        if self.source_image is not None:
            small_src = self.source_image.resize((320, 200), Image.Resampling.BILINEAR)
            pre_adjusted_small = Image.fromarray(self.apply_preprocessing(small_src).astype(np.uint8))
            self.original_image_palette = self.extract_base_palette(pre_adjusted_small)
        self.populate_palette_dropdown()
        self.on_preset_changed(self.palette_combo.currentIndex())
        self.commit_state()

    def on_skin_focus_toggled(self):
        self.populate_palette_dropdown()
        self.on_preset_changed(self.palette_combo.currentIndex())
        self.commit_state()

    def on_framing_changed(self):
        if self.is_updating or self.source_image is None:
            return
        self.cached_framed_image = None
        self.process_render()
        self.commit_state()

    def on_preprocessing_changed(self):
        if self.is_updating or self.source_image is None:
            return

        small_src = self.source_image.resize((320, 200), Image.Resampling.BILINEAR)
        pre_adjusted_small = Image.fromarray(self.apply_preprocessing(small_src).astype(np.uint8))
        self.original_image_palette = self.extract_base_palette(pre_adjusted_small)
        self.populate_palette_dropdown()

        curr_idx = self.palette_combo.currentIndex()
        if curr_idx < 8:
            num_active = 8 if self.eight_color_toggle.isChecked() else 16
            target_pal = self.generated_palettes[curr_idx]
            for slot in range(num_active):
                if not self.locked_colors[slot]:
                    self.active_palette[slot] = target_pal[slot]
            self.update_palette_swatches()

        self.process_render()
        self.commit_state()

    def on_preset_changed(self, index: int):
        if self.is_updating or index < 0 or index >= len(self.generated_palettes):
            return
        num_active = 8 if self.eight_color_toggle.isChecked() else 16
        unlocked_slots = [i for i in range(num_active) if not self.locked_colors[i]]
        target_pal = self.generated_palettes[index]
        for slot in unlocked_slots:
            self.active_palette[slot] = target_pal[slot]
        self.update_palette_swatches()
        self.process_render()
        self.commit_state()

    def on_snap_toggled(self):
        self.populate_palette_dropdown()
        self.on_preset_changed(self.palette_combo.currentIndex())
        self.commit_state()

    def process_render(self):
        if self.source_image is None or self.is_updating:
            return
        framed = self.get_framed_image()
        if framed is None:
            return

        arr_pre = self.apply_preprocessing(framed)
        arr = self.apply_post_color_editing(arr_pre)

        h, w, _ = arr.shape
        num_colors = 8 if self.eight_color_toggle.isChecked() else 16
        algo = self.algo_combo.currentIndex()
        strength = self.slider_dither.value() / 100.0
        palette = self.active_palette[:num_colors].astype(np.float32)

        if self.check_perceptual.isChecked():
            weights = np.array([0.299, 0.587, 0.114], dtype=np.float32)
        else:
            weights = np.array([0.333, 0.333, 0.333], dtype=np.float32)
        sqrt_w = np.sqrt(weights)

        if algo == 3:
            pil_input = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
            pal_img = Image.new("P", (1, 1))
            pal_256 = np.zeros((256, 3), dtype=np.uint8)
            for i in range(256):
                pal_256[i] = self.active_palette[i % num_colors]
            pal_img.putpalette(pal_256.flatten().tolist())
            quant = pil_input.quantize(palette=pal_img, dither=Image.Dither.FLOYDSTEINBERG)
            self.processed_indices = (np.array(quant) % num_colors).astype(np.uint8)
        else:
            if algo == 0:
                matrix, step = BAYER_4X4, 4
            elif algo == 1:
                matrix, step = BAYER_2X2, 2
            elif algo == 2:
                matrix, step = BAYER_8X8, 8
            else:
                matrix, step = np.zeros((1, 1), dtype=np.float32), 1

            if algo != 4 and strength > 0:
                t_y = (h + step - 1) // step
                t_x = (w + step - 1) // step
                tiled = np.tile(matrix, (t_y, t_x))[:h, :w, None]
                arr_dithered = np.clip(arr + tiled * (54.0 * strength), 0, 255)
            else:
                arr_dithered = arr

            arr_scaled = (arr_dithered.reshape(-1, 3) * sqrt_w).astype(np.float32)
            pal_scaled = (palette * sqrt_w).astype(np.float32)
            pal_norm_sq = np.sum(pal_scaled ** 2, axis=1)
            logits = pal_norm_sq[None, :] - 2.0 * np.dot(arr_scaled, pal_scaled.T)
            self.processed_indices = np.argmin(logits, axis=1).reshape(h, w).astype(np.uint8)

        self.update_preview_display()
        self.commit_state()

    def update_preview_display(self, *args):
        if self.source_image is None or self.processed_indices is None:
            return

        h, w = self.processed_indices.shape
        framed_orig = self.get_framed_image()
        if framed_orig is None:
            return

        rgb_output = self.active_palette[self.processed_indices]
        qimg_edited = QImage(rgb_output.data, w, h, w * 3, QImage.Format.Format_RGB888).copy()

        stretch = 1.2 if self.aspect_toggle.isChecked() else 1.0
        self.canvas_edited.set_image(qimg_edited, stretch)

        if self.compare_toggle.isChecked():
            orig_bytes = np.array(framed_orig, dtype=np.uint8)
            qimg_orig = QImage(orig_bytes.data, w, h, w * 3, QImage.Format.Format_RGB888).copy()
            self.canvas_orig.set_image(qimg_orig, stretch)

        num_colors = 8 if self.eight_color_toggle.isChecked() else 16
        is_crt = self.aspect_toggle.isChecked()
        self.status_label.setText(
            f"Canvas: {w}x{h} | Active Colors: {num_colors} | CRT Stretch: {'ON (1:1.2)' if is_crt else 'OFF (1:1)'}"
        )

    def import_palette(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Palette", "", "Palettes (*.hex *.gpl *.txt *.png *.bmp)"
        )
        if not path:
            return
        colors = []
        try:
            if path.lower().endswith((".png", ".bmp")):
                pal_img = Image.open(path).convert("RGB")
                unique = np.unique(np.array(pal_img).reshape(-1, 3), axis=0)
                colors = [list(c) for c in unique[:16]]
            else:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("#") and len(line) == 7:
                            colors.append([int(line[1:3], 16), int(line[3:5], 16), int(line[5:7], 16)])
                        elif line and not line.startswith("GIMP") and not line.startswith(";"):
                            parts = line.split()
                            if len(parts) >= 3 and parts[0].isdigit():
                                colors.append([int(parts[0]), int(parts[1]), int(parts[2])])
            if len(colors) > 0:
                for i in range(min(16, len(colors))):
                    c = np.array(colors[i], dtype=np.uint8)
                    self.active_palette[i] = snap_to_rgb444(c) if self.snap_toggle.isChecked() else c
                self.update_palette_swatches()
                self.process_render()
                self.commit_state()
            else:
                QMessageBox.warning(self, "Import Failed", "No valid colors found in file.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to import palette: {str(e)}")

    def export_palette(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Palette", "pc98_palette.hex", "Hex Palette (*.hex);;GIMP/Aseprite (*.gpl)"
        )
        if not path:
            return
        num_colors = 8 if self.eight_color_toggle.isChecked() else 16
        try:
            with open(path, "w", encoding="utf-8") as f:
                if path.endswith(".gpl"):
                    f.write("GIMP Palette\nChannels: RGB\n#\n")
                    for i in range(num_colors):
                        c = self.active_palette[i]
                        f.write(f"{c[0]:3d} {c[1]:3d} {c[2]:3d} Untitled\n")
                else:
                    for i in range(num_colors):
                        c = self.active_palette[i]
                        f.write(f"#{c[0]:02X}{c[1]:02X}{c[2]:02X}\n")
            self.status_label.setText(f"Exported palette: {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to export palette: {str(e)}")

    def save_image(self):
        if self.processed_indices is None:
            QMessageBox.warning(self, "Warning", "No processed image to export.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Image", "pc98_output.png", "Indexed PNG (*.png);;Windows BMP (*.bmp)"
        )
        if not path:
            return
        h, w = self.processed_indices.shape
        num_colors = 8 if self.eight_color_toggle.isChecked() else 16
        indexed_img = Image.fromarray(self.processed_indices, mode="P")
        full_pal = np.zeros((256, 3), dtype=np.uint8)
        full_pal[:num_colors] = self.active_palette[:num_colors]
        indexed_img.putpalette(full_pal.flatten().tolist())

        upscale_idx = self.export_upscale_combo.currentIndex()
        scale = 1 if upscale_idx == 0 else 2 if upscale_idx == 1 else 4 if upscale_idx == 2 else 8
        apply_crt = self.aspect_toggle.isChecked()

        target_w = w * scale
        target_h = int(round(h * (1.2 if apply_crt else 1.0))) * scale

        if (target_w != w) or (target_h != h):
            indexed_img = indexed_img.resize((target_w, target_h), Image.Resampling.NEAREST)

        try:
            if path.lower().endswith(".png"):
                indexed_img.save(path, format="PNG", bits=4, optimize=True)
            else:
                indexed_img.save(path, format="BMP")
            stretch_note = " [CRT 1.2x Stretched]" if apply_crt else ""
            self.status_label.setText(f"Exported: {os.path.basename(path)} ({target_w}x{target_h}){stretch_note}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save image: {str(e)}")


if __name__ == "__main__":
    try:
        print("[PC-98 STUDIO] [4/4] Creating application window...")
        app = QApplication(sys.argv)
        app.setStyle("Fusion")

        icon_path = resource_path("app_icon.ico")
        if os.path.exists(icon_path):
            app.setWindowIcon(QIcon(icon_path))

        window = PC98Studio()
        window.show()
        window.raise_()
        window.activateWindow()
        print("[PC-98 STUDIO] Application running successfully!")
        print("=" * 55)
        sys.exit(app.exec())
    except Exception as e:
        import traceback
        print("\n" + "!" * 55)
        print("[FATAL ERROR DETECTED ON STARTUP]")
        traceback.print_exc()
        print("!" * 55)
        input("\nPress Enter to close this window...")