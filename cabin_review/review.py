"""盲审金标准解析、译文证据传递与漏标分类。

- 金标准：有裁定用裁定(只取 as_of 当日及之前可见的)，否则看双人初审
  是否一致；分歧且无裁定的错因保持未知，不按无漏标计。
- 译文传递：同一真实译文在同场景内的已完成复核，可传递语义反转、
  播放不清两类译文固有结论；线路不适用随应用条件变化，不传递。
  跨场景不传递(一条线路上的通过不能当成另一线路的独立抽样)。
- 漏标分类只针对关键错因，基准是抽核前内容席的初分(first_labels)。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .model import (
    CRITICAL_CAUSES,
    GOLD_ABSENT,
    GOLD_ADJUDICATED,
    GOLD_AGREED,
    GOLD_DISPUTED,
    GOLD_NOT_SELECTED,
    GOLD_TRANSFERRED,
    INTRINSIC_CAUSES,
    PATH_BLIND,
    PATH_CLUE,
    Data,
)

# 漏标分类取值
ST_CAUGHT = "caught"                # 金标准确认有，初分已标
ST_MISSED = "missed"                # 金标准确认有，初分漏标
ST_CLEAR = "clear"                  # 金标准确认无，初分未标
ST_OVER = "over_claimed"            # 金标准确认无，初分误标
ST_POTENTIAL = "potential_miss"     # 金标准未知，初分未标：可能漏标
ST_UNVERIFIED = "claimed_unverified"  # 金标准未知，初分已标：无法核实


@dataclass
class Gold:
    """一段播出的关键错因金标准。causes[c] ∈ {True, False, None(未知)}。"""

    state: str
    causes: dict
    evidence: str = "direct"          # direct / transferred / none
    transfer_from: tuple = ()         # 证据来源播出号

    @property
    def known(self) -> bool:
        return any(v is not None for v in self.causes.values())


def direct_gold(data: Data, play_id: str, as_of: str | None = None) -> Gold:
    """由双人复核记录解析单段播出的金标准(不做译文传递)。"""
    reviews = data.reviews.get(play_id, [])
    adjudications = [r for r in reviews if r.kind == "裁定"
                     and (as_of is None or r.date <= as_of)]
    if adjudications:
        latest = max(adjudications, key=lambda r: r.date)
        labels = set(latest.labels)
        return Gold(state=GOLD_ADJUDICATED,
                    causes={c: c in labels for c in CRITICAL_CAUSES})
    first_pass = [r for r in reviews if r.kind == "初审"]
    if len(first_pass) >= 2:
        a, b = first_pass[0], first_pass[1]
        la, lb = set(a.labels), set(b.labels)
        causes = {}
        for c in CRITICAL_CAUSES:
            if (c in la) == (c in lb):
                causes[c] = c in la
            else:
                causes[c] = None
        state = GOLD_AGREED if all(v is not None for v in causes.values()) \
            else GOLD_DISPUTED
        return Gold(state=state, causes=causes)
    draw = data.draws.get(play_id)
    if draw is not None and draw.path in (PATH_BLIND, PATH_CLUE):
        state = GOLD_ABSENT
    else:
        state = GOLD_NOT_SELECTED
    return Gold(state=state, causes={c: None for c in CRITICAL_CAUSES},
                evidence="none")


def resolve_golds(data: Data, as_of: str | None = None) -> dict[str, Gold]:
    """全部播出的金标准：先直接复核，再对无直接复核的播出做译文传递。"""
    golds = {pid: direct_gold(data, pid, as_of) for pid in data.plays}
    for play in data.plays.values():
        g = golds[play.play]
        if g.state not in (GOLD_ABSENT, GOLD_NOT_SELECTED):
            continue
        # 同一真实译文、同场景、已完成直接复核的播出提供共享证据。
        donors = []
        for other_id in data.rendition_plays[play.rendition]:
            if other_id == play.play:
                continue
            other = data.plays[other_id]
            if other.scene != play.scene:
                continue  # 应用条件不同：不能把另一线路的复核当独立抽样
            og = golds[other_id]
            if og.evidence == "direct" and og.known:
                donors.append(og)
        causes = {}
        for c in CRITICAL_CAUSES:
            if c not in INTRINSIC_CAUSES:
                causes[c] = None  # 线路不适用随应用条件变化，不传递
                continue
            values = {d.causes[c] for d in donors if d.causes[c] is not None}
            causes[c] = values.pop() if len(values) == 1 else None
        if any(v is not None for v in causes.values()):
            from_ids = tuple(sorted(
                pid for pid in data.rendition_plays[play.rendition]
                if pid != play.play
                and data.plays[pid].scene == play.scene
                and golds[pid].evidence == "direct" and golds[pid].known
            ))
            golds[play.play] = Gold(state=GOLD_TRANSFERRED, causes=causes,
                                    evidence="transferred", transfer_from=from_ids)
    return golds


def miss_status(first_labels: tuple, gold: Gold) -> dict[str, str]:
    """单个播出在各关键错因上的漏标分类。"""
    first = set(first_labels)
    out = {}
    for c in CRITICAL_CAUSES:
        g = gold.causes[c]
        if g is True:
            out[c] = ST_CAUGHT if c in first else ST_MISSED
        elif g is False:
            out[c] = ST_OVER if c in first else ST_CLEAR
        else:
            out[c] = ST_UNVERIFIED if c in first else ST_POTENTIAL
    return out


def resolve_all(data: Data, as_of: str | None = None):
    """返回 (golds, statuses)：golds 见上；statuses[play][cause] 为漏标分类。"""
    golds = resolve_golds(data, as_of)
    statuses = {pid: miss_status(data.firsts[pid], golds[pid]) for pid in data.plays}
    return golds, statuses
