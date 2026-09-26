"""核心领域模型 — 系统中所有模块引用股票、行情和状态的唯一方式。

设计原则:
  - 值对象（SecurityId / PriceBar）不可变（frozen dataclass）
  - 枚举覆盖所有业务状态，消除魔法字符串
  - PriceSeries 内部使用 NumPy 数组，提供类型安全的访问接口
  - 与现有 dict 体系可互转（from_legacy_dict / to_legacy_dict）
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any

import numpy as np
from numpy.typing import NDArray


# ---------------------------------------------------------------------------
# 枚举：市场与板块
# ---------------------------------------------------------------------------

class Market(Enum):
    """交易所。"""
    SH = "sh"  # 上交所
    SZ = "sz"  # 深交所
    BJ = "bj"  # 北交所


class BoardType(Enum):
    """板块类型。"""
    MAIN = "main"    # 主板
    SME = "sme"      # 中小板
    GEM = "gem"      # 创业板
    STAR = "star"    # 科创板
    BSE = "bse"      # 北交所


# ---------------------------------------------------------------------------
# 枚举：行情状态
# ---------------------------------------------------------------------------

class BarState(Enum):
    """K 线形成状态。"""
    CLOSED = "closed"    # 已收盘，不可变
    PREVIEW = "preview"  # 盘中预览，可变


class Timeframe(Enum):
    """时间周期。"""
    DAILY = "1d"
    WEEKLY = "1w"
    SIXTY_MIN = "60m"
    FOUR_HOUR = "4h"  # 聚合生成


# ---------------------------------------------------------------------------
# 枚举：决策状态
# ---------------------------------------------------------------------------

class Permission(Enum):
    """许可层输出 — 非线性枚举，不可用数字排序。

    被 FORBIDDEN 拦截后，任何高分都不能进入可参与队列。
    """
    FORBIDDEN = "forbidden"
    WATCH_ONLY = "watch_only"
    STRUCTURE_ONLY = "structure_only"
    PULLBACK_ALLOWED = "pullback_allowed"
    BREAKOUT_ALLOWED = "breakout_allowed"
    ATTACK_ALLOWED = "attack_allowed"
    RISK_ONLY = "risk_only"


class CandidateState(Enum):
    """候选子状态 — 从 P25 候选拆分而来。"""
    STRUCTURE_CANDIDATE = "structure_candidate"      # 候
    PULLBACK_SETUP = "pullback_setup"                # 候
    WEAK_REPAIR = "weak_repair_candidate"            # 候?
    STRONG_REPAIR_WATCH = "strong_repair_watch"      # 待触
    REVERSAL_CONFIRMED = "reversal_confirmed"        # 触
    ENTRY_READY = "entry_ready"                      # 买


class PlanStatus(Enum):
    """交易计划闸门状态。"""
    READY = "ready"
    WAITING = "waiting"
    BLOCKED = "blocked"


# ---------------------------------------------------------------------------
# 值对象：证券身份
# ---------------------------------------------------------------------------

_CODE_PATTERN = re.compile(r"^[0-9]{6}$")
_QUALIFIED_PATTERN = re.compile(
    r"^(?P<prefix>[a-zA-Z]{2})(?P<code>[0-9]{6})$"
)


@dataclass(frozen=True)
class SecurityId:
    """不可变的证券身份 — 系统中所有模块引用股票的唯一方式。

    构造时自动校验 code 格式，保证后续不需要 normalize_code。
    """
    code: str
    market: Market

    def __post_init__(self) -> None:
        if not _CODE_PATTERN.match(self.code):
            raise ValueError(
                f"股票代码必须为 6 位纯数字，收到: {self.code!r}"
            )

    @property
    def qualified_code(self) -> str:
        """带市场前缀的完整代码，如 sh600096。"""
        return f"{self.market.value}{self.code}"

    @classmethod
    def parse(cls, raw: str) -> SecurityId:
        """从各种格式解析证券身份。

        支持: '600096', 'sh600096', 'SH600096', '600096.SH'
        """
        raw = raw.strip()

        # 带前缀: sh600096
        m = _QUALIFIED_PATTERN.match(raw.lower())
        if m:
            prefix = m.group("prefix")
            code = m.group("code")
            market = _prefix_to_market(prefix)
            return cls(code=code, market=market)

        # 带后缀: 600096.SH
        if "." in raw:
            parts = raw.split(".")
            if len(parts) == 2 and _CODE_PATTERN.match(parts[0]):
                market = _prefix_to_market(parts[1].lower())
                return cls(code=parts[0], market=market)

        # 纯数字: 600096 — 根据代码段推断市场
        if _CODE_PATTERN.match(raw):
            return cls(code=raw, market=_infer_market(raw))

        raise ValueError(f"无法解析证券代码: {raw!r}")

    def __str__(self) -> str:
        return self.qualified_code


def _prefix_to_market(prefix: str) -> Market:
    """将市场前缀映射为 Market 枚举。"""
    mapping = {"sh": Market.SH, "sz": Market.SZ, "bj": Market.BJ}
    if prefix in mapping:
        return mapping[prefix]
    raise ValueError(f"未知市场前缀: {prefix!r}")


def _infer_market(code: str) -> Market:
    """根据代码段推断所属市场。"""
    if code.startswith("6"):
        return Market.SH
    if code.startswith(("0", "3")):
        return Market.SZ
    if code.startswith(("4", "8")):
        return Market.BJ
    # 默认深圳
    return Market.SZ


# ---------------------------------------------------------------------------
# 值对象：证券画像（时间切片）
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SecurityProfile:
    """时间切片上的证券画像，解决 ST/改名/重组问题（ADR-0003）。"""
    security_id: SecurityId
    name: str
    board: BoardType
    sector: str = ""
    concepts: tuple[str, ...] = ()
    effective_date: date = field(default_factory=date.today)
    is_st: bool = False
    is_suspended: bool = False

    @classmethod
    def from_dict(cls, code: str, payload: dict[str, Any] | None = None
                  ) -> SecurityProfile:
        """从旧格式字典构建画像（向后兼容）。"""
        payload = payload or {}
        sid = SecurityId.parse(code)
        name = str(payload.get("name") or code).strip()
        sector = str(payload.get("sector") or "").strip()
        concepts_raw = payload.get("concepts") or payload.get("concept") or []
        if isinstance(concepts_raw, str):
            concepts_raw = [concepts_raw]
        concepts = tuple(
            str(c).strip() for c in concepts_raw if str(c).strip()
        )
        return cls(
            security_id=sid, name=name, board=BoardType.MAIN,
            sector=sector, concepts=concepts,
        )


# ---------------------------------------------------------------------------
# 值对象：单根 K 线
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PriceBar:
    """单根 K 线 — 不可变值对象。"""
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    amount: float = 0.0
    bar_state: BarState = BarState.CLOSED

    @property
    def balance(self) -> float:
        """威廉归一化多空均衡比 ∈ [-1, 1]。

        +1.0: 光头阳线（多头完胜）
        -1.0: 光脚阴线（空头完胜）
         0.0: 多空势均力敌
        """
        span = self.high - self.low
        if span <= 0:
            return 0.0
        return (2 * self.close - self.high - self.low) / span


# ---------------------------------------------------------------------------
# 聚合对象：K 线序列
# ---------------------------------------------------------------------------

@dataclass
class PriceSeries:
    """完整的 K 线序列 — 领域层操作的核心数据结构。

    内部用 NumPy 数组存储，提供类型安全的访问接口。
    需要 pandas DataFrame 时调用 as_dataframe()。
    """
    security_id: SecurityId
    timeframe: Timeframe
    dates: NDArray[np.datetime64]
    opens: NDArray[np.float64]
    highs: NDArray[np.float64]
    lows: NDArray[np.float64]
    closes: NDArray[np.float64]
    volumes: NDArray[np.int64]
    bar_states: list[BarState] = field(default_factory=list)

    # 数据溯源
    data_source: str = "unknown"
    data_revision: str = ""

    def __len__(self) -> int:
        return len(self.dates)

    def __bool__(self) -> bool:
        return len(self) > 0

    @property
    def last_closed_index(self) -> int:
        """最后一根已收盘 K 线的索引，如果全部为 preview 返回 -1。"""
        for i in range(len(self) - 1, -1, -1):
            if i < len(self.bar_states) and \
               self.bar_states[i] == BarState.CLOSED:
                return i
        # 如果没有 bar_states 信息，默认最后一根
        if not self.bar_states:
            return len(self) - 1 if len(self) > 0 else -1
        return -1

    @property
    def last_close(self) -> float:
        """最后一根 K 线的收盘价。"""
        if len(self) == 0:
            return 0.0
        return float(self.closes[-1])

    def balance_array(self) -> NDArray[np.float64]:
        """计算全序列的威廉归一化均衡比数组。"""
        span = self.highs - self.lows
        # 避免除零
        safe_span = np.where(span > 0, span, 1.0)
        return np.where(
            span > 0,
            (2 * self.closes - self.highs - self.lows) / safe_span,
            0.0,
        )

    def as_dataframe(self):
        """转换为 pandas DataFrame（延迟导入 pandas）。"""
        import pandas as pd
        df = pd.DataFrame({
            "trade_date": self.dates,
            "open": self.opens,
            "high": self.highs,
            "low": self.lows,
            "close": self.closes,
            "volume": self.volumes,
        })
        return df

    @classmethod
    def from_dataframe(cls, df, security_id: SecurityId,
                       timeframe: Timeframe = Timeframe.DAILY,
                       data_source: str = "unknown") -> PriceSeries:
        """从 pandas DataFrame 构建 PriceSeries（向后兼容）。"""
        dates = np.array(df["trade_date"].values, dtype="datetime64[D]") \
            if "trade_date" in df.columns else \
            np.array(df.index.values, dtype="datetime64[D]")

        bar_states = [BarState.CLOSED] * len(df)
        if "bar_state" in df.columns:
            bar_states = [
                BarState(v) if isinstance(v, str) else BarState.CLOSED
                for v in df["bar_state"]
            ]

        return cls(
            security_id=security_id,
            timeframe=timeframe,
            dates=dates,
            opens=np.asarray(df["open"].values, dtype=np.float64),
            highs=np.asarray(df["high"].values, dtype=np.float64),
            lows=np.asarray(df["low"].values, dtype=np.float64),
            closes=np.asarray(df["close"].values, dtype=np.float64),
            volumes=np.asarray(df["volume"].values, dtype=np.int64),
            bar_states=bar_states,
            data_source=data_source,
        )
