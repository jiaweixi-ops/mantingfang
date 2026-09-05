from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .capture import encode_rgba_png
from .models import Observation, RegionSpec


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
        """Crop a real client-area frame before sending it to DeepSeek."""
        region = self.regions.get(region_name)
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

    def _analyze(self, frame: bytes, region: RegionSpec, *, context: str, crop_box: tuple[int, int, int, int] | None) -> Observation:
        prompt = (
            f"任务上下文：{context or '读取当前区域状态'}\n"
            f"关注区域：{region.name}\n{region.focus_instruction}\n"
            "只返回可从图像确认的事实，未知值使用 null；返回 JSON。"
            "如果看见可操作控件，额外返回 ui_elements 数组；每项必须是"
            "{id: string, label: string, bbox: [left, top, right, bottom]}，"
            "bbox 是相对于当前裁剪图的 0 到 1 归一化坐标，不要猜测不可见控件。"
        )
        result = self.analyzer.analyze_image_json(frame, prompt, model=self.model)
        result = self._normalize_ui_elements(result)
        confidence = result.get("confidence")
        if confidence is not None and not isinstance(confidence, (int, float)):
            raise ValueError("vision confidence must be numeric")
        if crop_box is not None:
            result = {**result, "crop_box": crop_box}
        return Observation(data=result, source="deepseek-vision", region=region.name, confidence=confidence)

    @staticmethod
    def _normalize_ui_elements(result: dict[str, Any]) -> dict[str, Any]:
        raw_elements = result.get("ui_elements")
        if raw_elements is None:
            return result
        if not isinstance(raw_elements, list):
            raise ValueError("vision ui_elements must be a list")
        normalized: list[dict[str, Any]] = []
        for item in raw_elements:
            if not isinstance(item, dict):
                raise ValueError("each ui element must be an object")
            element_id = item.get("id")
            bbox = item.get("bbox")
            if not isinstance(element_id, str) or not element_id.strip():
                raise ValueError("each ui element requires a non-empty id")
            if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
                raise ValueError("ui element bbox must be [left, top, right, bottom]")
            try:
                values = [float(value) for value in bbox]
            except (TypeError, ValueError) as exc:
                raise ValueError("ui element bbox values must be numeric") from exc
            left, top, right, bottom = values
            if not 0 <= left < right <= 1 or not 0 <= top < bottom <= 1:
                raise ValueError("ui element bbox must use normalized coordinates between 0 and 1")
            normalized.append({**item, "id": element_id.strip(), "bbox": values})
        return {**result, "ui_elements": normalized}


class StaticFrameSource:
    """Test/dry-run frame source; it does not inspect or control a real game window."""

    def __init__(self, frame: bytes = b"dry-run-frame", width: int = 1920, height: int = 1080) -> None:
        self.frame, self.width, self.height = frame, width, height

    def capture(self) -> tuple[bytes, int, int]:
        return self.frame, self.width, self.height
