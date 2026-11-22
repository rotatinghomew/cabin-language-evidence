"""把审查状态渲染成负责人可读的 Markdown 报告。"""
from __future__ import annotations

from .model import CRITICAL_CAUSES


def pct(x):
    return "—" if x is None else f"{x:.1%}"


def _table(headers, rows):
    out = ["| " + " | ".join(headers) + " |",
           "| " + " | ".join("---" for _ in headers) + " |"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def render(state: dict) -> str:
    lines = []
    add = lines.append
    as_of = state["as_of"] or "全部可见记录"
    add("# 座舱提示改版漏标审查报告")
    add("")
    add(f"金标准可见范围：{as_of}。总体漏标率与版本比较只用盲抽样本"
        "(逆概率加权)；线索追查片段单列，不进总体率。")
    add("")

    # 1. 闸口总览
    add("## 一、关键用途闸口总览")
    add("")
    rows = []
    for g in state["gates"]:
        est, cov = g["estimate"], g["coverage"]
        rows.append([
            f"{g['scene']}-{g['language']}",
            f"{cov['journeys_reviewed']}(决{cov['journeys_resolved']})/{g['min_trips']}",
            pct(est["point"]),
            pct(est["upper"]),
            f"{g['max_miss']:.0%}",
            g["verdict"],
        ])
    add(_table(
        ["层(场景-语言)", "独立审核旅程(已决)/下限", "已确认漏标率", "悲观上限",
         "漏标上限", "判定"], rows))
    add("")
    for g in state["gates"]:
        add(f"- **{g['scene']}-{g['language']}：{g['verdict']}**。"
            + "；".join(g["reasons"]) + "。")
    add("")

    # 2. 加权错因风险
    add("## 二、加权错因风险(盲抽样本，逆概率加权)")
    add("")
    rows = []
    for g in state["gates"]:
        for c in CRITICAL_CAUSES:
            pc = g["estimate"]["per_cause"][c]
            rows.append([
                f"{g['scene']}-{g['language']}", c,
                pc["true_w"], pc["missed_w"], pc["potential_w"],
            ])
    add(_table(["层", "错因", "真错因(加权)", "已确认漏标(加权)",
                "可能漏标(加权)"], rows))
    add("")
    add("可能漏标来自初审分歧未裁定或已抽未审，不计为无漏标；"
        "它决定悲观上限能否落到上限以内。")
    add("")

    # 3. 覆盖
    add("## 三、覆盖与观察机会")
    add("")
    rows = []
    for g in state["gates"]:
        cov = g["coverage"]
        rows.append([
            f"{g['scene']}-{g['language']}", cov["journeys"], cov["blind"],
            cov["reviewed"], len(cov["disputed"]),
            len(cov["absent_covered"]), len(cov["absent_open"]),
            cov["zero_prob"],
            f"{cov['renditions_direct']}/{cov['renditions']}",
            cov["renditions_covered"],
        ])
    add(_table(["层", "旅程数", "盲抽段数", "完成复核", "分歧未裁定",
                "缺席(传递可覆盖)", "缺席(未知)", "零概率段",
                "独立审查译文/总译文", "可覆盖译文"], rows))
    add("")
    nf = state["no_feedback"]
    add(f"无留言播出共 {nf['plays']} 段：盲抽入样 {nf['blind']} 段，"
        f"完成复核 {nf['reviewed']} 段，含译文传递可覆盖 {nf['covered']} 段。"
        "投诉变少不等于问题变少——没投诉的播报靠盲抽覆盖，不靠留言统计。")
    add("")
    for g in state["gates"]:
        cov = g["coverage"]
        notes = []
        if cov["disputed"]:
            notes.append(f"分歧未裁定：{'、'.join(cov['disputed'])}")
        if cov["absent_open"]:
            notes.append(f"已抽未审(未知)：{'、'.join(cov['absent_open'])}")
        if cov["absent_covered"]:
            notes.append(
                f"已抽未审(译文传递可覆盖)：{'、'.join(cov['absent_covered'])}")
        if notes:
            add(f"- {g['scene']}-{g['language']}：" + "；".join(notes))
    add("")

    # 4. 版本比较
    add("## 四、版本比较(同一盲抽口径)")
    add("")
    rows = []
    for v, est in state["versions"].items():
        ci = "—" if est["ci"] is None else f"{est['ci'][0]:.1%}~{est['ci'][1]:.1%}"
        rows.append([v, est["sample_plays"], est["sample_journeys"],
                     pct(est["point"]), pct(est["upper"]), ci])
    add(_table(["版本", "盲抽段数", "旅程数", "已确认漏标率", "悲观上限",
                "95%置信区间(聚类)"], rows))
    add("")
    add("留言入口改版后投诉量不可比；上表三个版本用的是同一盲抽口径，"
        "才是可比的改版效果证据。置信区间按旅程聚类，旅程数少时偏窄，"
        "仅作参考。")
    add("")
    vs = state["versions"]
    ordered = [v for v in vs if vs[v]["point"] is not None]
    if len(ordered) >= 2:
        trend = "、".join(f"{v} {pct(vs[v]['point'])}" for v in ordered)
        add(f"已确认漏标率沿版本走势：{trend}。投诉量下降而盲抽漏标率未降，"
            "说明投诉变少更可能来自留言入口变化，而不是提示更清楚；"
            "遗漏的错因本来就不会出现在投诉统计里。")
    add("")

    # 5. 旅客线索与专项追查
    add("## 五、旅客线索与专项追查(不进总体率)")
    add("")
    fb = state["feedback"]
    add(f"留言共 {fb['total']} 条，其中翻译件 {fb['translations']} 条"
        f"(引用同一留言，不作独立观测)，独立留言 {fb['original']} 条。")
    add("")
    rows = []
    for it in state["clue_items"]:
        gold_txt = "、".join(
            f"{k}{'有' if v else '无'}" for k, v in it["gold_causes"].items()
        ) or "—"
        rows.append([
            it["play"], it["version"], f"{it['scene']}-{it['language']}",
            "、".join(it["first_labels"]), it["gold_state"], gold_txt,
        ])
    add(_table(["播出", "版本", "层", "初分错因", "复核状态",
                "已知金标准"], rows))
    add("")

    # 6. 复用、传播与停用
    add("## 六、译文复用、更正传播与旧提示停用")
    add("")
    if state["ledger"]["propagation"]:
        rows = []
        for p in state["ledger"]["propagation"]:
            rows.append([p["rendition"],
                         "、".join(p["intrinsic"]) or "—",
                         "、".join(p["route"]) or "—",
                         "、".join(p["versions"]), "、".join(p["uses"])])
        add("共用译文上的已确认关键错因：译文固有错因的更正传播到实际共用它的"
            "版本；线路不适用是旅程级发现，提示同译文其他使用处自查：")
        add("")
        add(_table(["译文", "固有错因(传播更正)", "线路不适用(旅程级自查)",
                    "涉及版本", "实际使用播出"], rows))
    else:
        add("共用译文上没有已确认关键错因。")
    add("")
    if state["ledger"]["retired"]:
        rows = []
        for r in state["ledger"]["retired"]:
            rows.append([r["rendition"], f"{r['content']}({r['scene']}-{r['language']})",
                         r["last_version"], r["retired_in"]])
        add("已停止使用的旧提示：")
        add("")
        add(_table(["译文", "用途", "最后使用版本", "停用起始版本"], rows))
    add("")

    # 7. 补抽建议与班位
    add("## 七、补抽建议与班位安排")
    add("")
    supp = state["supplementary"]
    rec = supp["recommendation"]
    if rec.get("scope"):
        sc = rec["scope"]
        add(f"建议补抽范围：**{sc['language']} × {sc['version']}**"
            f"(负责人一次只能申请一个语言×版本范围)。")
        add(f"它能回答的问题：{rec['question']}。")
        if rec.get("caveat"):
            add(f"⚠ {rec['caveat']}。")
        elif rec.get("residual_upper") is not None:
            add(f"该范围待补证据全部有利化解后的残余悲观上限约 "
                f"{rec['residual_upper']:.1%}。")
    else:
        add(f"本轮不建议补抽：{rec.get('reason', '')}")
    for note in rec.get("blocked_notes", []):
        add(f"- {note}")
    add("")
    if supp.get("special"):
        rows = []
        for s in supp["special"]:
            rows.append([s["play"], s["version"], s["gate"],
                         "、".join(s["unknown_causes"])])
        add("范围外的待补证据(补抽覆盖不到，需专项追查；"
            "线路不适用随旅程变化，不能靠共用译文的复核代替)：")
        add("")
        add(_table(["播出", "版本", "影响闸口", "未确认错因"], rows))
        add("")
    if supp["candidates"]:
        rows = []
        for c in supp["candidates"]:
            rows.append([
                c["play"], c["rendition"], c["scene"],
                "是" if c["key_instruction"] else "否",
                "是" if c["gate_critical"] else "否",
                "、".join(c["also_covers"]) or "—",
            ])
        add("候选(范围内译文尚无直接复核的播出，按译文去重，"
            "每段都先登记参与机会)：")
        add("")
        add(_table(["播出", "译文", "场景", "关键提示", "决策关键",
                    "同译文顺带覆盖"], rows))
        add("")
        add("后续若复核缺席，该段仍计入覆盖并留在不确定性里，"
            "不按无漏标计。")
        add("")
    if supp["assignments"]:
        rows = []
        for a in supp["assignments"]:
            rows.append([a["day"], a["slot"], a["reviewer"], a["play"], a["kind"]])
        add("班位安排(关键提示只占关键资格席位；已发出待确认的复核仍占班位)：")
        add("")
        add(_table(["日期", "班位", "复核席", "播出", "类型"], rows))
        add("")
        usage = "；".join(
            f"{u['reviewer']} {u['used']}/{u['capacity']}"
            for u in supp.get("slot_usage", []))
        add(f"班位用量：{usage}。本轮登记资料中没有已发出待确认的复核；"
            "若存在，须先从相应席位扣除再排。未排入的工作见下表，"
            "不是被挤掉就是现有席位资格不够。")
        add("")
    if supp["unscheduled"]:
        rows = []
        for u in supp["unscheduled"]:
            rows.append([u["play"], u.get("kind", "复核"), u["language"],
                         "是" if u["key_instruction"] else "否"])
        add("现有班位排不下的工作(需增设具备相应语言与关键资格的席位)：")
        add("")
        add(_table(["播出", "类型", "语言", "关键提示"], rows))
        add("")

    # 8. 放行记录
    add("## 八、放行记录(当时批准了什么、还缺什么)")
    add("")
    verdicts = [g["verdict"] for g in state["gates"]]
    fb_status = [f["status"] for f in state["ledger"]["fallbacks"]]
    if "通过" not in verdicts:
        fb_summary = "、".join(
            f"{s}×{fb_status.count(s)}" for s in dict.fromkeys(fb_status))
        add("**本轮未批准任何版本或条目**：五个关键用途层无一达到可放行"
            f"条件({'、'.join(f'{v}×{verdicts.count(v)}' for v in dict.fromkeys(verdicts))})；"
            f"可单独批准的部分也不存在——替代提示核实结果：{fb_summary}。")
    missing = []
    for g in state["gates"]:
        for item in g["pending"]:
            missing.append(f"{item['play']}({g['scene']}-{g['language']})")
    if missing:
        add(f"还缺的证据：{'、'.join(missing)}；"
            "晚线-英语、晚线-法语为结构性缺口(旅程数低于下限)，"
            "靠后续版本积累旅程，不靠补抽。")
    add("旧提示停用清单见第六节。")
    add("")
    ov = state["ledger"]["overrides"]
    rows = []
    for e in ov["planned"]:
        rows.append([
            f"{e['content']}({e['scene']}-{e['language']}-{e['version']})",
            e["gate_verdict"] or "无闸口",
            "、".join(h["rendition"] + ":" + "/".join(h["causes"])
                      for h in e["confirmed_hits"]) or "—",
        ])
    add("拟发布条目：")
    add("")
    add(_table(["条目", "所在层判定", "互认内容已确认错因"], rows))
    add("")
    rows = []
    for e in ov["in_use"]:
        rows.append([
            f"{e['content']}({e['scene']}-{e['language']}-{e['version']})",
            e["gate_verdict"] or "无闸口",
            "建议收窄" if e["narrow"] else "维持",
            "、".join(h["rendition"] + ":" + "/".join(h["causes"])
                      for h in e["confirmed_hits"]) or "—",
        ])
    add("在用条目：")
    add("")
    add(_table(["条目", "所在层判定", "处置", "互认内容已确认错因"], rows))
    add("")
    rows = []
    for f in state["ledger"]["fallbacks"]:
        rows.append([f"{f['scene']}-{f['language']}", f["fallback"] or "无",
                     f["status"]])
    add("替代提示核实(按场景和语言核实，符合关键指引要求才可用)：")
    add("")
    add(_table(["层", "替代提示", "核实结论"], rows))
    add("")

    # 9. 重算指引
    add("## 九、新证据到达后的重算指引")
    add("")
    add("- 新的盲审裁定只更新金标准，不回写抽核前的初分基准；"
        "用 `--as-of` 可还原当时可见的裁定。")
    add("- 重跑 `python3 -m cabin_review run` 后，"
        "用 `python3 -m cabin_review diff 旧状态.json 新状态.json` "
        "查看：总体判断哪些要重算、在用版本哪些要收窄、"
        "本轮已启动的补抽是否还能回答原问题。")
    add("")
    return "\n".join(lines)
