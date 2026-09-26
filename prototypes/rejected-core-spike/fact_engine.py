"""插件化事实计算引擎 — 按拓扑顺序执行已注册的事实计算器。

核心思路：
  - 每个事实计算器只负责一类事实（分型、矩形、动能、宏观等）
  - 计算器通过 dependencies 声明依赖关系
  - 引擎自动按拓扑排序执行，保证依赖先于被依赖者
  - 新增事实只需：1) 定义模型  2) 实现计算器  3) 注册
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Protocol, runtime_checkable

from stock_analyzer.core.facts import TechnicalFacts
from stock_analyzer.core.models import PriceSeries, SecurityProfile

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 计算器协议
# ---------------------------------------------------------------------------

@runtime_checkable
class FactComputer(Protocol):
    """事实计算器协议 — 所有事实计算器必须实现此接口。"""

    @property
    def name(self) -> str:
        """计算器唯一名称，用于依赖解析。"""
        ...

    @property
    def dependencies(self) -> list[str]:
        """依赖的其他计算器名称（用于拓扑排序执行顺序）。"""
        ...

    def compute(
        self,
        series: PriceSeries,
        profile: SecurityProfile,
        existing_facts: TechnicalFacts,
    ) -> TechnicalFacts:
        """接收已有事实，返回增强后的事实。

        实现者应使用 existing_facts.model_copy(update={...})
        来返回新实例，不要原地修改。
        """
        ...


# ---------------------------------------------------------------------------
# 事实引擎
# ---------------------------------------------------------------------------

class CircularDependencyError(Exception):
    """事实计算器之间存在循环依赖。"""


class FactEngine:
    """事实引擎 — 管理和执行事实计算器。

    用法::

        engine = FactEngine()
        engine.register(MomentumComputer())
        engine.register(FractalComputer())
        engine.register(RectangleComputer())  # depends on fractal

        facts = engine.compute_all(series, profile)
    """

    def __init__(self) -> None:
        self._computers: dict[str, FactComputer] = {}
        self._sorted: list[FactComputer] | None = None

    def register(self, computer: FactComputer) -> None:
        """注册一个事实计算器。

        注册后会使缓存的拓扑排序失效，下次 compute_all 时重新排序。
        """
        if computer.name in self._computers:
            logger.warning(
                "覆盖已注册的事实计算器: %s", computer.name
            )
        self._computers[computer.name] = computer
        self._sorted = None  # 使缓存失效

    def compute_all(
        self,
        series: PriceSeries,
        profile: SecurityProfile,
        strategy_version: str = "",
    ) -> TechnicalFacts:
        """按拓扑顺序执行全部已注册的计算器，返回聚合事实。"""
        if len(series) == 0:
            return TechnicalFacts.empty(
                security_id=profile.security_id.qualified_code,
            )

        import numpy as np
        last_date = series.dates[-1]
        if isinstance(last_date, np.datetime64):
            from datetime import date as date_cls
            ts = (last_date - np.datetime64("1970-01-01", "D")).astype(int)
            as_of = date_cls.fromordinal(ts + 719163)
        else:
            as_of = last_date

        bar_state = (
            series.bar_states[-1]
            if series.bar_states
            else __import__("stock_analyzer.core.models",
                            fromlist=["BarState"]).BarState.CLOSED
        )

        facts = TechnicalFacts(
            security_id=profile.security_id.qualified_code,
            as_of=as_of,
            bar_state=bar_state,
            strategy_version=strategy_version,
            data_source=series.data_source,
            data_revision=series.data_revision,
        )

        ordered = self._topological_order()

        for computer in ordered:
            try:
                facts = computer.compute(series, profile, facts)
            except Exception:
                logger.error(
                    "事实计算器 %s 执行失败 (security=%s)",
                    computer.name,
                    profile.security_id.qualified_code,
                    exc_info=True,
                )
                # 单个计算器失败不应阻塞整个管道

        return facts

    def _topological_order(self) -> list[FactComputer]:
        """Kahn 算法拓扑排序 — 保证依赖先于被依赖者执行。"""
        if self._sorted is not None:
            return self._sorted

        # 构建入度和邻接表
        in_degree: dict[str, int] = {
            name: 0 for name in self._computers
        }
        adjacency: dict[str, list[str]] = {
            name: [] for name in self._computers
        }

        for name, computer in self._computers.items():
            for dep in computer.dependencies:
                if dep not in self._computers:
                    logger.warning(
                        "计算器 %s 依赖 %s，但 %s 未注册",
                        name, dep, dep,
                    )
                    continue
                adjacency[dep].append(name)
                in_degree[name] += 1

        # BFS
        queue: deque[str] = deque(
            name for name, degree in in_degree.items() if degree == 0
        )
        result: list[FactComputer] = []

        while queue:
            name = queue.popleft()
            result.append(self._computers[name])
            for neighbor in adjacency[name]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(result) != len(self._computers):
            processed = {c.name for c in result}
            remaining = set(self._computers) - processed
            raise CircularDependencyError(
                f"事实计算器存在循环依赖: {remaining}"
            )

        self._sorted = result
        logger.debug(
            "事实计算器执行顺序: %s",
            [c.name for c in result],
        )
        return result

    @property
    def registered_names(self) -> list[str]:
        """已注册的计算器名称列表。"""
        return list(self._computers.keys())
