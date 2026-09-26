"""声明式决策闸门框架 — 四层漏斗状态机。

核心思路:
  - 每条规则是一个独立可测试的类
  - 每层 Gate 聚合多条规则，按排除法裁定
  - DecisionFunnel 串联多层 Gate，首层否决即短路
  - 所有裁定自动生成中文解释链，支持审计追溯
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

from stock_analyzer.core.facts import TechnicalFacts
from stock_analyzer.core.models import CandidateState, Permission, PlanStatus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 规则结果与闸门裁定
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RuleResult:
    """单条规则的判定结果。"""
    rule_name: str
    passed: bool
    reason: str
    severity: Literal["block", "degrade", "warn", "info"] = "info"


@dataclass
class GateVerdict:
    """一层闸门的综合裁定。"""
    gate_name: str
    passed: bool
    permission: Permission
    rule_results: list[RuleResult] = field(default_factory=list)

    @property
    def block_reasons(self) -> list[str]:
        """被否决的原因列表。"""
        return [r.reason for r in self.rule_results
                if not r.passed and r.severity == "block"]

    @property
    def warnings(self) -> list[str]:
        """警告列表。"""
        return [r.reason for r in self.rule_results
                if r.severity == "warn"]

    @property
    def degrade_reasons(self) -> list[str]:
        """降级原因列表。"""
        return [r.reason for r in self.rule_results
                if not r.passed and r.severity == "degrade"]


# ---------------------------------------------------------------------------
# 规则协议
# ---------------------------------------------------------------------------

@runtime_checkable
class GateRule(Protocol):
    """闸门规则协议 — 所有规则必须实现此接口。"""

    @property
    def name(self) -> str:
        """规则唯一名称。"""
        ...

    def evaluate(self, facts: TechnicalFacts) -> RuleResult:
        """基于事实判定是否通过。"""
        ...


# ---------------------------------------------------------------------------
# 闸门
# ---------------------------------------------------------------------------

class Gate:
    """一层闸门 = 一组规则的有序执行。

    任何一条 severity='block' 的规则未通过，整层闸门判定为否决。
    """

    def __init__(
        self,
        name: str,
        rules: list[GateRule],
        on_block: Permission = Permission.FORBIDDEN,
        on_pass: Permission = Permission.BREAKOUT_ALLOWED,
    ) -> None:
        self.name = name
        self.rules = rules
        self.on_block = on_block
        self.on_pass = on_pass

    def evaluate(self, facts: TechnicalFacts) -> GateVerdict:
        """执行全部规则并返回综合裁定。"""
        results: list[RuleResult] = []
        for rule in self.rules:
            try:
                result = rule.evaluate(facts)
                results.append(result)
            except Exception:
                logger.error("规则 %s 执行异常", rule.name, exc_info=True)
                results.append(RuleResult(
                    rule_name=rule.name,
                    passed=False,
                    reason=f"规则 {rule.name} 执行异常",
                    severity="warn",
                ))

        any_blocked = any(
            not r.passed and r.severity == "block" for r in results
        )

        return GateVerdict(
            gate_name=self.name,
            passed=not any_blocked,
            permission=self.on_block if any_blocked else self.on_pass,
            rule_results=results,
        )


# ---------------------------------------------------------------------------
# 漏斗结果
# ---------------------------------------------------------------------------

@dataclass
class FunnelResult:
    """四层漏斗的最终裁定结果。"""
    permission: Permission
    candidate_state: CandidateState = CandidateState.STRUCTURE_CANDIDATE
    plan_status: PlanStatus = PlanStatus.BLOCKED
    verdicts: list[GateVerdict] = field(default_factory=list)
    explanation: list[str] = field(default_factory=list)

    @property
    def is_actionable(self) -> bool:
        """是否可执行交易。"""
        return self.permission in (
            Permission.PULLBACK_ALLOWED,
            Permission.BREAKOUT_ALLOWED,
            Permission.ATTACK_ALLOWED,
        ) and self.plan_status == PlanStatus.READY

    @property
    def all_block_reasons(self) -> list[str]:
        """汇总所有层的否决原因。"""
        reasons = []
        for v in self.verdicts:
            reasons.extend(v.block_reasons)
        return reasons

    @property
    def all_warnings(self) -> list[str]:
        """汇总所有层的警告。"""
        warnings = []
        for v in self.verdicts:
            warnings.extend(v.warnings)
        return warnings


# ---------------------------------------------------------------------------
# 决策漏斗
# ---------------------------------------------------------------------------

class DecisionFunnel:
    """四层通关漏斗 — 核心决策引擎。

    排除法：第一层否决后不再继续下层。
    每层 Gate 可包含多条规则，全部执行后汇总。

    用法::

        funnel = DecisionFunnel(gates=[
            Gate("环境与大势", [MA250VetoRule(), WeeklyMACDVetoRule()]),
            Gate("空间与赔率", [RewardRiskRule()]),
            Gate("微观结构",   [StructureExistsRule()]),
            Gate("触发与计划", [TriggerFiredRule()]),
        ])
        result = funnel.evaluate(facts)
        print(result.explanation)
    """

    def __init__(self, gates: list[Gate] | None = None) -> None:
        self.gates: list[Gate] = gates or []

    def add_gate(self, gate: Gate) -> None:
        """添加一层闸门。"""
        self.gates.append(gate)

    def evaluate(self, facts: TechnicalFacts) -> FunnelResult:
        """按顺序执行所有闸门，首层否决即短路。"""
        verdicts: list[GateVerdict] = []
        final_permission = Permission.WATCH_ONLY

        for gate in self.gates:
            verdict = gate.evaluate(facts)
            verdicts.append(verdict)

            if not verdict.passed:
                final_permission = verdict.permission
                break
            else:
                final_permission = verdict.permission

        # 推断候选子状态和计划状态
        candidate_state = self._infer_candidate_state(
            facts, final_permission, verdicts,
        )
        plan_status = self._infer_plan_status(
            facts, final_permission, verdicts,
        )

        explanation = self._build_explanation(verdicts)

        return FunnelResult(
            permission=final_permission,
            candidate_state=candidate_state,
            plan_status=plan_status,
            verdicts=verdicts,
            explanation=explanation,
        )

    def _infer_candidate_state(
        self,
        facts: TechnicalFacts,
        permission: Permission,
        verdicts: list[GateVerdict],
    ) -> CandidateState:
        """根据许可层和事实推断候选子状态。"""
        if permission == Permission.FORBIDDEN:
            return CandidateState.STRUCTURE_CANDIDATE

        # 检查修复事实
        if facts.repair and facts.repair.stage == "repair_impulse":
            return CandidateState.STRONG_REPAIR_WATCH
        if facts.repair and facts.repair.stage == "repair_setup":
            return CandidateState.WEAK_REPAIR

        # 检查交易计划
        if facts.trade_plan and facts.trade_plan.reward_risk_ratio:
            if facts.trade_plan.reward_risk_ratio >= 2.0:
                if permission in (
                    Permission.BREAKOUT_ALLOWED,
                    Permission.ATTACK_ALLOWED,
                ):
                    return CandidateState.ENTRY_READY

        # 检查触发事实
        if (facts.attack_day and facts.attack_day.is_valid) or \
           (facts.ignition and facts.ignition.is_triggered) or \
           (facts.bear_trap and facts.bear_trap.is_valid):
            return CandidateState.REVERSAL_CONFIRMED

        # 检查结构
        if facts.active_rectangle:
            pos = facts.active_rectangle.latest_position
            if pos in ("lower_half", "below"):
                return CandidateState.PULLBACK_SETUP

        return CandidateState.STRUCTURE_CANDIDATE

    def _infer_plan_status(
        self,
        facts: TechnicalFacts,
        permission: Permission,
        verdicts: list[GateVerdict],
    ) -> PlanStatus:
        """根据事实和许可推断交易计划状态。"""
        if permission in (Permission.FORBIDDEN, Permission.RISK_ONLY):
            return PlanStatus.BLOCKED

        tp = facts.trade_plan
        if tp is None:
            return PlanStatus.WAITING

        if tp.entry_price is None or tp.stop_loss is None:
            return PlanStatus.BLOCKED

        if tp.target_price is None:
            return PlanStatus.WAITING

        if tp.reward_risk_ratio is not None and tp.reward_risk_ratio < 2.0:
            return PlanStatus.BLOCKED

        if tp.stop_distance_pct is not None and tp.stop_distance_pct > 8.0:
            return PlanStatus.BLOCKED

        return PlanStatus.READY

    @staticmethod
    def _build_explanation(verdicts: list[GateVerdict]) -> list[str]:
        """生成人类可读的中文解释链。"""
        lines: list[str] = []
        for verdict in verdicts:
            for r in verdict.rule_results:
                icon = "✓" if r.passed else "✗"
                lines.append(f"{icon} [{verdict.gate_name}] {r.reason}")
            if not verdict.passed:
                lines.append(
                    f"⛔ 在「{verdict.gate_name}」层被拦截，"
                    f"后续闸门未执行"
                )
                break
        return lines
