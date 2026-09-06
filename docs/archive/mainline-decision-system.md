# Mainline Decision System

## Product Definition

The project is an A-share mainline decision system.

It answers four user questions:

1. What is the market trading now?
2. Which sector/concept evidence supports that direction?
3. Which stocks are participation points, risk validations, or low-level repair candidates?
4. What should the user do next: follow, wait for pullback, defend, reduce exposure, or observe?

Scanning is an internal validation capability. It is not the product goal.

## Core Principle

Mainline = market-traded business narrative.

A mainline is not the same as a raw concept name. A raw concept such as CPO, liquid cooling, or storage chips can be evidence inside a larger mainline such as AI compute chain.

The system should preserve raw data names, but the user-facing mainline name should be a higher-level synthesized theme when enough evidence exists.

## Layered Architecture

### 1. Stock Profile Layer

Purpose: explain what a stock actually does and why the market may trade it under a theme.

Target relation shape:

```text
stock_code
name
relation_name
relation_kind: industry | concept | business | event | manual | derived
relation_type: core_business | market_tag | event_driven | weak_association | expired_watch
source
confidence
effective_date
last_verified_date
evidence
```

Examples:

- core_business: company revenue or products are directly related.
- market_tag: THS/Eastmoney or market pages classify it under a concept.
- event_driven: new order, acquisition, policy, cooperation, investor interaction.
- weak_association: participation, small layout, indirect exposure.
- expired_watch: previously related, but evidence is stale.

### 2. Concept Graph Layer

Purpose: connect different concepts into a tradable mainline.

Target relation shape:

```text
source_node
target_node
relation_type: upstream | downstream | same_theme | member_overlap | market_sync | event_sync
source
confidence
effective_date
last_verified_date
evidence
```

Relation meanings:

- upstream/downstream:产业链上下游。
- same_theme:同一市场叙事。
- member_overlap:成分股高度重叠。
- market_sync:行情启动、分歧、回流节奏同步。
- event_sync:同一政策、公告、新闻或产业事件驱动。

### 3. Mainline Engine Layer

Purpose: identify and stage market mainlines.

Input evidence:

- board/concept market strength
- real breadth from constituent histories
- 5/20-day market returns
- active days and persistence
- representative stocks
- concept graph relations
- stock-profile evidence
- candidate validation from opportunity/risk/bottom-divergence pools

Mainline outputs:

```text
mainline_id
mainline_name
raw_name
display_name
target_board_type
target_name
stage
lifecycle_label
participation_mode
participation_label
primary_pool
risk_action
evidence_boards
evidence_concepts
representative_stocks
defensive_branches
confidence
quality_score
quality_label
quality_reasons
```

The display name is allowed to be synthesized, but filtering and drill-down must use `target_board_type` + `target_name`. This prevents a narrative name such as AI算力链 from being accidentally used as a raw THS concept filter.

### 4. Trading Decision Layer

Purpose: translate a mainline into an action.

Decision roles:

- mainline participation point: opportunity candidate aligned with the mainline.
- mainline risk validation: risk candidate inside or adjacent to the mainline.
- low-level repair: bottom-divergence candidate that can become a defensive branch.
- branch candidate: strong stock outside the current primary mainline.
- watch candidate: not aligned enough for priority tracking.

Decision modes:

- trend_follow: mainline confirmed, follow with chart confirmation.
- pullback_confirm: strong line with divergence, only accept pullback/re-strength confirmation.
- right_side_watch: developing line, wait for continuity.
- risk_control: risk is expanding, reduce participation.
- defensive_rotation: line is rotating, prefer low-risk repaired branches.
- observe: evidence is insufficient.

## Mainline Naming Direction

Current state:

- Raw sector/concept names are preserved as evidence and drill-down targets.
- User-facing names can now be separated through `display_name`.
- Initial clustering is deterministic and conservative; it is a bridge until the concept graph is mature.

Target state:

1. Keep raw sector/concept names as evidence.
2. Group related concepts and sectors through the concept graph.
3. Name the group by the dominant market narrative.
   - Generic sector names should yield to stronger child concepts or narrative rules.
   - Weak/event concepts should not become user-facing mainline names.
   - Narrative naming may normalize raw labels such as `芯片概念 -> 半导体国产替代`.
4. Show the raw concepts below the synthesized name.

Example:

```text
AI算力链
  concepts: CPO / 液冷服务器 / 算力租赁 / 存储芯片 / 数据中心
  sectors: 通信设备 / 计算机设备 / 半导体
  representatives: 中军 / 弹性 / 补涨 / 风险验证
```

## UI Direction

Default path:

```text
今日主线
  -> 主线拆解
  -> 候选股票
  -> 单股研判
```

Rules:

- The first screen should not be a scan result list.
- Concepts and sectors should explain a mainline, not compete with it.
- Candidate pools should be shown as participation roles.
- Refresh/rescan/governance belongs to Data & Jobs.
- Single-stock charts are confirmation, not the first product layer.

## Near-Term Implementation Order

1. Documentation and product language alignment. Done.
2. Stock profile relation contract. Done as `profile_relations.v1` for cached industry/concept evidence.
3. Concept graph relation contract. Defined; implementation remains staged.
4. Mainline quality and naming fields. Done as deterministic backend output.
5. Mainline breakdown page. Done: selected mainline, formation evidence, risk profile, composition map, representative opportunity/risk/repair stocks.
6. Candidate role and decision queue rendering based on selected mainline. Done.
7. Event/business evidence enrichment. Next.
8. Optional AI summarization only after structured evidence exists.

## AI Assistance Position

AI can help summarize business evidence, normalize event text, and propose mainline names.

AI should not be the first source of truth. The system should first collect structured evidence, then optionally ask AI to summarize:

- why a stock belongs to a mainline
- why concepts are connected
- what the current risk is
- which participation script fits

Guardrails:

- AI input must be structured evidence produced by providers, graph relations, candidate pools, replay statistics, and profile relations.
- AI output is explanation text, naming suggestions, or event normalization; it must not directly create buy/sell/risk decisions.
- Every AI summary should keep evidence ids or source labels so the UI can show why the sentence exists.
- If structured evidence is incomplete, the UI should say evidence is missing rather than asking AI to fill the gap.
