"""补抽范围建议与复核班位编排。

补抽建议：负责人只能申请一个(语言, 版本)范围。候选范围按“哪些证据
可能解除发布限制”排序——能把待补证闸口的不确定性收敛到上限之内
的范围优先；结构性达不到 min_trips 的层不浪费补抽。

班位编排：把补抽复核与初审分歧裁定一起排进班位。约束：
- 复核席须同时具备源语言与目标语言能力(两种语言的审核资格)；
- 关键提示须由有关键指引资格的席位完成；
- 已发给某席位待确认的复核仍占该席位班位；
- 多项申请抢同一席位时给出能一同完成的安排，排不下就明说。
"""
from __future__ import annotations

from .gates import VERDICT_BLOCKED, VERDICT_PENDING
from .model import CRITICAL_CAUSES, PATH_BLIND, PATH_CLUE, Data
from .review import ST_POTENTIAL, ST_UNVERIFIED


def recommend_scope(data: Data, gates, statuses) -> dict:
    """推荐一个(语言, 版本)补抽范围，并说明它能回答的问题。

    对每个待补证闸口，模拟某范围待补证据全部有利化解后的残余悲观
    上限：能压回上限以内的范围才值得申请；都不足时取残余最小者并
    明说单靠本轮补抽不能放行。
    """
    evaluations = []
    for gate in gates:
        if gate["verdict"] != VERDICT_PENDING:
            continue
        est = gate["estimate"]
        missed_w = est["missed_w"]
        true_w = est["true_w"]
        scopes = {}
        for item in gate["pending"]:
            key = (gate["language"], item["version"])
            scopes.setdefault(key, []).append(item)
        for (language, version), items in scopes.items():
            in_scope = {it["play"] for it in items}
            out_potential = sum(it["potential_w"] for it in gate["pending"]
                                if it["play"] not in in_scope)
            out_unverified = sum(it["unverified_w"] for it in gate["pending"]
                                 if it["play"] not in in_scope)
            den = true_w + out_potential + out_unverified
            residual = None if den <= 0 else (missed_w + out_potential) / den
            evaluations.append({
                "scope": {"language": language, "version": version},
                "gate": f"{gate['scene']}-{gate['language']}",
                "max_miss": gate["max_miss"],
                "pending_plays": sorted(in_scope),
                "residual_upper": residual,
                "lifts": residual is not None and residual <= gate["max_miss"],
            })
    # 阻断闸口：补抽能否解除？
    blocked_notes = []
    for gate in gates:
        if gate["verdict"] != VERDICT_BLOCKED:
            continue
        cov = gate["coverage"]
        if cov["journeys"] < gate["min_trips"]:
            blocked_notes.append(
                f"{gate['scene']}-{gate['language']}：近期仅 {cov['journeys']} "
                f"个旅程 < 下限 {gate['min_trips']}，补抽无法解除，不占用申请")
        else:
            blocked_notes.append(
                f"{gate['scene']}-{gate['language']}：可考虑补抽创造观察机会")
    if not evaluations:
        return {"scope": None, "reason": "没有待补证闸口需要补抽",
                "blocked_notes": blocked_notes}
    # 优先能解除限制的范围；并列取残余上限更低者
    evaluations.sort(key=lambda e: (not e["lifts"],
                                    e["residual_upper"] if e["residual_upper"] is not None else 9))
    best = evaluations[0]
    out = {
        "scope": best["scope"],
        "gates": [best["gate"]],
        "pending_plays": best["pending_plays"],
        "residual_upper": best["residual_upper"],
        "lifts": best["lifts"],
        "question": f"{best['gate']} 的悲观上限能否降到 {best['max_miss']:.0%} 以内",
        "blocked_notes": blocked_notes,
        "evaluations": evaluations,
    }
    if not best["lifts"]:
        out["caveat"] = (
            f"即使该范围全部有利化解，残余悲观上限仍约 "
            f"{best['residual_upper']:.1%} > {best['max_miss']:.0%}；"
            "单靠本轮补抽不能放行该层，范围外的待补证据需另行核实(专项追查)")
    return out


def draw_candidates(data: Data, scope: dict, golds, statuses,
                    pending_plays=frozenset()) -> list[dict]:
    """范围内译文尚无直接复核的播出，按译文去重后作为补抽候选。

    代表性抽取先给每个候选留参与机会(登记概率)；同一真实译文只需
    复核其中一段(优先不占关键资格的播出)，结论在同场景内传递。
    """
    if not scope:
        return []
    plays = data.plays_in(version=scope["version"], language=scope["language"])
    by_rendition = {}
    for p in plays:
        has_direct = any(
            golds[pid].evidence == "direct" and golds[pid].known
            and data.plays[pid].scene == p.scene
            for pid in data.rendition_plays[p.rendition]
        )
        if has_direct:
            continue
        by_rendition.setdefault((p.rendition, p.scene), []).append(p)
    candidates = []
    for (rendition, scene), group in sorted(by_rendition.items()):
        # 同一译文同场景选一段代表：优先非关键提示(不占关键资格班位)
        group.sort(key=lambda p: (p.key_instruction, p.day, p.play))
        chosen = group[0]
        candidates.append({
            "play": chosen.play,
            "rendition": rendition,
            "scene": scene,
            "journey": chosen.journey,
            "language": chosen.language,
            "version": chosen.version,
            "key_instruction": chosen.key_instruction,
            "also_covers": [p.play for p in group[1:]],
            "gate_critical": chosen.play in pending_plays
                             or any(p.play in pending_plays for p in group[1:]),
            "clue": data.draws[chosen.play].path == PATH_CLUE
                    or chosen.play in data.feedback_by_play,
            "probability": 1.0,  # 候选少，按普查登记，人人有参与机会
        })
    # 决策关键的排前：能解除闸口限制的优先，其次带旅客线索的
    candidates.sort(key=lambda c: (not c["gate_critical"], not c["clue"], c["play"]))
    return candidates


def adjudication_items(data: Data, golds, gates) -> list[dict]:
    """需要班位再核实的初审分歧。考核层优先。"""
    gated = {(g["scene"], g["language"]) for g in gates}
    items = []
    for pid, gold in golds.items():
        if gold.state != "分歧未裁定":
            continue
        p = data.plays[pid]
        items.append({
            "play": pid,
            "kind": "分歧裁定",
            "language": p.language,
            "key_instruction": p.key_instruction,
            "gated": (p.scene, p.language) in gated,
            "version": p.version,
            "scene": p.scene,
        })
    items.sort(key=lambda it: (not it["gated"], it["play"]))
    return items


def schedule(data: Data, items: list[dict], dispatched: list[dict] | None = None):
    """把工作项排进班位。

    items: 需含 play/language/key_instruction；可选 priority(小者优先)。
    dispatched: 已发给某席位待确认的复核 [{reviewer, day, capacity}]，
    仍占班位。
    返回 (assignments, unscheduled)。
    """
    source_langs = {pol.source_lang for pol in data.policy}
    slots = sorted(data.slots, key=lambda s: (s.day, s.slot))
    remaining = {(s.slot, s.day): s.capacity for s in slots}
    for d in dispatched or []:
        key = (d["slot"], d["day"]) if "slot" in d else None
        if key is None:
            for s in slots:
                if s.reviewer == d["reviewer"] and s.day == d["day"]:
                    key = (s.slot, s.day)
                    break
        if key and key in remaining:
            remaining[key] = max(0, remaining[key] - int(d.get("capacity", 1)))

    def fits(slot, item):
        need_langs = {item["language"]} | source_langs
        if not need_langs.issubset(set(slot.languages)):
            return False
        if item["key_instruction"] and not slot.critical:
            return False
        return True

    assignments = []
    unscheduled = []
    ordered = sorted(items, key=lambda it: (it.get("priority", 0), it["play"]))
    for item in ordered:
        placed = None
        for s in slots:
            if remaining[(s.slot, s.day)] <= 0:
                continue
            if not fits(s, item):
                continue
            placed = s
            break
        if placed is None:
            unscheduled.append(item)
        else:
            remaining[(placed.slot, placed.day)] -= 1
            assignments.append({
                "play": item["play"],
                "kind": item.get("kind", "复核"),
                "slot": placed.slot,
                "reviewer": placed.reviewer,
                "day": placed.day,
            })
    return assignments, unscheduled
