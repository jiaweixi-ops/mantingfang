from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

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
        prompt = (
            f"任务上下文：{context or '读取当前区域状态'}\n"
            f"关注区域：{region.name}\n{region.focus_instruction}\n"
            "只返回可从图像确认的事实，未知值使用 null；返回 JSON。"
        )
        result = self.analyzer.analyze_image_json(frame, prompt, model=self.model)
        confidence = result.get("confidence")
        if confidence is not None and not isinstance(confidence, (int, float)):
            raise ValueError("vision confidence must be numeric")
        return Observation(data=result, source="deepseek-vision", region=region_name, confidence=confidence)


class StaticFrameSource:
    """Test/dry-run frame source; it does not inspect or control a real game window."""

    def __init__(self, frame: bytes = b"dry-run-frame", width: int = 1920, height: int = 1080) -> None:
        self.frame, self.width, self.height = frame, width, height

    def capture(self) -> tuple[bytes, int, int]:
        return self.frame, self.width, self.height
