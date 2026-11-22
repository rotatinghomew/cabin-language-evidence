"""关键用途放行闸口评估。

判定口径：
- 阻断：独立审核旅程数低于 min_trips(含登记概率为 0、结构性无观察机会)；
- 不通过：已确认漏标率(区间下限)已超 max_miss；
- 通过：悲观上限也不超 max_miss；
- 待补证：区间跨上限——列出能解除限制的待补证据。
"""
from __future__ import annotations

from .estimate import Estimate
from .model import CRITICAL_CAUSES, PATH_BLIND, Data, Policy
from .review import ST_POTENTIAL, ST_UNVERIFIED

VERDICT_PASS = "通过"
VERDICT_PENDING = "待补证"
VERDICT_FAIL = "不通过"
VERDICT_BLOCKED = "阻断"


def evaluate_gate(policy: Policy, est: Estimate, cov: dict, data: Data,
                  statuses) -> dict:
    reasons = []
    if cov["journeys_reviewed"] < policy.min_trips:
        verdict = VERDICT_BLOCKED
        reasons.append(
            f"独立审核旅程 {cov['journeys_reviewed']} 旅程 < 下限 {policy.min_trips}")
        if cov["zero_prob"] > 0:
            reasons.append(f"{cov['zero_prob']} 段登记概率为 0，没有观察机会")
        if cov["journeys"] < policy.min_trips:
            reasons.append(
                f"近期窗口内该层总共只有 {cov['journeys']} 个旅程，"
                "即使全部复核也达不到下限，补抽无法解除")
    elif est.point is not None and est.point > policy.max_miss:
        verdict = VERDICT_FAIL
        reasons.append(
            f"已确认漏标率 {round(est.point, 4):.1%} > 上限 {policy.max_miss:.0%}，"
            "不确定性不影响方向")
    elif est.upper is not None and est.upper <= policy.max_miss:
        verdict = VERDICT_PASS
        reasons.append(
            f"悲观上限 {round(est.upper, 4):.1%} ≤ 上限 {policy.max_miss:.0%}")
    else:
        verdict = VERDICT_PENDING
        upper = "—" if est.upper is None else f"{round(est.upper, 4):.1%}"
        reasons.append(
            f"已确认漏标率未超上限，但悲观上限 {upper} 跨上限 "
            f"{policy.max_miss:.0%}")
    # 待补证据：盲抽样本中仍未知的播出-错因(带加权贡献，供补抽评估)
    pending = []
    for p in data.plays_in(scene=policy.scene, language=policy.language):
        draw = data.draws[p.play]
        if draw.path != PATH_BLIND:
            continue
        unknown = [c for c in CRITICAL_CAUSES
                   if statuses[p.play][c] in (ST_POTENTIAL, ST_UNVERIFIED)]
        if unknown:
            w = 1.0 / draw.probability
            pending.append({
                "play": p.play,
                "version": p.version,
                "journey": p.journey,
                "unknown_causes": list(unknown),
                "potential_w": round(
                    w * sum(1 for c in unknown
                            if statuses[p.play][c] == ST_POTENTIAL), 4),
                "unverified_w": round(
                    w * sum(1 for c in unknown
                            if statuses[p.play][c] == ST_UNVERIFIED), 4),
                "gold_state": None,  # 由调用方补充
            })
    return {
        "scene": policy.scene,
        "language": policy.language,
        "min_trips": policy.min_trips,
        "max_miss": policy.max_miss,
        "fallback": policy.fallback,
        "verdict": verdict,
        "reasons": reasons,
        "estimate": est.as_dict(),
        "coverage": cov,
        "pending": pending,
    }


def evaluate_all(data: Data, golds, statuses):
    """返回 (gates, strata_estimates, strata_coverage, version_ests)。"""
    from .estimate import coverage, estimate, version_estimates

    gates = []
    strata_est = {}
    strata_cov = {}
    for pol in data.policy:
        plays = data.plays_in(scene=pol.scene, language=pol.language)
        est = estimate(f"{pol.scene}-{pol.language}", plays, data, golds, statuses)
        cov = coverage(pol.scene, pol.language, data, golds)
        gate = evaluate_gate(pol, est, cov, data, statuses)
        for item in gate["pending"]:
            item["gold_state"] = golds[item["play"]].state
        gates.append(gate)
        strata_est[(pol.scene, pol.language)] = est
        strata_cov[(pol.scene, pol.language)] = cov
    # 非考核层也给估计，供总体判断与版本比较参考
    all_keys = sorted({(p.scene, p.language) for p in data.plays.values()})
    other_est = {}
    for scene, lang in all_keys:
        if (scene, lang) in strata_est:
            continue
        plays = data.plays_in(scene=scene, language=lang)
        other_est[(scene, lang)] = estimate(
            f"{scene}-{lang}", plays, data, golds, statuses)
    v_est = version_estimates(data, golds, statuses)
    return gates, strata_est, strata_cov, other_est, v_est
