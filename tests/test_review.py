"""漏标审查管线的单元测试与基于交接资料的集成测试。"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from cabin_review.model import CRITICAL_CAUSES, Data
from cabin_review.review import (
    ST_CAUGHT,
    ST_CLEAR,
    ST_MISSED,
    ST_POTENTIAL,
    ST_UNVERIFIED,
    direct_gold,
    miss_status,
    resolve_all,
)
from cabin_review.estimate import coverage, estimate
from cabin_review.gates import evaluate_all
from cabin_review.plan import (
    adjudication_items,
    draw_candidates,
    recommend_scope,
    schedule,
)
from cabin_review.state import build_state, diff_states

DATA = Path(__file__).resolve().parents[1] / "data"


def load_data():
    return Data(DATA)


class GoldResolutionTest(unittest.TestCase):
    def setUp(self):
        self.data = load_data()

    def test_adjudication_wins_over_disagreement(self):
        # P00-0 初审分歧(语义反转 vs 播放不清)，裁定语义反转
        gold = direct_gold(self.data, "P00-0")
        self.assertEqual(gold.state, "裁定")
        self.assertEqual(gold.causes["语义反转"], True)
        self.assertEqual(gold.causes["播放不清"], False)

    def test_as_of_hides_later_adjudication(self):
        # 裁定 2026-06-07 才可见；此前只能看到分歧
        gold = direct_gold(self.data, "P00-0", as_of="2026-06-06")
        self.assertEqual(gold.state, "分歧未裁定")
        self.assertIsNone(gold.causes["语义反转"])
        gold = direct_gold(self.data, "P00-0", as_of="2026-06-07")
        self.assertEqual(gold.state, "裁定")

    def test_agreed_first_pass(self):
        gold = direct_gold(self.data, "P01-0")
        self.assertEqual(gold.state, "一致")
        self.assertEqual(gold.causes["播放不清"], True)
        self.assertEqual(gold.causes["语义反转"], False)

    def test_dispute_stays_unknown_not_no_miss(self):
        gold = direct_gold(self.data, "P66-1")
        self.assertEqual(gold.state, "分歧未裁定")
        self.assertIsNone(gold.causes["语义反转"])
        self.assertIsNone(gold.causes["播放不清"])
        # 两人都未提的错因视为已确认无
        self.assertEqual(gold.causes["线路不适用"], False)

    def test_absent_and_not_selected(self):
        self.assertEqual(direct_gold(self.data, "P44-0").state, "已抽未审")
        self.assertEqual(direct_gold(self.data, "P68-0").state, "未入样")


class TransferTest(unittest.TestCase):
    def setUp(self):
        self.data = load_data()
        self.golds, self.statuses = resolve_all(self.data)

    def test_shared_rendition_transfers_intrinsic_causes(self):
        # P00-1 裁定确认 X01-英语-共用 有播放不清+语义反转；
        # 同译文同场景的 P24-1(缺席) 获得传递证据
        gold = self.golds["P24-1"]
        self.assertEqual(gold.evidence, "transferred")
        self.assertEqual(gold.causes["语义反转"], True)
        self.assertEqual(gold.causes["播放不清"], True)
        # 线路不适用随应用条件变化，不传递
        self.assertIsNone(gold.causes["线路不适用"])

    def test_cross_scene_does_not_transfer(self):
        # X01-英语-声一 只在晚线(P13-0)复核过，日游的 P12-1 不能借用
        gold = self.golds["P12-1"]
        self.assertEqual(gold.evidence, "none")
        self.assertFalse(gold.known)

    def test_route_cause_never_transfers(self):
        # P32-0 确认 X08-普通话-共用 语义反转；P08-0 同译文同场景
        gold = self.golds["P08-0"]
        self.assertEqual(gold.causes["语义反转"], True)
        self.assertIsNone(gold.causes["线路不适用"])

    def test_no_double_independent_review(self):
        # 同一译文在多个旅程被抽中，独立审查译文数只算一次
        cov = coverage("免下车", "普通话", self.data, self.golds)
        # X11-普通话-声一 在 P11-0/P23-0 都完成复核，译文只计一次
        self.assertEqual(cov["reviewed"], 16)
        self.assertEqual(cov["renditions_direct"], 12)


class MissStatusTest(unittest.TestCase):
    def test_all_branches(self):
        gold_true = {"语义反转": True, "播放不清": False, "线路不适用": None}

        class G:
            causes = gold_true

        st = miss_status(("播放不清",), G())
        self.assertEqual(st["语义反转"], ST_MISSED)      # 有而未标
        self.assertEqual(st["播放不清"], ST_OVER if False else "over_claimed")
        self.assertEqual(st["线路不适用"], ST_POTENTIAL)  # 未知且未标
        st = miss_status(("语义反转", "线路不适用"), G())
        self.assertEqual(st["语义反转"], ST_CAUGHT)
        self.assertEqual(st["线路不适用"], ST_UNVERIFIED)  # 未知但已标
        st = miss_status((), G())
        self.assertEqual(st["播放不清"], ST_CLEAR)


class EstimateTest(unittest.TestCase):
    def setUp(self):
        self.data = load_data()
        self.golds, self.statuses = resolve_all(self.data)

    def test_clue_path_excluded_from_rate(self):
        # 线索追查片段不进总体率样本
        plays = self.data.plays_in(scene="免下车", language="普通话")
        est = estimate("t", plays, self.data, self.golds, self.statuses)
        clue = {p.play for p in plays
                if self.data.draws[p.play].path == "线索追查"}
        self.assertEqual(clue, {"P20-0", "P56-0"})
        self.assertEqual(est.sample_plays, 18)  # 只含盲抽

    def test_inverse_probability_weights(self):
        plays = self.data.plays_in(scene="免下车", language="普通话")
        est = estimate("t", plays, self.data, self.golds, self.statuses)
        # 声一 1/0.72、声二 1/0.61、声三 1/0.75
        self.assertAlmostEqual(est.per_cause["语义反转"]["true_w"],
                               4 / 0.72 + 1 / 0.61, places=3)

    def test_unconfirmed_not_counted_as_no_miss(self):
        # 免下车-普通话：已确认漏标为 0，但 P44-0 未知使悲观上限 > 0
        plays = self.data.plays_in(scene="免下车", language="普通话")
        est = estimate("t", plays, self.data, self.golds, self.statuses)
        self.assertEqual(est.missed_w, 0.0)
        self.assertGreater(est.upper, 0.1)
        self.assertGreater(est.potential_w, 0.0)

    def test_cluster_se_present(self):
        plays = self.data.plays_in(scene="日游", language="英语")
        est = estimate("t", plays, self.data, self.golds, self.statuses)
        self.assertIsNotNone(est.se)
        lo, hi = est.ci
        self.assertLessEqual(lo, est.point)
        self.assertGreaterEqual(hi, est.point)


class GateTest(unittest.TestCase):
    def setUp(self):
        self.data = load_data()
        self.golds, self.statuses = resolve_all(self.data)
        self.gates, *_ = evaluate_all(self.data, self.golds, self.statuses)
        self.by_key = {(g["scene"], g["language"]): g for g in self.gates}

    def test_verdicts(self):
        self.assertEqual(self.by_key[("日游", "英语")]["verdict"], "不通过")
        self.assertEqual(self.by_key[("晚线", "英语")]["verdict"], "阻断")
        self.assertEqual(self.by_key[("免下车", "普通话")]["verdict"], "待补证")
        self.assertEqual(self.by_key[("晚线", "法语")]["verdict"], "阻断")
        self.assertEqual(self.by_key[("日游", "粤语")]["verdict"], "不通过")

    def test_zero_probability_stratum_flagged(self):
        gate = self.by_key[("晚线", "法语")]
        self.assertEqual(gate["coverage"]["zero_prob"], 2)
        self.assertTrue(any("没有观察机会" in r for r in gate["reasons"]))

    def test_pending_lists_only_blind_sample(self):
        gate = self.by_key[("免下车", "普通话")]
        plays = {p["play"] for p in gate["pending"]}
        self.assertEqual(plays, {"P08-0", "P44-0"})
        for p in gate["pending"]:
            self.assertEqual(self.data.draws[p["play"]].path, "盲抽")


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.data = load_data()
        self.golds, self.statuses = resolve_all(self.data)
        self.gates, *_ = evaluate_all(self.data, self.golds, self.statuses)

    def test_scope_targets_restriction_lifting_evidence(self):
        rec = recommend_scope(self.data, self.gates, self.statuses)
        self.assertEqual(rec["scope"], {"language": "普通话", "version": "声二"})
        self.assertIn("P44-0", rec["pending_plays"])
        # 单靠该范围仍不能把残余压到上限内，须明说
        self.assertFalse(rec["lifts"])
        self.assertIn("专项追查", rec["caveat"])

    def test_blocked_strata_not_recommended(self):
        rec = recommend_scope(self.data, self.gates, self.statuses)
        notes = " ".join(rec["blocked_notes"])
        self.assertIn("晚线-英语", notes)
        self.assertIn("补抽无法解除", notes)

    def test_candidates_dedupe_rendition_and_prefer_non_critical(self):
        rec = recommend_scope(self.data, self.gates, self.statuses)
        cands = draw_candidates(self.data, rec["scope"], self.golds,
                                self.statuses,
                                pending_plays=frozenset(rec["pending_plays"]))
        by_rend = {c["rendition"]: c for c in cands}
        # X04-普通话-共用 两段选一段，优先不占关键资格的 P40-0
        self.assertEqual(by_rend[("X04-普通话-共用")]["play"], "P40-0")
        self.assertEqual(by_rend[("X04-普通话-共用")]["also_covers"], ["P64-0"])
        # 决策关键的 P44-0 排最前
        self.assertEqual(cands[0]["play"], "P44-0")
        self.assertTrue(cands[0]["gate_critical"])
        # 每个候选都登记了参与机会
        self.assertTrue(all(c["probability"] > 0 for c in cands))

    def test_scheduler_respects_qualifications(self):
        items = [
            {"play": "A", "language": "英语", "key_instruction": True},
            {"play": "B", "language": "粤语", "key_instruction": True},
            {"play": "C", "language": "普通话", "key_instruction": False},
        ]
        assignments, unscheduled = schedule(self.data, items)
        by_play = {a["play"]: a for a in assignments}
        # 英语关键提示只能给双语甲(关键资格+双语)
        self.assertEqual(by_play["A"]["reviewer"], "双语甲")
        # 粤语关键提示：普通话乙无关键资格，双语甲不会粤语 → 排不下
        self.assertEqual([u["play"] for u in unscheduled], ["B"])
        # 普通话非关键：两个席位都可，按日序先排双语甲
        self.assertEqual(by_play["C"]["reviewer"], "双语甲")

    def test_dispatched_review_still_occupies_slot(self):
        items = [{"play": f"X{i}", "language": "英语",
                  "key_instruction": True} for i in range(3)]
        dispatched = [{"reviewer": "双语甲", "day": "2026-08-09", "capacity": 2}]
        assignments, _ = schedule(self.data, items, dispatched)
        days = [a["day"] for a in assignments]
        # 2026-08-09 双语甲的 2 个名额被已发出的复核占掉，只能往后排
        self.assertNotIn("2026-08-09", days)

    def test_adjudication_items_gated_first(self):
        items = adjudication_items(self.data, self.golds, self.gates)
        gated = [it for it in items if it["gated"]]
        self.assertTrue(all(it["gated"] for it in items[:len(gated)]))
        self.assertEqual(len(items), 12)  # 全部初审分歧


class StateDiffTest(unittest.TestCase):
    def setUp(self):
        self.data = load_data()

    def _with_new_labels(self, extra):
        tmp = Path(tempfile.mkdtemp())
        for f in DATA.glob("*.json"):
            shutil.copy(f, tmp / f.name)
        labels = json.loads((tmp / "labels.json").read_text(encoding="utf-8"))
        labels.extend(extra)
        (tmp / "labels.json").write_text(
            json.dumps(labels, ensure_ascii=False), encoding="utf-8")
        return tmp

    def test_new_adjudication_triggers_recompute(self):
        old = build_state(self.data)
        # 新裁定：P66-1 确认语义反转(声三 日游-英语)
        tmp = self._with_new_labels([{
            "play": "P66-1", "reviewer": "裁定席",
            "labels": ["语义反转"], "date": "2026-08-20", "kind": "裁定",
        }])
        new = build_state(Data(tmp))
        shutil.rmtree(tmp)
        diff = diff_states(old, new)
        gates_changed = {r["gate"] for r in diff["recompute"]}
        self.assertIn(("日游", "英语"), gates_changed)
        # 初分基准未被篡改：P66-1 的初分仍是语义反转
        self.assertEqual(self.data.firsts["P66-1"], ("语义反转",))

    def test_supplementary_validity_tracked(self):
        old = build_state(self.data)
        # P44-0 复核完成且全部正常 → 免下车-普通话 的不确定性大头消除
        tmp = self._with_new_labels([
            {"play": "P44-0", "reviewer": "席甲", "labels": ["正常建议"],
             "date": "2026-08-20", "kind": "初审"},
            {"play": "P44-0", "reviewer": "席乙", "labels": ["正常建议"],
             "date": "2026-08-20", "kind": "初审"},
        ])
        new = build_state(Data(tmp))
        shutil.rmtree(tmp)
        diff = diff_states(old, new)
        self.assertEqual(diff["supplementary"]["scope"],
                         {"language": "普通话", "version": "声二"})
        # 原问题已部分回答：状态字段存在且给出说明
        self.assertIn(diff["supplementary"]["status"], ("仍然有效", "问题已变化"))

    def test_first_labels_baseline_immutable(self):
        # 新裁定只更新金标准，不回写初分基准
        tmp = self._with_new_labels([{
            "play": "P66-0", "reviewer": "裁定席",
            "labels": ["语义反转"], "date": "2026-08-20", "kind": "裁定",
        }])
        new_data = Data(tmp)
        self.assertEqual(new_data.firsts["P66-0"], ("正常建议",))
        golds, _ = resolve_all(new_data)
        self.assertEqual(golds["P66-0"].causes["语义反转"], True)
        shutil.rmtree(tmp)


class IntegrationTest(unittest.TestCase):
    """基于交接资料的端到端口径核对。"""

    @classmethod
    def setUpClass(cls):
        cls.state = build_state(load_data())

    def test_gate_numbers(self):
        gates = {(g["scene"], g["language"]): g for g in self.state["gates"]}
        g = gates[("免下车", "普通话")]
        self.assertEqual(g["coverage"]["journeys_reviewed"], 16)
        self.assertAlmostEqual(g["estimate"]["upper"], 0.2119, places=3)
        g = gates[("日游", "英语")]
        self.assertEqual(g["coverage"]["journeys_reviewed"], 14)
        self.assertAlmostEqual(g["estimate"]["point"], 0.3368, places=3)

    def test_unschedulable_cantonese_critical(self):
        unscheduled = {u["play"] for u in self.state["supplementary"]["unscheduled"]}
        self.assertEqual(unscheduled, {"P18-0", "P54-0"})

    def test_feedback_translations_collapsed(self):
        fb = self.state["feedback"]
        self.assertEqual((fb["total"], fb["original"], fb["translations"]),
                         (72, 60, 12))

    def test_no_feedback_coverage_reported(self):
        nf = self.state["no_feedback"]
        self.assertEqual(nf["plays"], 64)
        self.assertGreaterEqual(nf["covered"], nf["reviewed"])

    def test_propagation_lists_shared_renditions(self):
        props = {p["rendition"]: p for p in self.state["ledger"]["propagation"]}
        self.assertIn("X01-英语-共用", props)
        self.assertEqual(props["X01-英语-共用"]["versions"],
                         ["声一", "声二", "声三"])

    def test_slot_usage_within_capacity(self):
        for u in self.state["supplementary"]["slot_usage"]:
            self.assertLessEqual(u["used"], u["capacity"])


if __name__ == "__main__":
    unittest.main()
