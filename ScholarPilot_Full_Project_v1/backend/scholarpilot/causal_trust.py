"""Trust-aware answer calibration for evidence-backed research agents.

This module implements the engineering core described in ``when to trust``:
controlled evidence/reasoning interventions, candidate canonicalization,
intervention-specific panel scoring, deterministic CCI calculation, a
reliability gate, diagnosis, one bounded recovery, and an auditable trace.

It is intentionally independent from paper retrieval and ranking.  A caller
supplies evidence and may optionally supply a recovery callback.  Failures in
this optional layer are represented as a result rather than allowed to break
the underlying search request.
"""

from __future__ import annotations

import json
import math
import re
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Protocol

from .config import CausalTrustConfig, get_config
from .llm_client import LLMError


Intervention = Literal[
    "baseline",
    "evidence_quality",
    "reasoning_reliability",
]
Decision = Literal[
    "ACCEPT",
    "RETRY_RETRIEVAL",
    "RETRY_REASONING",
    "ABSTAIN",
    "NOT_RUN",
]
RecoveryCallback = Callable[[str], list["EvidenceItem"]]


class ChatClient(Protocol):
    config: Any

    def chat(
        self,
        messages: list[dict[str, str]],
        **overrides: Any,
    ) -> Any: ...


@dataclass(slots=True, frozen=True)
class EvidenceItem:
    id: str
    title: str
    content: str
    source: str = ""
    year: int | None = None

    def to_prompt(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "content": self.content,
        }
        if self.source:
            payload["source"] = self.source
        if self.year:
            payload["year"] = self.year
        return payload


@dataclass(slots=True)
class AgentCandidate:
    intervention: Intervention
    result_type: str
    value: str
    response: str
    evidence_ids: list[str]
    canonical_key: str = ""

    def to_trace(self) -> dict[str, Any]:
        return {
            "intervention": self.intervention,
            "result": {
                "type": self.result_type,
                "value": self.value,
            },
            "response": self.response,
            "evidenceIds": self.evidence_ids,
        }


@dataclass(slots=True)
class CanonicalCandidate:
    id: str
    key: str
    value: str
    response: str
    evidence_ids: list[str] = field(default_factory=list)
    produced_by: list[Intervention] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class CandidateScore:
    candidate_id: str
    ce: float
    ce_var: float
    cci: float
    intervention_scores: dict[str, float]

    def to_api(
        self,
        candidate: CanonicalCandidate,
    ) -> dict[str, Any]:
        return {
            "id": self.candidate_id,
            "value": candidate.value,
            "response": candidate.response,
            "evidenceIds": candidate.evidence_ids,
            "producedBy": candidate.produced_by,
            "meanSupport": round(self.ce, 6),
            "instability": round(self.ce_var, 6),
            "cci": round(self.cci, 6),
            "interventionScores": {
                key: round(value, 6)
                for key, value in self.intervention_scores.items()
            },
        }


@dataclass(slots=True, frozen=True)
class ReliabilityPolicyResult:
    decision: Decision
    confidence: float
    margin: float


@dataclass(slots=True)
class CalibrationPass:
    generated: dict[str, AgentCandidate]
    candidates: list[CanonicalCandidate]
    panel_scores: dict[str, dict[str, float]]
    scores: dict[str, CandidateScore]
    selected_id: str
    policy: ReliabilityPolicyResult
    evidence_risk: float
    reasoning_risk: float


def _clamp(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return max(0.0, min(1.0, value))


def canonicalize_value(value: str) -> str:
    """Normalize superficial answer variants without semantic invention."""
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    normalized = re.sub(r"https?://(?:dx\.)?doi\.org/", "", normalized)
    normalized = re.sub(r"^doi:\s*", "", normalized)
    normalized = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", normalized)
    # Preserve decimal meaning before stripping general punctuation so that
    # "1.0" cannot collide with "10".
    normalized = re.sub(r"(?<=\d)\.(?=\d)", " decimal ", normalized)
    normalized = re.sub(r"[\W_]+", "", normalized, flags=re.UNICODE)
    return normalized


def canonicalize_candidates(
    outputs: list[AgentCandidate],
) -> list[CanonicalCandidate]:
    merged: dict[str, CanonicalCandidate] = {}
    for output in outputs:
        key = canonicalize_value(output.value)
        if not key:
            continue
        output.canonical_key = key
        existing = merged.get(key)
        if existing is None:
            existing = CanonicalCandidate(
                id=f"c{len(merged)}",
                key=key,
                value=output.value.strip(),
                response=(output.response or output.value).strip(),
            )
            merged[key] = existing
        existing.evidence_ids = list(
            dict.fromkeys([*existing.evidence_ids, *output.evidence_ids])
        )
        if output.intervention not in existing.produced_by:
            existing.produced_by.append(output.intervention)
    return list(merged.values())


def normalize_panel_scores(
    raw_scores: dict[str, float],
    candidate_ids: list[str],
) -> dict[str, float]:
    """Clamp and normalize model support scores in deterministic code."""
    values = {
        candidate_id: max(
            0.0,
            float(raw_scores.get(candidate_id, 0.0)),
        )
        for candidate_id in candidate_ids
    }
    total = sum(values.values())
    if total <= 0:
        uniform = 1.0 / len(candidate_ids) if candidate_ids else 0.0
        return {candidate_id: uniform for candidate_id in candidate_ids}
    # Preserve unsupported probability mass when the evaluator assigns less
    # than 100 points in total.  Dividing a lone 10/100 candidate by its own
    # total would otherwise turn weak support into false certainty (1.0).
    denominator = max(100.0, total)
    return {
        candidate_id: value / denominator
        for candidate_id, value in values.items()
    }


def calculate_cci(
    scores: dict[str, dict[str, float]],
    *,
    stability_penalty: bool = True,
    cci_enabled: bool = True,
) -> dict[str, CandidateScore]:
    """Calculate mean support, cross-intervention range, and CCI."""
    candidate_ids = list(
        dict.fromkeys(
            candidate_id
            for perspective in scores.values()
            for candidate_id in perspective
        )
    )
    result: dict[str, CandidateScore] = {}
    for candidate_id in candidate_ids:
        intervention_scores = {
            mode: _clamp(mode_scores.get(candidate_id, 0.0))
            for mode, mode_scores in scores.items()
        }
        values = list(intervention_scores.values()) or [0.0]
        ce = sum(values) / len(values)
        ce_var = max(values) - min(values)
        if not cci_enabled:
            cci = ce
        elif stability_penalty:
            cci = ce * (1.0 - ce_var)
        else:
            cci = ce
        result[candidate_id] = CandidateScore(
            candidate_id=candidate_id,
            ce=_clamp(ce),
            ce_var=_clamp(ce_var),
            cci=_clamp(cci),
            intervention_scores=intervention_scores,
        )
    return result


def reliability_policy(
    scores: dict[str, CandidateScore],
    config: CausalTrustConfig,
) -> ReliabilityPolicyResult:
    ordered = sorted(scores.values(), key=lambda item: item.cci, reverse=True)
    if not ordered:
        return ReliabilityPolicyResult("ABSTAIN", 0.0, 0.0)
    best = ordered[0].cci
    second = ordered[1].cci if len(ordered) > 1 else 0.0
    margin = max(0.0, best - second)
    if best >= config.accept_threshold and (
        len(ordered) == 1 or margin >= config.margin_threshold
    ):
        decision: Decision = "ACCEPT"
    elif best >= config.retry_threshold:
        # The controller specializes this after diagnosing the failure source.
        decision = "RETRY_REASONING"
    else:
        decision = "ABSTAIN"
    return ReliabilityPolicyResult(decision, best, margin)


def _parse_json_object(content: str) -> dict[str, Any]:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.I)
        stripped = re.sub(r"\s*```$", "", stripped)
    candidates = [stripped]
    match = re.search(r"\{.*\}", stripped, re.DOTALL)
    if match:
        candidates.append(match.group(0))
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("LLM response is not a JSON object")


class CausalTrust:
    """Counterfactual calibration controller with bounded recovery."""

    _PERSPECTIVES: tuple[Intervention, ...] = (
        "baseline",
        "evidence_quality",
        "reasoning_reliability",
    )

    def __init__(
        self,
        llm_client: ChatClient,
        config: CausalTrustConfig | None = None,
    ) -> None:
        self.llm = llm_client
        self.config = config or get_config().causal_trust

    @property
    def enabled(self) -> bool:
        return bool(
            self.config.enabled
            and getattr(getattr(self.llm, "config", None), "api_key", "")
        )

    def run(
        self,
        *,
        query: str,
        evidence: list[EvidenceItem],
        query_id: str = "",
        recovery: RecoveryCallback | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        bounded_evidence = evidence[: self.config.max_evidence_items]
        if not self.enabled:
            return self._not_run(
                "disabled" if not self.config.enabled else "llm_not_configured"
            )
        if len(bounded_evidence) < self.config.minimum_evidence_items:
            return self._not_run("insufficient_evidence")

        passes: list[CalibrationPass] = []
        recovery_mode = ""
        try:
            first = self._calibrate_once(query, bounded_evidence)
            passes.append(first)
            final_pass = first
            decision = first.policy.decision
            if decision == "RETRY_REASONING":
                recovery_mode = self._diagnose_retry(first)
                decision = recovery_mode  # type: ignore[assignment]
                recovery_enabled = (
                    recovery_mode == "RETRY_RETRIEVAL"
                    and self.config.retrieval_recovery_enabled
                ) or (
                    recovery_mode == "RETRY_REASONING"
                    and self.config.reasoning_recovery_enabled
                )
                if (
                    recovery_enabled
                    and self.config.max_retries > 0
                    and recovery is not None
                ):
                    recovered = recovery(recovery_mode)
                    if len(recovered) >= self.config.minimum_evidence_items:
                        final_pass = self._calibrate_once(
                            query,
                            recovered[: self.config.max_evidence_items],
                            recovery_mode=recovery_mode,
                        )
                        passes.append(final_pass)
                        decision = (
                            "ACCEPT"
                            if final_pass.policy.decision == "ACCEPT"
                            else "ABSTAIN"
                        )

            selected = next(
                candidate
                for candidate in final_pass.candidates
                if candidate.id == final_pass.selected_id
            )
            accepted = decision == "ACCEPT"
            candidates_api = [
                final_pass.scores[candidate.id].to_api(candidate)
                for candidate in sorted(
                    final_pass.candidates,
                    key=lambda item: final_pass.scores[item.id].cci,
                    reverse=True,
                )
            ]
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            result: dict[str, Any] = {
                "status": "completed",
                "answer": selected.response if accepted else "",
                "confidence": round(final_pass.policy.confidence, 6),
                "decision": decision,
                "message": (
                    ""
                    if accepted
                    else (
                        "当前证据不足以可靠回答。"
                        if decision == "ABSTAIN"
                        else "可靠性校准建议在返回结论前执行一次恢复。"
                    )
                ),
                "selectedCandidateId": selected.id,
                "diagnosis": {
                    "evidenceRisk": round(final_pass.evidence_risk, 6),
                    "reasoningRisk": round(final_pass.reasoning_risk, 6),
                    "recommendedRecovery": (
                        recovery_mode if recovery_mode else "NONE"
                    ),
                },
                "candidates": candidates_api,
                "recovery": {
                    "attempted": len(passes) > 1,
                    "mode": recovery_mode or "NONE",
                    "attempts": max(0, len(passes) - 1),
                    "recovered": len(passes) > 1 and accepted,
                },
            }
            if self.config.trace_enabled:
                result["trace"] = {
                    "queryId": query_id,
                    "evidenceIds": [item.id for item in bounded_evidence],
                    "passes": [
                        self._pass_trace(index, item)
                        for index, item in enumerate(passes)
                    ],
                    "selected": selected.id,
                    "decision": decision,
                    "latencyMs": elapsed_ms,
                }
            return result
        except (
            LLMError,
            ValueError,
            KeyError,
            TypeError,
            StopIteration,
        ) as exc:
            return {
                "status": "failed",
                "answer": "",
                "confidence": 0.0,
                "decision": "NOT_RUN",
                "message": "可靠性校准未完成；论文检索结果仍然有效。",
                "reason": type(exc).__name__,
            }

    def _calibrate_once(
        self,
        query: str,
        evidence: list[EvidenceItem],
        *,
        recovery_mode: str = "",
    ) -> CalibrationPass:
        generated: dict[str, AgentCandidate] = {}
        baseline = self._generate(
            "baseline",
            query,
            evidence,
            recovery_mode=recovery_mode,
        )
        generated["baseline"] = baseline
        if self.config.evidence_intervention_enabled:
            generated["evidence_quality"] = self._generate(
                "evidence_quality",
                query,
                evidence,
                previous=baseline,
                recovery_mode=recovery_mode,
            )
        if self.config.reasoning_intervention_enabled:
            generated["reasoning_reliability"] = self._generate(
                "reasoning_reliability",
                query,
                evidence,
                previous=baseline,
                recovery_mode=recovery_mode,
            )

        candidates = canonicalize_candidates(list(generated.values()))
        if not candidates:
            raise ValueError("No valid calibration candidates")
        panel_scores = (
            self._panel(query, evidence, candidates)
            if self.config.panel_enabled
            else self._frequency_scores(generated, candidates)
        )
        scores = calculate_cci(
            panel_scores,
            stability_penalty=self.config.stability_penalty_enabled,
            cci_enabled=self.config.cci_enabled,
        )
        policy = reliability_policy(scores, self.config)
        selected_id = max(scores.values(), key=lambda item: item.cci).candidate_id
        baseline_id = next(
            candidate.id
            for candidate in candidates
            if "baseline" in candidate.produced_by
        )
        base_scores = {
            mode: values.get(baseline_id, 0.0)
            for mode, values in panel_scores.items()
        }
        evidence_risk = max(
            0.0,
            base_scores.get("baseline", 0.0)
            - base_scores.get(
                "evidence_quality",
                base_scores.get("baseline", 0.0),
            ),
        )
        reasoning_risk = max(
            0.0,
            base_scores.get("baseline", 0.0)
            - base_scores.get(
                "reasoning_reliability",
                base_scores.get("baseline", 0.0),
            ),
        )
        if (
            generated.get("evidence_quality")
            and generated["evidence_quality"].canonical_key
            != baseline.canonical_key
        ):
            evidence_risk = max(evidence_risk, 0.25)
        if (
            generated.get("reasoning_reliability")
            and generated["reasoning_reliability"].canonical_key
            != baseline.canonical_key
        ):
            reasoning_risk = max(reasoning_risk, 0.25)
        return CalibrationPass(
            generated=generated,
            candidates=candidates,
            panel_scores=panel_scores,
            scores=scores,
            selected_id=selected_id,
            policy=policy,
            evidence_risk=_clamp(evidence_risk),
            reasoning_risk=_clamp(reasoning_risk),
        )

    def _generate(
        self,
        intervention: Intervention,
        query: str,
        evidence: list[EvidenceItem],
        *,
        previous: AgentCandidate | None = None,
        recovery_mode: str = "",
    ) -> AgentCandidate:
        evidence_json = json.dumps(
            [item.to_prompt() for item in evidence],
            ensure_ascii=False,
        )
        previous_json = (
            json.dumps(previous.to_trace(), ensure_ascii=False)
            if previous
            else "无"
        )
        perspective = {
            "baseline": (
                "正常完成任务。只使用给定证据，不得虚构；形成一个简洁、"
                "可核验的核心科研结论。"
            ),
            "evidence_quality": (
                "假设先前结论可能因证据不完整、无关、冲突或质量不足而错误。"
                "不要获取新信息，重新筛选相同证据后独立作答。"
            ),
            "reasoning_reliability": (
                "假设先前结论可能因理解、实体对应、条件遗漏、数字、逻辑或"
                "多跳推理错误。不要获取新信息，重新严格推导后独立作答。"
            ),
        }[intervention]
        recovery_instruction = {
            "RETRY_RETRIEVAL": (
                "这是证据恢复后的重新校准；优先核对新增或更直接的证据。"
            ),
            "RETRY_REASONING": (
                "这是推理恢复后的重新校准；显式检查限定词和证据到结论的"
                "每个必要跳步。"
            ),
        }.get(recovery_mode, "")
        prompt = f"""你正在执行基于真实论文证据的研究 Agent 任务。

用户问题：
{query}

可用证据（JSON）：
{evidence_json}

先前答案：
{previous_json}

当前受控干预：{intervention}
{perspective}
{recovery_instruction}

要求：
1. result.value 是参与校准的单一核心结论，避免空泛描述。
2. response 是给用户看的简洁结论，必须保留必要限定条件。
3. evidence_ids 只能引用输入中的证据 id，且必须真正支持结论。
4. 无法得到结论时，result.value 使用“证据不足”。
5. 只输出 JSON，不要输出思维链。

严格输出：
{{
  "result": {{"type": "research_conclusion", "value": "..."}},
  "evidence_ids": ["..."],
  "response": "..."
}}"""
        response = self.llm.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=900,
            json_mode=True,
        )
        payload = _parse_json_object(response.content)
        raw_result = payload.get("result")
        if not isinstance(raw_result, dict):
            raise ValueError("Candidate result must be an object")
        value = str(raw_result.get("value", "")).strip()
        if not value:
            raise ValueError("Candidate value is empty")
        allowed_ids = {item.id for item in evidence}
        raw_evidence_ids = payload.get("evidence_ids", [])
        evidence_ids = (
            [
                str(item)
                for item in raw_evidence_ids
                if str(item) in allowed_ids
            ]
            if isinstance(raw_evidence_ids, list)
            else []
        )
        return AgentCandidate(
            intervention=intervention,
            result_type=str(
                raw_result.get("type", "research_conclusion")
            ).strip()
            or "research_conclusion",
            value=value,
            response=str(payload.get("response", value)).strip() or value,
            evidence_ids=list(dict.fromkeys(evidence_ids)),
        )

    def _panel(
        self,
        query: str,
        evidence: list[EvidenceItem],
        candidates: list[CanonicalCandidate],
    ) -> dict[str, dict[str, float]]:
        evidence_json = json.dumps(
            [item.to_prompt() for item in evidence],
            ensure_ascii=False,
        )
        candidates_json = json.dumps(
            [
                {
                    "candidate_id": item.id,
                    "value": item.value,
                    "evidence_ids": item.evidence_ids,
                }
                for item in candidates
            ],
            ensure_ascii=False,
        )
        prompt = f"""你是 Agent Reliability Evaluator。

Query:
{query}

Evidence:
{evidence_json}

Candidate Answers:
{candidates_json}

请独立从三种视角评估每个 Candidate：
- baseline：正常证据使用；
- evidence_quality：假设证据可能不完整、无关、冲突或质量不足；
- reasoning_reliability：假设证据理解、计算或推理可能有误。

每个视角都要评价：是否直接回答问题、证据支持、证据冲突、未经证明的
推理，以及在该失败假设下是否仍可靠。给出 0 到 100 的 support。
禁止生成新 Candidate。不要自行归一化概率。只输出 JSON。

严格输出：
{{
  "perspectives": {{
    "baseline": [{{"candidate_id": "c0", "support": 0}}],
    "evidence_quality": [{{"candidate_id": "c0", "support": 0}}],
    "reasoning_reliability": [{{"candidate_id": "c0", "support": 0}}]
  }}
}}"""
        response = self.llm.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=1000,
            json_mode=True,
        )
        payload = _parse_json_object(response.content)
        perspectives = payload.get("perspectives")
        if not isinstance(perspectives, dict):
            raise ValueError("Panel perspectives are missing")
        candidate_ids = [item.id for item in candidates]
        result: dict[str, dict[str, float]] = {}
        active_modes = [
            mode
            for mode in self._PERSPECTIVES
            if mode == "baseline"
            or (
                mode == "evidence_quality"
                and self.config.evidence_intervention_enabled
            )
            or (
                mode == "reasoning_reliability"
                and self.config.reasoning_intervention_enabled
            )
        ]
        for mode in active_modes:
            entries = perspectives.get(mode)
            if not isinstance(entries, list):
                raise ValueError(f"Panel perspective is missing: {mode}")
            raw: dict[str, float] = {}
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                candidate_id = str(entry.get("candidate_id", ""))
                if candidate_id not in candidate_ids:
                    continue
                try:
                    raw[candidate_id] = max(
                        0.0,
                        min(100.0, float(entry.get("support", 0.0))),
                    )
                except (TypeError, ValueError):
                    raw[candidate_id] = 0.0
            result[mode] = normalize_panel_scores(raw, candidate_ids)
        return result

    @staticmethod
    def _frequency_scores(
        generated: dict[str, AgentCandidate],
        candidates: list[CanonicalCandidate],
    ) -> dict[str, dict[str, float]]:
        candidate_ids = [item.id for item in candidates]
        counts = {
            item.id: float(len(item.produced_by))
            for item in candidates
        }
        total = sum(counts.values())
        normalized = {
            candidate_id: (
                counts.get(candidate_id, 0.0) / total if total else 0.0
            )
            for candidate_id in candidate_ids
        }
        return {
            mode: dict(normalized)
            for mode in generated
        }

    @staticmethod
    def _diagnose_retry(calibration: CalibrationPass) -> str:
        return (
            "RETRY_RETRIEVAL"
            if calibration.evidence_risk >= calibration.reasoning_risk
            else "RETRY_REASONING"
        )

    @staticmethod
    def _pass_trace(
        index: int,
        calibration: CalibrationPass,
    ) -> dict[str, Any]:
        return {
            "attempt": index,
            "generated": {
                mode: candidate.to_trace()
                for mode, candidate in calibration.generated.items()
            },
            "panel": calibration.panel_scores,
            "cci": {
                candidate_id: {
                    "meanSupport": score.ce,
                    "instability": score.ce_var,
                    "cci": score.cci,
                }
                for candidate_id, score in calibration.scores.items()
            },
            "selected": calibration.selected_id,
            "policyDecision": calibration.policy.decision,
        }

    @staticmethod
    def _not_run(reason: str) -> dict[str, Any]:
        return {
            "status": "skipped",
            "answer": "",
            "confidence": 0.0,
            "decision": "NOT_RUN",
            "message": "当前请求未运行可靠性校准。",
            "reason": reason,
        }
