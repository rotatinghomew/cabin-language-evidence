"""汇总一次审查的状态，以及与上一轮状态的差异。

状态文件留档“当时批准了什么、还缺什么、哪些旧提示已停用”。
新的盲审裁定改变关键错因与复用范围时，diff 给出：
- 总体判断哪些要重算(闸口判定变化)；
- 在用版本哪些要收窄；
- 本轮已启动的补抽是否还能回答原问题。
"""
from __future__ import annotations

from .estimate import no_feedback_coverage
from .gates import evaluate_all
from .ledger import (
    confirmed_causes_on,
    fallback_status,
    override_review,
    propagation,
    retired_renditions,
)
from .model import CRITICAL_CAUSES, PATH_CLUE, Data
from .plan import (
    adjudication_items,
    draw_candidates,
    recommend_scope,
    schedule,
)
from .review import resolve_all


def build_state(data: Data, as_of: str | None = None,
                dispatched: list[dict] | None = None) -> dict:
    """对当前可见资料做一次完整漏标审查，返回可 JSON 序列化的状态。"""
    golds, statuses = resolve_all(data, as_of)
    gates, strata_est, strata_cov, other_est, v_est = evaluate_all(
        data, golds, statuses)

    # 补抽建议与候选
    rec = recommend_scope(data, gates, statuses)
    candidates = []
    if rec.get("scope"):
        candidates = draw_candidates(
            data, rec["scope"], golds, statuses,
            pending_plays=frozenset(rec.get("pending_plays", ())))
    # 范围外待补证据：补抽覆盖不到，列入专项追查
    chosen_pending = set(rec.get("pending_plays", ()))
    special = []
    for gate in gates:
        if gate["verdict"] != "待补证":
            continue
        for item in gate["pending"]:
            if item["play"] in chosen_pending:
                continue
            p = data.plays[item["play"]]
            special.append({
                "play": item["play"], "version": p.version,
                "scene": p.scene, "language": p.language,
                "key_instruction": p.key_instruction,
                "unknown_causes": item["unknown_causes"],
                "gate": f"{gate['scene']}-{gate['language']}",
            })
    # 班位编排：补抽复核 + 专项追查 + 初审分歧裁定
    items = []
    for c in candidates:
        items.append({
            "play": c["play"], "kind": "补抽复核",
            "language": c["language"],
            "key_instruction": c["key_instruction"],
            "priority": 0 if c["gate_critical"] else 1,
        })
    for s in special:
        items.append({
            "play": s["play"], "kind": "专项追查",
            "language": s["language"],
            "key_instruction": s["key_instruction"],
            "priority": 0,
        })
    for it in adjudication_items(data, golds, gates):
        it["priority"] = 0 if it["gated"] else 1
        items.append(it)
    assignments, unscheduled = schedule(data, items, dispatched)
    assignments.sort(key=lambda a: (a["day"], a["slot"], a["play"]))
    # 班位用量：多项申请抢同一席位时，要看是否还能一同完成
    capacity = {}
    for s in data.slots:
        capacity[s.reviewer] = capacity.get(s.reviewer, 0) + s.capacity
    used = {}
    for a in assignments:
        used[a["reviewer"]] = used.get(a["reviewer"], 0) + 1
    slot_usage = [
        {"reviewer": r, "used": used.get(r, 0), "capacity": c}
        for r, c in sorted(capacity.items())
    ]

    # 线索追查片段：只列状态，不进总体率
    clue_items = []
    for p in data.plays.values():
        if data.draws[p.play].path != PATH_CLUE:
            continue
        g = golds[p.play]
        clue_items.append({
            "play": p.play, "version": p.version, "scene": p.scene,
            "language": p.language,
            "feedback": sorted(f.feedback for f in
                               data.feedback_by_play.get(p.play, [])),
            "first_labels": list(data.firsts[p.play]),
            "gold_state": g.state,
            "gold_causes": {c: g.causes[c] for c in CRITICAL_CAUSES
                            if g.causes[c] is not None},
            "transfer_from": list(g.transfer_from),
        })

    fb = {
        "total": len(data.feedback),
        "original": len(data.original_feedback),
        "translations": len(data.feedback) - len(data.original_feedback),
    }
    ledger = {
        "overrides": override_review(data, golds, gates),
        "fallbacks": [
            dict(scene=pol.scene, language=pol.language,
                 **fallback_status(data, golds, pol.scene, pol.language,
                                   pol.fallback))
            for pol in data.policy
        ],
        "propagation": propagation(data, golds),
        "retired": retired_renditions(data),
    }
    return {
        "as_of": as_of,
        "gates": gates,
        "other_strata": {f"{k[0]}|{k[1]}": e.as_dict()
                         for k, e in other_est.items()},
        "versions": {v: e.as_dict() for v, e in v_est.items()},
        "no_feedback": no_feedback_coverage(data, golds),
        "feedback": fb,
        "clue_items": clue_items,
        "supplementary": {
            "recommendation": rec,
            "candidates": candidates,
            "special": special,
            "assignments": assignments,
            "unscheduled": unscheduled,
            "slot_usage": slot_usage,
        },
        "ledger": ledger,
    }


def _gate_map(state):
    return {(g["scene"], g["language"]): g for g in state["gates"]}


def diff_states(old: dict, new: dict) -> dict:
    """比较两次审查状态，给出要重算、要收窄与补抽有效性。"""
    old_g, new_g = _gate_map(old), _gate_map(new)
    recompute = []
    for key in sorted(set(old_g) | set(new_g)):
        o, n = old_g.get(key), new_g.get(key)
        if o is None or n is None:
            recompute.append({"gate": key, "change": "新增/移除"})
            continue
        changes = []
        if o["verdict"] != n["verdict"]:
            changes.append(f"判定 {o['verdict']} → {n['verdict']}")
        for fld in ("point", "upper"):
            ov, nv = o["estimate"][fld], n["estimate"][fld]
            if ov != nv:
                fmt = lambda x: "—" if x is None else f"{x:.1%}"
                changes.append(f"{fld} {fmt(ov)} → {fmt(nv)}")
        if changes:
            recompute.append({"gate": key, "change": "；".join(changes)})
    old_narrow = {(e["content"], e["scene"], e["language"], e["version"])
                  for e in old["ledger"]["overrides"]["in_use"] if e["narrow"]}
    new_narrow = {(e["content"], e["scene"], e["language"], e["version"])
                  for e in new["ledger"]["overrides"]["in_use"] if e["narrow"]}
    narrowing = sorted(new_narrow - old_narrow)
    relaxing = sorted(old_narrow - new_narrow)

    # 复用范围变化：共用译文上的已确认错因集合
    def prop_map(state):
        return {p["rendition"]: tuple(p["causes"])
                for p in state["ledger"]["propagation"]}
    old_p, new_p = prop_map(old), prop_map(new)
    propagation_changes = [
        {"rendition": r,
         "change": f"{'/'.join(old_p.get(r, ())) or '无'} → "
                   f"{'/'.join(new_p.get(r, ())) or '无'}"}
        for r in sorted(set(old_p) | set(new_p))
        if old_p.get(r) != new_p.get(r)
    ]

    # 补抽有效性：原问题涉及的闸口现在是否仍待补证
    supp_old = old["supplementary"]["recommendation"]
    supp_check = {"scope": supp_old.get("scope"), "status": "无需补抽", "notes": []}
    if supp_old.get("scope"):
        open_gates = []
        for gname in supp_old.get("gates", []):
            scene, _, language = gname.partition("-")
            gate = new_g.get((scene, language))
            if gate is not None and gate["verdict"] == "待补证":
                open_gates.append(gname)
        if open_gates:
            supp_check["status"] = "仍然有效"
            supp_check["notes"] = [f"{g} 仍待补证，补抽还能回答原问题"
                                   for g in open_gates]
        else:
            supp_check["status"] = "问题已变化"
            supp_check["notes"] = [
                "原待补证闸口已有结论，请核对本轮补抽是否仍按原范围执行"]
    return {
        "recompute": recompute,
        "narrowing_added": [list(x) for x in narrowing],
        "narrowing_relax": [list(x) for x in relaxing],
        "propagation_changes": propagation_changes,
        "supplementary": supp_check,
    }
