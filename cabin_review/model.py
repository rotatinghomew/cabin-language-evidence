"""数据模型、常量与装载。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# 关键错因：放行上限考核的三类。
CRITICAL_CAUSES = ("语义反转", "播放不清", "线路不适用")
# 译文本身固有的错因：同一真实译文在同场景内可共享证据。
INTRINSIC_CAUSES = ("语义反转", "播放不清")
# 随应用条件(旅程/场景)变化的错因：不随译文传递。
ROUTE_CAUSE = "线路不适用"
# 非错因类别。
NON_CRITICAL = {"正常建议"}

PATH_BLIND = "盲抽"        # 代表性入样：用于总体漏标率与版本比较
PATH_CLUE = "线索追查"      # 专为找故障挑出：不进总体率
PATH_NOT_SELECTED = "未入样"

# 复核结论状态
GOLD_ADJUDICATED = "裁定"
GOLD_AGREED = "一致"
GOLD_DISPUTED = "分歧未裁定"
GOLD_ABSENT = "已抽未审"
GOLD_NOT_SELECTED = "未入样"
GOLD_TRANSFERRED = "译文传递"


@dataclass(frozen=True)
class Play:
    play: str
    journey: str
    content: str
    version: str
    scene: str
    language: str
    day: str
    key_instruction: bool
    rendition: str


@dataclass(frozen=True)
class Draw:
    play: str
    feedback: str | None
    stratum: str
    probability: float
    draw: float
    path: str
    day: str


@dataclass(frozen=True)
class ReviewLabel:
    play: str
    reviewer: str
    labels: tuple
    date: str
    kind: str  # 初审 / 裁定


@dataclass(frozen=True)
class Feedback:
    feedback: str
    journey: str
    play: str
    language: str
    text: str
    received: str
    translation_of: str | None


@dataclass(frozen=True)
class Slot:
    slot: str
    reviewer: str
    day: str
    languages: tuple
    capacity: int
    critical: bool


@dataclass(frozen=True)
class Policy:
    scene: str
    language: str
    min_trips: int
    max_miss: float
    source_lang: str
    fallback: str | None


@dataclass(frozen=True)
class Override:
    content: str
    scene: str
    language: str
    version: str
    state: str  # 拟发布 / 在用
    equivalent: tuple
    day: str


class Data:
    """交接资料的只读视图。"""

    def __init__(self, root: str | Path):
        root = Path(root)

        def load(name):
            return json.loads((root / f"{name}.json").read_text(encoding="utf-8"))

        self.plays: dict[str, Play] = {}
        for r in load("playbacks"):
            self.plays[r["play"]] = Play(
                play=r["play"], journey=r["journey"], content=r["content"],
                version=r["version"], scene=r["scene"], language=r["language"],
                day=r["day"], key_instruction=bool(r["key_instruction"]),
                rendition=r["rendition"],
            )
        self.draws: dict[str, Draw] = {}
        for r in load("audit_draws"):
            self.draws[r["play"]] = Draw(
                play=r["play"], feedback=r["feedback"], stratum=r["stratum"],
                probability=float(r["probability"]), draw=float(r["draw"]),
                path=r["path"], day=r["day"],
            )
        self.firsts: dict[str, tuple] = {
            r["play"]: tuple(r["labels"]) for r in load("first_labels")
        }
        self.reviews: dict[str, list[ReviewLabel]] = {}
        for r in load("labels"):
            self.reviews.setdefault(r["play"], []).append(ReviewLabel(
                play=r["play"], reviewer=r["reviewer"],
                labels=tuple(r["labels"]), date=r["date"], kind=r["kind"],
            ))
        self.feedback = [
            Feedback(feedback=r["feedback"], journey=r["journey"], play=r["play"],
                     language=r["language"], text=r["text"], received=r["received"],
                     translation_of=r["translation_of"])
            for r in load("feedback")
        ]
        # 同一留言的翻译件不是独立观测。
        self.original_feedback = [f for f in self.feedback if f.translation_of is None]
        self.slots = [
            Slot(slot=r["slot"], reviewer=r["reviewer"], day=r["day"],
                 languages=tuple(r["languages"]), capacity=int(r["capacity"]),
                 critical=bool(r["critical"]))
            for r in load("review_slots")
        ]
        self.policy = [
            Policy(scene=r["scene"], language=r["language"],
                   min_trips=int(r["min_trips"]), max_miss=float(r["max_miss"]),
                   source_lang=r["source_lang"], fallback=r["fallback"])
            for r in load("release_policy")
        ]
        self.overrides = [
            Override(content=r["content"], scene=r["scene"], language=r["language"],
                     version=r["version"], state=r["state"],
                     equivalent=tuple(r["equivalent"]), day=r["day"])
            for r in load("overrides")
        ]

        self.rendition_plays: dict[str, list[str]] = {}
        for p in self.plays.values():
            self.rendition_plays.setdefault(p.rendition, []).append(p.play)
        self.journey_plays: dict[str, list[str]] = {}
        for p in self.plays.values():
            self.journey_plays.setdefault(p.journey, []).append(p.play)
        self.feedback_by_play: dict[str, list[Feedback]] = {}
        for f in self.original_feedback:
            self.feedback_by_play.setdefault(f.play, []).append(f)

    def plays_in(self, scene=None, language=None, version=None) -> list[Play]:
        out = []
        for p in self.plays.values():
            if scene is not None and p.scene != scene:
                continue
            if language is not None and p.language != language:
                continue
            if version is not None and p.version != version:
                continue
            out.append(p)
        return sorted(out, key=lambda p: p.play)

    @property
    def versions(self) -> list[str]:
        """版本按首播日先后排列(不按编码字典序)。"""
        first_day = {}
        for p in self.plays.values():
            first_day[p.version] = min(first_day.get(p.version, p.day), p.day)
        return sorted(first_day, key=lambda v: (first_day[v], v))
