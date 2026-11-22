"""版本适用证据：替代提示核实、在用收窄、更正传播与旧提示停用。"""
from __future__ import annotations

from .model import CRITICAL_CAUSES, ROUTE_CAUSE, Data
from .review import ST_MISSED


def confirmed_causes_on(data: Data, golds, contents, scene, language) -> list[dict]:
    """指定内容集合在指定场景-语言下，金标准已确认的关键错因。"""
    found = []
    for p in data.plays_in(scene=scene, language=language):
        if p.content not in contents:
            continue
        g = golds[p.play]
        if not g.known:
            continue
        causes = [c for c in CRITICAL_CAUSES if g.causes[c] is True]
        if causes:
            found.append({
                "play": p.play, "content": p.content, "version": p.version,
                "rendition": p.rendition, "causes": causes,
                "evidence": g.evidence,
            })
    return found


def fallback_status(data: Data, golds, scene, language, fallback) -> dict:
    """核实替代提示在该场景-语言下是否可用。"""
    if fallback is None:
        return {"fallback": None, "status": "无替代提示"}
    hits = confirmed_causes_on(data, golds, {fallback}, scene, language)
    if hits:
        return {"fallback": fallback, "status": "未通过核实",
                "detail": f"{fallback} 在{scene}-{language}有已确认关键错因",
                "hits": hits}
    has_evidence = any(
        golds[p.play].known
        for p in data.plays_in(scene=scene, language=language)
        if p.content == fallback
    )
    if not has_evidence:
        return {"fallback": fallback, "status": "无核实证据",
                "detail": f"{fallback} 在{scene}-{language}没有复核证据"}
    return {"fallback": fallback, "status": "可用",
            "detail": f"{fallback} 在{scene}-{language}未见已确认关键错因"}


def override_review(data: Data, golds, gates) -> dict:
    """拟发布与在用条目的放行/收窄评估。"""
    gate_by_key = {(g["scene"], g["language"]): g for g in gates}
    planned, in_use = [], []
    for ov in data.overrides:
        gate = gate_by_key.get((ov.scene, ov.language))
        hits = confirmed_causes_on(data, golds, set(ov.equivalent),
                                   ov.scene, ov.language)
        entry = {
            "content": ov.content, "scene": ov.scene, "language": ov.language,
            "version": ov.version, "state": ov.state,
            "gate_verdict": None if gate is None else gate["verdict"],
            "confirmed_hits": hits,
        }
        if ov.state == "拟发布":
            planned.append(entry)
        else:
            # 在用：互认内容在该场景-语言有已确认关键错因 → 建议收窄
            entry["narrow"] = bool(hits) or (
                gate is not None and gate["verdict"] in ("不通过", "阻断"))
            in_use.append(entry)
    return {"planned": planned, "in_use": in_use}


def propagation(data: Data, golds) -> list[dict]:
    """共用译文上的已确认关键错因 → 需要同步更正的版本/场景。

    译文固有错因(语义反转、播放不清)随译文传播更正；线路不适用是
    旅程级发现，只提示同译文其他使用处自查，不当作译文缺陷传播。
    """
    out = []
    version_order = {v: i for i, v in enumerate(data.versions)}
    for rendition, play_ids in sorted(data.rendition_plays.items()):
        plays = [data.plays[pid] for pid in play_ids]
        versions = sorted({p.version for p in plays},
                          key=lambda v: version_order[v])
        if len(versions) < 2:
            continue
        intrinsic, route = set(), set()
        evidence_from = []
        for p in plays:
            g = golds[p.play]
            if g.evidence == "direct" and g.known:
                for c in CRITICAL_CAUSES:
                    if g.causes[c] is True:
                        (route if c == ROUTE_CAUSE else intrinsic).add(c)
                        evidence_from.append(p.play)
        if intrinsic or route:
            out.append({
                "rendition": rendition,
                "causes": sorted(intrinsic | route),
                "intrinsic": sorted(intrinsic),
                "route": sorted(route),
                "versions": versions,
                "scenes": sorted({p.scene for p in plays}),
                "evidence_from": sorted(set(evidence_from)),
                "uses": sorted(play_ids),
            })
    return out


def retired_renditions(data: Data) -> list[dict]:
    """同一(内容,场景,语言)下，被后续版本替换而停止使用的旧译文。"""
    by_key = {}
    for p in data.plays.values():
        by_key.setdefault((p.content, p.scene, p.language), {}) \
              .setdefault(p.version, set()).add(p.rendition)
    order = {v: i for i, v in enumerate(data.versions)}  # 已按首播日排序
    retired = []
    for (content, scene, language), versions in sorted(by_key.items()):
        if len(versions) < 2:
            continue
        for v in sorted(versions, key=order.get):
            later = [u for u in versions if order[u] > order[v]]
            if not later:
                continue
            later_renditions = set().union(*(versions[u] for u in later))
            for r in sorted(versions[v] - later_renditions):
                retired.append({
                    "content": content, "scene": scene, "language": language,
                    "retired_in": min(later, key=order.get),
                    "rendition": r, "last_version": v,
                })
    return retired
