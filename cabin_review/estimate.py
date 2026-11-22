"""漏标率估计：逆概率加权、区间不确定性与旅程聚类标准误。

只用盲抽样本估计总体漏标率与版本比较；线索追查片段另列，不进样本。
每个播出-错因对按 1/登记概率 加权。已确认部分给点估计；分歧未裁定、
已抽未审的未知项不按无漏标计，而是展开为区间上下限：
  下限(乐观)：未知错因均视为不存在；
  上限(悲观)：未知错因均视为存在(初分未标的成为漏标，初分已标的计入真错因)。
抽样不确定性用按旅程聚类的比率估计量标准误表示(CR1 调整)。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .model import CRITICAL_CAUSES, PATH_BLIND, PATH_CLUE, Data
from .review import (
    ST_CAUGHT,
    ST_MISSED,
    ST_POTENTIAL,
    ST_UNVERIFIED,
    Gold,
)


@dataclass
class Estimate:
    """一个层(或版本)的漏标率估计。"""

    scope: str
    sample_plays: int = 0
    sample_journeys: int = 0
    weight_total: float = 0.0
    missed_w: float = 0.0        # 已确认漏标(加权)
    true_w: float = 0.0          # 已确认真错因(加权)
    potential_w: float = 0.0     # 可能漏标(加权)
    unverified_w: float = 0.0    # 初分已标但无法核实(加权)
    point: float | None = None   # 已确认漏标率 = missed_w / true_w
    upper: float | None = None   # 悲观上限
    se: float | None = None      # 旅程聚类标准误(基于已确认比率)
    ci: tuple | None = None      # 95% 置信区间(仅抽样不确定性)
    per_cause: dict = field(default_factory=dict)
    plays_with_miss: int = 0     # 含至少一个已确认漏标的播出数
    resolved_plays: int = 0      # 金标准完全已知的播出数

    def as_dict(self):
        return {
            "scope": self.scope,
            "sample_plays": self.sample_plays,
            "sample_journeys": self.sample_journeys,
            "weight_total": round(self.weight_total, 4),
            "missed_w": round(self.missed_w, 4),
            "true_w": round(self.true_w, 4),
            "potential_w": round(self.potential_w, 4),
            "unverified_w": round(self.unverified_w, 4),
            "point": None if self.point is None else round(self.point, 4),
            "upper": None if self.upper is None else round(self.upper, 4),
            "se": None if self.se is None else round(self.se, 4),
            "ci": None if self.ci is None else [round(x, 4) for x in self.ci],
            "per_cause": self.per_cause,
            "plays_with_miss": self.plays_with_miss,
            "resolved_plays": self.resolved_plays,
        }


def estimate(scope: str, plays, data: Data, golds, statuses) -> Estimate:
    """对给定播出集合中的盲抽样本估计漏标率。"""
    est = Estimate(scope=scope)
    sample = [p for p in plays if data.draws[p.play].path == PATH_BLIND]
    est.sample_plays = len(sample)
    est.sample_journeys = len({p.journey for p in sample})
    per_cause = {c: {"missed_w": 0.0, "true_w": 0.0, "potential_w": 0.0}
                 for c in CRITICAL_CAUSES}
    # 旅程聚类用的贡献量
    cluster_resid = {}
    for p in sample:
        w = 1.0 / data.draws[p.play].probability
        est.weight_total += w
        missed_any = False
        resolved_all = True
        for c in CRITICAL_CAUSES:
            st = statuses[p.play][c]
            if st == ST_MISSED:
                est.missed_w += w
                est.true_w += w
                per_cause[c]["missed_w"] += w
                per_cause[c]["true_w"] += w
                missed_any = True
                y, x = 1.0, 1.0
            elif st == ST_CAUGHT:
                est.true_w += w
                per_cause[c]["true_w"] += w
                y, x = 0.0, 1.0
            elif st == ST_POTENTIAL:
                est.potential_w += w
                per_cause[c]["potential_w"] += w
                resolved_all = False
                y, x = 0.0, 0.0
            elif st == ST_UNVERIFIED:
                est.unverified_w += w
                resolved_all = False
                y, x = 0.0, 0.0
            else:  # clear / over_claimed：已确认无此错因
                y, x = 0.0, 0.0
            cluster_resid.setdefault(p.journey, []).append((w, y, x))
        est.plays_with_miss += int(missed_any)
        est.resolved_plays += int(resolved_all)
    est.per_cause = {c: {k: round(v, 4) for k, v in d.items()}
                     for c, d in per_cause.items()}
    if est.true_w > 0:
        est.point = est.missed_w / est.true_w
    den_upper = est.true_w + est.potential_w + est.unverified_w
    if den_upper > 0:
        est.upper = (est.missed_w + est.potential_w) / den_upper
    elif est.sample_plays > 0:
        est.upper = 0.0  # 样本全部已确认无关键错因
    # 旅程聚类的比率标准误(CR1)
    if est.point is not None and est.sample_journeys > 1:
        r = est.point
        z = []
        for j, contribs in cluster_resid.items():
            zj = sum(w * (y - r * x) for w, y, x in contribs)
            z.append(zj)
        g = len(z)
        var = (g / (g - 1)) * sum(v * v for v in z) / (est.true_w ** 2)
        est.se = math.sqrt(var)
        lo = max(0.0, r - 1.96 * est.se)
        hi = min(1.0, r + 1.96 * est.se)
        est.ci = (lo, hi)
    return est


def version_estimates(data: Data, golds, statuses) -> dict[str, Estimate]:
    """版本比较：同一口径(盲抽、逆概率加权)下各版本的漏标率。"""
    out = {}
    for v in data.versions:
        out[v] = estimate(f"版本-{v}", data.plays_in(version=v), data, golds, statuses)
    return out


def coverage(scene: str, language: str, data: Data, golds) -> dict:
    """一个场景-语言层的覆盖情况。"""
    plays = data.plays_in(scene=scene, language=language)
    journeys = {p.journey for p in plays}
    blind, clue, not_selected, zero_prob = [], [], [], []
    reviewed, disputed, absent_covered, absent_open = [], [], [], []
    for p in plays:
        d = data.draws[p.play]
        if d.probability == 0:
            zero_prob.append(p.play)
        if d.path == PATH_BLIND:
            blind.append(p.play)
        elif d.path == PATH_CLUE:
            clue.append(p.play)
        else:
            not_selected.append(p.play)
        g = golds[p.play]
        if g.evidence == "direct":
            reviewed.append(p.play)
            if g.state == "分歧未裁定":
                disputed.append(p.play)
        elif d.path == PATH_BLIND:
            # 盲抽已抽未审：区分译文传递已部分覆盖与完全未知；
            # 线索追查片段的复核状态在报告专项部分单列
            if g.known:
                absent_covered.append(p.play)
            else:
                absent_open.append(p.play)
    journeys_reviewed = {data.plays[pid].journey for pid in reviewed}
    journeys_resolved = {
        data.plays[pid].journey for pid in reviewed
        if all(golds[pid].causes[c] is not None for c in CRITICAL_CAUSES)
    }
    renditions = {p.rendition for p in plays}
    renditions_direct = {p.rendition for p in plays
                         if golds[p.play].evidence == "direct" and golds[p.play].known}
    renditions_covered = {p.rendition for p in plays if golds[p.play].known}
    return {
        "scene": scene,
        "language": language,
        "plays": len(plays),
        "journeys": len(journeys),
        "blind": len(blind),
        "clue": len(clue),
        "not_selected": len(not_selected),
        "zero_prob": len(zero_prob),
        "reviewed": len(reviewed),
        "disputed": sorted(disputed),
        "absent_covered": sorted(absent_covered),
        "absent_open": sorted(absent_open),
        "journeys_reviewed": len(journeys_reviewed),
        "journeys_resolved": len(journeys_resolved),
        "renditions": len(renditions),
        "renditions_direct": len(renditions_direct),
        "renditions_covered": len(renditions_covered),
    }


def no_feedback_coverage(data: Data, golds) -> dict:
    """无留言播出的覆盖：证明没投诉的播报也被抽查到。"""
    no_fb = [p for p in data.plays.values() if p.play not in data.feedback_by_play]
    blind = [p for p in no_fb if data.draws[p.play].path == PATH_BLIND]
    reviewed = [p for p in no_fb if golds[p.play].evidence == "direct"]
    covered = [p for p in no_fb if golds[p.play].known]
    return {
        "plays": len(no_fb),
        "blind": len(blind),
        "reviewed": len(reviewed),
        "covered": len(covered),
    }
