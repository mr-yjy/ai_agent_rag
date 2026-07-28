import json
import unittest
from dataclasses import replace

from scholarpilot.calibration_metrics import (
    CalibrationObservation,
    abstain_precision,
    brier_score,
    expected_calibration_error,
    intervention_flip_rate,
    retry_recovery_rate,
    selective_accuracy_coverage_auc,
)
from scholarpilot.causal_trust import (
    AgentCandidate,
    CausalTrust,
    EvidenceItem,
    calculate_cci,
    canonicalize_value,
    canonicalize_candidates,
    reliability_policy,
)
from scholarpilot.config import CausalTrustConfig


class Response:
    def __init__(self, payload):
        self.content = json.dumps(payload, ensure_ascii=False)


class ScriptedLLM:
    class Config:
        api_key = "test-key"

    config = Config()

    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = 0

    def chat(self, messages, **overrides):
        del messages, overrides
        self.calls += 1
        if not self.payloads:
            raise AssertionError("Unexpected LLM call")
        return Response(self.payloads.pop(0))


def candidate(value, intervention):
    return {
        "result": {
            "type": "research_conclusion",
            "value": value,
        },
        "evidence_ids": ["d1"],
        "response": value,
    }


def panel(a0, b0=None, a1=None, b1=None, a2=None, b2=None):
    def entries(a, b):
        values = [{"candidate_id": "c0", "support": a}]
        if b is not None:
            values.append({"candidate_id": "c1", "support": b})
        return values

    return {
        "perspectives": {
            "baseline": entries(a0, b0),
            "evidence_quality": entries(
                a1 if a1 is not None else a0,
                b1 if b1 is not None else b0,
            ),
            "reasoning_reliability": entries(
                a2 if a2 is not None else a0,
                b2 if b2 is not None else b0,
            ),
        }
    }


class CausalTrustUnitTest(unittest.TestCase):
    def setUp(self):
        self.evidence = [
            EvidenceItem(
                id=f"d{index}",
                title=f"Paper {index}",
                content="Direct supporting evidence.",
            )
            for index in range(1, 4)
        ]

    def test_candidate_canonicalization_merges_surface_variants(self):
        outputs = [
            AgentCandidate(
                "baseline",
                "entity",
                "GPT-4",
                "GPT-4",
                ["d1"],
            ),
            AgentCandidate(
                "evidence_quality",
                "entity",
                " gpt 4. ",
                "gpt 4",
                ["d2"],
            ),
        ]
        merged = canonicalize_candidates(outputs)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].evidence_ids, ["d1", "d2"])
        self.assertNotEqual(canonicalize_value("1.0"), canonicalize_value("10"))

    def test_cci_uses_mean_and_cross_intervention_range(self):
        scores = calculate_cci(
            {
                "baseline": {"A": 0.82},
                "evidence_quality": {"A": 0.78},
                "reasoning_reliability": {"A": 0.80},
            }
        )
        self.assertAlmostEqual(scores["A"].ce, 0.8)
        self.assertAlmostEqual(scores["A"].ce_var, 0.04)
        self.assertAlmostEqual(scores["A"].cci, 0.768)

    def test_complete_controller_accepts_stable_answer(self):
        llm = ScriptedLLM(
            [
                candidate("当前证据支持有限条件下的方法优势。", "baseline"),
                candidate(
                    "当前证据支持有限条件下的方法优势。",
                    "evidence_quality",
                ),
                candidate(
                    "当前证据支持有限条件下的方法优势。",
                    "reasoning_reliability",
                ),
                panel(90),
            ]
        )
        result = CausalTrust(llm).run(
            query="根据论文判断方法是否具有普遍优势",
            evidence=self.evidence,
            query_id="q-1",
        )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["decision"], "ACCEPT")
        self.assertEqual(result["confidence"], 0.9)
        self.assertEqual(llm.calls, 4)
        self.assertEqual(len(result["trace"]["passes"]), 1)

    def test_evidence_risk_triggers_one_retrieval_recovery(self):
        first_pass = [
            candidate("结论 A", "baseline"),
            candidate("结论 B", "evidence_quality"),
            candidate("结论 A", "reasoning_reliability"),
            panel(85, 15, 55, 45, 82, 18),
        ]
        recovered_pass = [
            candidate("结论 A", "baseline"),
            candidate("结论 A", "evidence_quality"),
            candidate("结论 A", "reasoning_reliability"),
            panel(95),
        ]
        llm = ScriptedLLM([*first_pass, *recovered_pass])
        recoveries = []

        def recover(mode):
            recoveries.append(mode)
            return self.evidence

        result = CausalTrust(llm).run(
            query="比较两个研究结论",
            evidence=self.evidence,
            recovery=recover,
        )
        self.assertEqual(recoveries, ["RETRY_RETRIEVAL"])
        self.assertEqual(result["decision"], "ACCEPT")
        self.assertTrue(result["recovery"]["recovered"])
        self.assertEqual(len(result["trace"]["passes"]), 2)

    def test_policy_abstains_below_retry_threshold(self):
        config = replace(
            CausalTrustConfig(),
            retry_threshold=0.5,
        )
        scores = calculate_cci(
            {
                "baseline": {"A": 0.45, "B": 0.55},
                "evidence_quality": {"A": 0.95, "B": 0.05},
                "reasoning_reliability": {"A": 0.05, "B": 0.95},
            }
        )
        self.assertEqual(
            reliability_policy(scores, config).decision,
            "ABSTAIN",
        )

    def test_single_weak_candidate_does_not_normalize_to_certainty(self):
        llm = ScriptedLLM(
            [
                candidate("证据不足", "baseline"),
                candidate("证据不足", "evidence_quality"),
                candidate("证据不足", "reasoning_reliability"),
                panel(20),
            ]
        )
        result = CausalTrust(llm).run(
            query="当前证据能否支持强结论",
            evidence=self.evidence,
        )
        self.assertEqual(result["decision"], "ABSTAIN")
        self.assertEqual(result["confidence"], 0.2)


class CalibrationMetricsTest(unittest.TestCase):
    def test_calibration_metrics(self):
        observations = [
            CalibrationObservation(0.9, True, True),
            CalibrationObservation(0.8, True, True),
            CalibrationObservation(0.2, False, False),
            CalibrationObservation(0.1, False, False),
        ]
        self.assertAlmostEqual(brier_score(observations), 0.025)
        self.assertAlmostEqual(
            expected_calibration_error(observations, bins=2),
            0.15,
        )
        self.assertGreater(
            selective_accuracy_coverage_auc(observations),
            0.8,
        )
        self.assertEqual(abstain_precision(observations), 1.0)
        self.assertEqual(retry_recovery_rate([False, True], [True, True]), 1.0)
        self.assertEqual(
            intervention_flip_rate(["a", "b"], ["a", "c"]),
            0.5,
        )


if __name__ == "__main__":
    unittest.main()
