from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Protocol

from .capture import encode_rgba_png
from .models import Observation, RegionSpec


BUILD_UI_ROLES = (
    "BUILD_MENU_TOGGLE",
    "BUILD_MENU_OPEN",
    "BUILD_MENU_CLOSE",
    "BUILD_CATEGORY_TAB",
    "BUILD_OPTION",
    "BUILD_DISABLED_OPTION",
    "BUILD_PLACEMENT_CANCEL",
    "UNKNOWN",
)
_BUILD_UI_ROLE_SET = frozenset(BUILD_UI_ROLES)


def normalize_build_ui_role(value: Any) -> str:
    if not isinstance(value, str):
        return "UNKNOWN"
    role = value.strip().upper()
    return role if role in _BUILD_UI_ROLE_SET else "UNKNOWN"


def _label_slug(label: Any) -> str:
    if not isinstance(label, str) or not label.strip():
        return ""
    value = re.sub(r"\s+", "_", label.strip().lower())
    value = re.sub(r"[^\w\u4e00-\u9fff]+", "_", value, flags=re.UNICODE)
    return value.strip("_")


def canonical_build_ui_id(role: Any, label: Any, index: int) -> str:
    """Map a controlled semantic role to a stable runtime element ID."""
    normalized_role = normalize_build_ui_role(role)
    slug = _label_slug(label)
    if normalized_role == "BUILD_MENU_TOGGLE":
        return "build_menu_toggle"
    if normalized_role == "BUILD_MENU_OPEN":
        return "build_menu_open_control"
    if normalized_role == "BUILD_MENU_CLOSE":
        return "build_menu_close_control"
    if normalized_role == "BUILD_CATEGORY_TAB":
        return f"build_category_tab_{slug or index + 1}"
    if normalized_role in {"BUILD_OPTION", "BUILD_DISABLED_OPTION"}:
        return f"build_option_{slug or index + 1}"
    return f"unknown_element_{index + 1}"


class FrameSource(Protocol):
    def capture(self) -> tuple[bytes, int, int]: ...


class VisionAnalyzer(Protocol):
    def analyze_image_json(self, image: bytes, prompt: str, *, model: str | None = None) -> dict[str, Any]: ...


class RegionCatalog:
    """Normalized regions keep automation independent from window position."""

    DEFAULTS = (
        RegionSpec("resources", 0.00, 0.00, 0.30, 0.16, "只读取人口、金钱、粮食、木材、石材和劳动力数值。"),
        RegionSpec("map", 0.18, 0.12, 0.82, 0.90, "识别道路、建筑、空地、施工状态和明显阻塞。"),
        RegionSpec("events", 0.58, 0.04, 1.00, 0.42, "只识别任务、警告、剧情或需要决策的弹窗。"),
        RegionSpec("build_menu", 0.00, 0.78, 0.48, 1.00, "识别当前建筑分类、可建按钮和资源/科技限制。"),
        RegionSpec("build_controls", 0.00, 0.65, 1.00, 1.00, "只识别建筑菜单开关、关闭按钮、建筑栏和分类按钮，不分析地图。"),
        RegionSpec("build_entry", 0.60, 0.00, 1.00, 0.45, "只识别用于打开建筑/建设菜单的入口控件及必要的相邻 UI，不分析地图。"),
        RegionSpec("dialog", 0.22, 0.18, 0.78, 0.82, "只读取弹窗标题、正文、所有选项及按钮，不推测未显示的内容。"),
    )

    def __init__(self, regions: tuple[RegionSpec, ...] = DEFAULTS) -> None:
        self._regions = {region.name: region for region in regions}

    def get(self, name: str) -> RegionSpec:
        try:
            return self._regions[name]
        except KeyError as exc:
            raise KeyError(f"unknown perception region: {name}") from exc

    def names(self) -> tuple[str, ...]:
        return tuple(self._regions)


@dataclass
class PerceptionEngine:
    analyzer: VisionAnalyzer
    regions: RegionCatalog
    model: str | None = None

    def observe(self, frame: bytes, region_name: str, *, context: str = "") -> Observation:
        region = self.regions.get(region_name)
        return self._analyze(frame, region, context=context, crop_box=None)

    def observe_rgba(self, rgba: bytes, width: int, height: int, region_name: str, *, context: str = "") -> Observation:
        """Crop a real client-area frame before sending it to Qwen."""
        region = self.regions.get(region_name)
        return self._observe_region_rgba(rgba, width, height, region, context=context)

    def observe_custom_rgba(
        self,
        rgba: bytes,
        width: int,
        height: int,
        region: RegionSpec,
        *,
        context: str = "",
    ) -> Observation:
        """Analyze a calibration-only custom ROI without changing runtime catalog."""
        return self._observe_region_rgba(rgba, width, height, region, context=context)

    def observe_build_categories_rgba(
        self,
        rgba: bytes,
        width: int,
        height: int,
        *,
        context: str = "",
    ) -> Observation:
        """Run the one-shot, category-only calibration schema for Build Menu.

        Controls are deliberately excluded from this model request.  The
        read-only adapter resolves them locally from the formal catalog ROI.
        """
        return self._observe_structured_rgba(
            rgba,
            width,
            height,
            self.regions.get("build_controls"),
            key="categories",
            role="BUILD_CATEGORY_TAB",
            context=context,
        )

    def observe_build_options_rgba(
        self,
        rgba: bytes,
        width: int,
        height: int,
        *,
        context: str = "",
    ) -> Observation:
        """Run the one-shot, option-only calibration schema for Build Menu."""
        return self._observe_structured_rgba(
            rgba,
            width,
            height,
            self.regions.get("build_controls"),
            key="options",
            role="BUILD_OPTION",
            context=context,
        )

    def _observe_region_rgba(
        self,
        rgba: bytes,
        width: int,
        height: int,
        region: RegionSpec,
        *,
        context: str = "",
    ) -> Observation:
        left, top, right, bottom = region.crop_box(width, height)
        cropped_width, cropped_height = right - left, bottom - top
        if cropped_width <= 0 or cropped_height <= 0:
            raise ValueError(f"region {region_name} is empty at {width}x{height}")
        expected = width * height * 4
        if len(rgba) != expected:
            raise ValueError("RGBA buffer size does not match frame dimensions")
        cropped = b"".join(
            rgba[(row * width + left) * 4:(row * width + right) * 4]
            for row in range(top, bottom)
        )
        return self._analyze(
            encode_rgba_png(cropped_width, cropped_height, cropped),
            region,
            context=context,
            crop_box=(left, top, right, bottom),
        )

    def _observe_structured_rgba(
        self,
        rgba: bytes,
        width: int,
        height: int,
        region: RegionSpec,
        *,
        key: str,
        role: str,
        context: str,
    ) -> Observation:
        left, top, right, bottom = region.crop_box(width, height)
        cropped_width, cropped_height = right - left, bottom - top
        expected = width * height * 4
        if cropped_width <= 0 or cropped_height <= 0 or len(rgba) != expected:
            raise ValueError(f"{key} calibration frame is invalid")
        cropped = b"".join(
            rgba[(row * width + left) * 4:(row * width + right) * 4]
            for row in range(top, bottom)
        )
        prompt = (
            f"任务上下文：{context or '读取当前建筑菜单结构'}\n"
            f"只返回一个 JSON object，最外层必须是对象，不能是数组。只识别当前裁剪图中的{key}。"
            f"返回严格格式：{{\"{key}\":[{{\"id\":\"...\",\"label\":\"...\","
            "\"bbox\":[left,top,right,bottom],\"confidence\":0.0}}]}}。"
            "bbox 必须是当前裁剪图内的 0 到 1 归一化坐标；不可确认的字段使用空字符串，"
            "不要返回关闭按钮、切换按钮、其他控件或猜测坐标。"
        )
        result = self.analyzer.analyze_image_json(
            encode_rgba_png(cropped_width, cropped_height, cropped),
            prompt,
            model=self.model,
        )
        if not isinstance(result, dict) or not isinstance(result.get(key), list):
            raise ValueError("CALIBRATION_MODEL_SCHEMA_FAIL")
        normalized: list[dict[str, Any]] = []
        for index, item in enumerate(result[key]):
            if not isinstance(item, dict):
                raise ValueError("CALIBRATION_MODEL_SCHEMA_FAIL")
            raw_bbox = item.get("bbox")
            if not isinstance(raw_bbox, (list, tuple)) or len(raw_bbox) != 4:
                raise ValueError("CALIBRATION_MODEL_SCHEMA_FAIL")
            try:
                bbox = [float(value) for value in raw_bbox]
            except (TypeError, ValueError) as exc:
                raise ValueError("CALIBRATION_MODEL_SCHEMA_FAIL") from exc
            if not 0 <= bbox[0] < bbox[2] <= 1 or not 0 <= bbox[1] < bbox[3] <= 1:
                raise ValueError("CALIBRATION_MODEL_SCHEMA_FAIL")
            confidence = item.get("confidence")
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
                raise ValueError("CALIBRATION_MODEL_SCHEMA_FAIL")
            label = item.get("label")
            if not isinstance(label, str) or not label.strip():
                label = f"{key[:-1]}_{index + 1}"
            identifier = item.get("id")
            if not isinstance(identifier, str) or not identifier.strip():
                identifier = f"{key[:-1]}_{index + 1}"
            normalized.append({
                **item,
                "id": identifier.strip(),
                "label": label.strip(),
                "role": role,
                "confidence": float(confidence),
                "bbox": bbox,
                "global_bbox": region.local_to_global_bbox(bbox),
            })
        return Observation(
            data={key: normalized, "ui_elements": normalized},
            source="qwen-vision-calibration",
            region=region.name,
        )

    def _analyze(self, frame: bytes, region: RegionSpec, *, context: str, crop_box: tuple[int, int, int, int] | None) -> Observation:
        schema_instruction = ""
        if region.name in {"build_menu", "build_controls", "build_entry"}:
            schema_instruction = (
                "本区域必须额外返回 build_menu_open 布尔值和非空 current_screen 字符串；"
                "build_menu_open 表示建筑菜单当前是否可见。"
            )
        elif region.name == "dialog":
            schema_instruction = (
                "本区域必须额外返回 dialog_open 布尔值、非空 current_screen 字符串和 options 数组；"
                "dialog_open 表示弹窗当前是否可见；没有选项时 options 必须返回空数组。"
            )
        prompt = (
            f"任务上下文：{context or '读取当前区域状态'}\n"
            f"关注区域：{region.name}\n{region.focus_instruction}\n"
            "只返回一个 JSON object（最外层绝对不能是数组），只报告可从图像确认的事实，未知值使用 null。"
            "如果看见可操作控件，额外返回 ui_elements 数组；每项必须是"
            "{id: string, role: string, label: string, bbox: [left, top, right, bottom], confidence: number}，"
            "bbox 是相对于当前裁剪图的 0 到 1 归一化坐标，不要猜测不可见控件。"
            "建筑控件 role 只能使用 BUILD_MENU_TOGGLE、BUILD_MENU_OPEN、BUILD_MENU_CLOSE、"
            "BUILD_CATEGORY_TAB、BUILD_OPTION、BUILD_DISABLED_OPTION、UNKNOWN。"
            f"{schema_instruction}"
        )
        result = self.analyzer.analyze_image_json(frame, prompt, model=self.model)
        if not isinstance(result, dict):
            raise ValueError("vision analyzer must return a top-level JSON object")
        self._validate_region_schema(result, region)
        result = self._normalize_ui_elements(result, region)
        confidence = result.get("confidence")
        if confidence is not None and not isinstance(confidence, (int, float)):
            raise ValueError("vision confidence must be numeric")
        if crop_box is not None:
            result = {**result, "crop_box": crop_box}
        return Observation(data=result, source="qwen-vision", region=region.name, confidence=confidence)

    @staticmethod
    def _validate_region_schema(result: dict[str, Any], region: RegionSpec) -> None:
        if region.name in {"build_menu", "build_controls", "build_entry"}:
            if not isinstance(result.get("build_menu_open"), bool):
                raise ValueError("build_menu vision schema requires boolean build_menu_open")
            current_screen = result.get("current_screen")
            if not isinstance(current_screen, str) or not current_screen.strip():
                raise ValueError("build_menu vision schema requires non-empty current_screen")
            if not isinstance(result.get("ui_elements"), list):
                raise ValueError("build_menu vision schema requires ui_elements list")
        elif region.name == "dialog":
            if not isinstance(result.get("dialog_open"), bool):
                raise ValueError("dialog vision schema requires boolean dialog_open")
            current_screen = result.get("current_screen")
            if not isinstance(current_screen, str) or not current_screen.strip():
                raise ValueError("dialog vision schema requires non-empty current_screen")
            if not isinstance(result.get("options"), list):
                raise ValueError("dialog vision schema requires options list")
            if not isinstance(result.get("ui_elements"), list):
                raise ValueError("dialog vision schema requires ui_elements list")

    @staticmethod
    def _normalize_ui_elements(result: dict[str, Any], region: RegionSpec) -> dict[str, Any]:
        raw_elements = result.get("ui_elements")
        if raw_elements is None:
            return result
        if not isinstance(raw_elements, list):
            raise ValueError("vision ui_elements must be a list")
        normalized: list[dict[str, Any]] = []
        for item in raw_elements:
            if not isinstance(item, dict):
                raise ValueError("each ui element must be an object")
            raw_id = item.get("id")
            bbox = item.get("bbox")
            if not isinstance(raw_id, str) or not raw_id.strip():
                raw_id = f"vision_element_{len(normalized) + 1}"
            if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
                raise ValueError("ui element bbox must be [left, top, right, bottom]")
            try:
                values = [float(value) for value in bbox]
            except (TypeError, ValueError) as exc:
                raise ValueError("ui element bbox values must be numeric") from exc
            left, top, right, bottom = values
            if not 0 <= left < right <= 1 or not 0 <= top < bottom <= 1:
                raise ValueError("ui element bbox must use normalized coordinates between 0 and 1")
            role = normalize_build_ui_role(item.get("role"))
            element_confidence = item.get("confidence", result.get("confidence"))
            if element_confidence is not None and not isinstance(element_confidence, (int, float)):
                raise ValueError("ui element confidence must be numeric")
            canonical_id = canonical_build_ui_id(role, item.get("label"), len(normalized))
            normalized.append({
                **item,
                "id": canonical_id,
                "raw_id": raw_id.strip(),
                "canonical_id": canonical_id,
                "role": role,
                "bbox": values,
                "confidence": element_confidence,
                "global_bbox": region.local_to_global_bbox(values),
            })
        return {**result, "ui_elements": normalized}


class StaticFrameSource:
    """Test/dry-run frame source; it does not inspect or control a real game window."""

    def __init__(self, frame: bytes = b"dry-run-frame", width: int = 1920, height: int = 1080) -> None:
        self.frame, self.width, self.height = frame, width, height

    def capture(self) -> tuple[bytes, int, int]:
        return self.frame, self.width, self.height
