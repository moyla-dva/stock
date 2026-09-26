"""技术事实模型 — 事实层与决策层之间的唯一数据契约。

所有事实使用 Pydantic v2 BaseModel，下游永远不碰裸 dict。
拼错字段名 → IDE 报错；字段缺失 → Pydantic 验证报错。
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

from stock_analyzer.core.models import BarState


# ---------------------------------------------------------------------------
# 基础事实模型
# ---------------------------------------------------------------------------

class FractalFact(BaseModel):
    """顶底分型事实。"""
    model_config = {"frozen": True}

    fractal_type: Literal["top", "bottom"]
    pivot_date: date
    pivot_price: float
    pivot_index: int
    is_confirmed: bool = False
    confirmation_balance: float | None = None
    source_bar_indices: tuple[int, int, int] = (0, 0, 0)


class RectangleFact(BaseModel):
    """矩形/箱体事实。"""
    model_config = {"frozen": True}

    lookback: int
    upper: float
    lower: float
    c_point: float             # 最低收盘价（非最低影线）
    mid: float
    width_pct: float
    touch_count_upper: int = 0
    touch_count_lower: int = 0
    quality_score: float = 0.0
    latest_position: Literal[
        "below", "lower_half", "mid", "upper_half", "above"
    ] = "mid"
    # 前值参照（用于突破/破位判定）
    previous_upper: float | None = None
    previous_lower: float | None = None
    breaks_previous_upper: bool = False
    breaks_previous_lower: bool = False


class ResistanceZone(BaseModel):
    """阻力区。"""
    model_config = {"frozen": True}

    source: Literal["prior_high", "gap", "macro_upper", "volume_peak"]
    price: float
    strength_score: float = 0.0     # 0-100
    distance_pct: float = 0.0
    touch_count: int = 0
    role: Literal["target", "warning", "ignore"] = "warning"


class MomentumFact(BaseModel):
    """动能事实。"""
    model_config = {"frozen": True}

    balance_ma3: float = 0.0          # 3日均衡比均值
    williams_r: float = 50.0          # %R 值 (0-100)
    power_flip: bool = False          # 迫切性跃迁
    compression_score: float = 0.0    # 威廉时钟压缩分 (0-100)
    volume_ratio: float = 1.0         # 量比


class MacroFact(BaseModel):
    """宏观环境事实。"""
    model_config = {"frozen": True}

    above_ma250: bool = True
    ma250_slope: float | None = None
    ma60_rising: bool | None = None          # None = 样本不足
    weekly_macd_bearish: bool = False
    weekly_macd_expanding_green: bool = False


class RepairFact(BaseModel):
    """修复观察事实。"""
    model_config = {"frozen": True}

    stage: Literal[
        "none", "repair_setup", "repair_impulse", "repair_confirmed"
    ] = "none"
    repair_impulse: bool = False
    has_bottom_fractal: bool = False
    recovery_strength: float = 0.0


class AttackDayFact(BaseModel):
    """攻击日事实。"""
    model_config = {"frozen": True}

    day1_high: float = 0.0
    day2_high: float = 0.0
    day2_low: float = 0.0
    trigger_price: float = 0.0       # Day2 高点 + 0.01
    stop_price: float = 0.0          # Day2 最低价
    is_valid: bool = False


class IgnitionFact(BaseModel):
    """起爆点事实。"""
    model_config = {"frozen": True}

    trigger_price: float = 0.0       # Open + (PrevHigh - PrevClose) * N
    multiplier: float = 1.0
    is_triggered: bool = False


class BearTrapFact(BaseModel):
    """破底翻事实。"""
    model_config = {"frozen": True}

    break_pct: float = 0.0           # 跌破幅度
    recover_days: int = 0            # 恢复天数
    recovered_above_lower: bool = False
    is_valid: bool = False


class TradePlanFact(BaseModel):
    """交易计划相关事实（用于 Plan Gate 判定）。"""

    entry_price: float | None = None
    stop_loss: float | None = None
    target_price: float | None = None
    reward_risk_ratio: float | None = None
    stop_distance_pct: float | None = None
    chase_risk: bool = False         # 追高风险
    overheat_score: float = 0.0      # 过热分


# ---------------------------------------------------------------------------
# 聚合事实容器
# ---------------------------------------------------------------------------

class TechnicalFacts(BaseModel):
    """一只股票在某个时间切片上的全部技术事实。

    这是事实层的唯一输出契约。下游决策层通过强类型字段访问事实，
    不再出现 facts.get("structure") 式取值。
    """

    # ---- 身份与元数据 ----
    security_id: str                  # qualified code, e.g. "sh600096"
    as_of: date
    bar_state: BarState = BarState.CLOSED
    strategy_version: str = ""
    data_source: str = "unknown"
    data_revision: str = ""

    # ---- 结构事实 ----
    fractals: list[FractalFact] = Field(default_factory=list)
    rectangles: dict[str, RectangleFact] = Field(default_factory=dict)
    active_rectangle: RectangleFact | None = None
    resistance_zones: list[ResistanceZone] = Field(default_factory=list)

    # ---- 动能事实 ----
    momentum: MomentumFact | None = None

    # ---- 宏观事实 ----
    macro: MacroFact | None = None

    # ---- 修复事实 ----
    repair: RepairFact | None = None

    # ---- 触发事实 ----
    attack_day: AttackDayFact | None = None
    ignition: IgnitionFact | None = None
    bear_trap: BearTrapFact | None = None

    # ---- 交易计划事实 ----
    trade_plan: TradePlanFact | None = None

    # ---- 扩展事实（插件注册） ----
    extensions: dict[str, Any] = Field(default_factory=dict)

    def to_legacy_dict(self) -> dict[str, Any]:
        """转换为旧格式 dict，用于向后兼容现有代码。

        注意：这是过渡期方法，随着迁移完成将逐步移除。
        """
        result: dict[str, Any] = {
            "security_id": self.security_id,
            "as_of": str(self.as_of),
            "bar_state": self.bar_state.value,
            "strategy_version": self.strategy_version,
        }

        if self.momentum:
            result["momentum"] = self.momentum.model_dump()

        if self.macro:
            result["macro"] = self.macro.model_dump()

        if self.active_rectangle:
            result["structure"] = self.active_rectangle.model_dump()

        if self.rectangles:
            result["rectangle_candidates"] = {
                k: v.model_dump() for k, v in self.rectangles.items()
            }

        if self.fractals:
            result["fractals"] = [f.model_dump() for f in self.fractals]

        if self.resistance_zones:
            result["resistance_zones"] = [
                z.model_dump() for z in self.resistance_zones
            ]

        if self.repair:
            result["repair"] = self.repair.model_dump()

        if self.attack_day:
            result["attack_day"] = self.attack_day.model_dump()

        if self.ignition:
            result["ignition"] = self.ignition.model_dump()

        if self.trade_plan:
            result["trade_plan"] = self.trade_plan.model_dump()

        result.update(self.extensions)
        return result

    @classmethod
    def empty(cls, security_id: str = "",
              as_of: date | None = None) -> TechnicalFacts:
        """创建空白事实容器。"""
        return cls(
            security_id=security_id,
            as_of=as_of or date.today(),
        )
