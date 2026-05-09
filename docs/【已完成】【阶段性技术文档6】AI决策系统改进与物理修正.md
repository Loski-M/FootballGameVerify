# 阶段性技术文档6：AI 决策系统改进与物理修正

> 日期：2026-05-09
> 范围：python_sim/ 全部修改（在文档5基础上的增量改动）

---

## 一、修改概览

本次共三轮修改，涉及 3 个文件，共约 12 处改动。

| 文件 | 本轮改动 | 新增/修改函数 |
|---|---|---|
| config.py | 替换 1 参数 + 新增 8 参数 | 9 参数 |
| models.py | MatchState 新增 2 字段 | 2 字段 |
| ai.py | 新增 2 函数 + 修改 4 函数 | ~120 行 |
| simulation.py | 修改 3 处 + 新增 1 辅助方法 + 6 处状态清除 | ~25 行 |

---

## 二、球物理模型：指数衰减 → 匀减速

### 2.1 改动原因

之前 `ball_friction = 0.92` 每 tick 乘以速度，球做指数衰减——永不真正停止，且速度衰减规律不直观。地面传球应近似匀减速运动。

### 2.2 修改内容

- **config.py** — `ball_friction: 0.92` 替换为 `ball_deceleration: float = 3.8`（m/s²）

  3.8 m/s² 意味着 10 m/s 的球约 2.6 秒停止，滑行约 13 米，符合五人制足球硬地球场。

- **simulation.py `_move_free_ball()`**（[simulation.py:209-218](python_sim/simulation.py#L209-L218)）：

```python
speed = math.hypot(match.ball.vx, match.ball.vy)
if speed > 0.0:
    decel = self.config.ball_deceleration * self.config.tick_seconds
    if speed <= decel:
        match.ball.vx = 0.0
        match.ball.vy = 0.0
    else:
        factor = (speed - decel) / speed
        match.ball.vx *= factor
        match.ball.vy *= factor
```

- **ai.py `predict_ball_path()`**（[ai.py:337-347](python_sim/ai.py#L337-L347)）：同步改为匀减速，用于拦截预判。

### 2.3 飞行时间公式修正

**simulation.py `_resolve_pass_target()`**（[simulation.py:570-575](python_sim/simulation.py#L570-L575)）：

飞行时间从 `dist / speed` 改为匀减速公式：

```
t = (v₀ - √(v₀² - 2ad)) / a
```

若 `dist ≥ v₀²/(2a)`（球无法抵达目标），取 `t = v₀/a`（停止时间）。

### 2.4 传球速度下限

**ai.py `choose_pass_speed()`**（[ai.py:284-285](python_sim/ai.py#L284-L285)）：增加物理可达性检查：

```python
min_reach_speed = math.sqrt(2.0 * config.ball_deceleration * dist * 1.05)
return clamp(speed, max(config.pass_speed_min, min_reach_speed), max_speed)
```

确保传球的初速足以在减速停止前抵达目标。

### 2.5 球员预判精度

**config.py** — 新增 `lead_prediction_quality_factor: float = 0.5`

**simulation.py `_resolve_pass_target()`**（[simulation.py:578-580](python_sim/simulation.py#L578-L580)）：传球者的 `attack_awareness` 影响提前量计算精度：

```python
pred_quality = owner.attrs.attack_awareness / 100.0
receiver_factor = lead_time_receiver_speed_factor * (0.5 + pred_quality * lead_prediction_quality_factor)
```

| attack_awareness | 接球人速度因子利用率 |
|---|---|
| 80 | ~90% |
| 50 | ~75% |
| 30 | ~65% |

低意识球员的 lead_pass 偏保守（偏近），球更容易传到接球人身后。

---

## 三、AI 决策系统改进

### 3.1 噪声分析

**问题**：将 `rng.uniform(-0.3, 0.3)` 改为 `rng.uniform(-0.1, 0.1)` 后比赛完全不变。

**根因**（[ai.py:203-207](python_sim/ai.py#L203-L207)）：动作评分差距在结构上远超噪声幅度。

| 动作 | 典型得分 | 关键项 |
|---|---|---|
| PASS | 2.5–4.5 | forward_value×0.3 ≈ 2.4 |
| DRIBBLE | 0.5–2.5 | ball_control/35 ≈ 2.0 |
| SHOOT（远距离） | -5.0 | 直接返回 |

PASS 比 DRIBBLE 高 1–3 分，±0.3 噪声无法弥合。噪声只在极端边缘情况生效——修复方法是让 dribble 和 off-ball 目标选择本身更智能。

### 3.2 带球找空当

**新增 `choose_dribble_target()`**（[ai.py:165](python_sim/ai.py#L165)）：

替代原有的"只往前走"逻辑。在球员前方弧内采样候选位置（3 距离 × N 角度），按以下因素评分：

- 向前推进量 × 偏置
- 离最近防守人距离 × 避让权重
- 边线惩罚
- 距当前位置距离惩罚
- 队友拥挤度

**射程内特殊行为**（[ai.py:178-183](python_sim/ai.py#L178-L183)）：当 `dist_to_goal < shot_range` 时，渐进式切换为进攻模式：

- 搜索角度从 150° 缩窄到 30°（最靠近球门时）
- 防守人避让权重线性衰减至 0
- 向前偏置增加至最多 4 倍

这解决了"单刀球前锋躲门将"的问题——前锋在接近球门时会直冲而非绕开。

### 3.3 无球跑位找空当

**新增 `_find_open_support_position()`**（[ai.py:436](python_sim/ai.py#L436)）：

替代原有的 7 固定偏移量搜索（`structured_target()` 中）。在角色基准位置周围全向采样候选点（3 距离 × N 角度），按以下因素评分：

- 防守压力（离最近防守人距离）× `open_space_defender_weight`（3.0）
- 传球线路质量（球→候选点连线离防守人的距离）× `support_lane_weight`（1.5）
- 向前推进
- 队友间距
- 边线避让

保留角色基准位置作为搜索中心，确保球队阵型不散。

### 3.4 防守盯人/拦截

**修改 `defending_target()`**（[ai.py:588](python_sim/ai.py#L588)）：

非压迫防守球员（非 GK、非最近 1-2 名压迫者）：

1. 识别最危险对方球员：`forward_pos×1.5 + (PIVOT加2.0) + 距球近加分`
2. 站位在持球人与该对手连线的 `mark_intercept_ratio`（40%）处——即拦截传球线路
3. 若没有明确危险目标，回退到防守基准位置

GK 和压迫球员的行为不变。

---

## 四、传球人/接球人状态

### 4.1 新增状态字段

**models.py `MatchState`**（[models.py:219-220](python_sim/models.py#L219-L220)）：

```python
passer_player_id: Optional[str] = None
receiver_player_id: Optional[str] = None
```

### 4.2 状态生命周期

- **设置**：[simulation.py:147-148](python_sim/simulation.py#L147-L148) — `_execute_pass()` 传球执行时
- **清除**：在以下时机通过 `_clear_pass_intent()` 清除：
  - `_resolve_loose_ball()` — 任何人控球
  - `_maybe_tackle_owner()` — 抢断成功
  - `_try_goalkeeper_save()` — 门将扑救
  - `_handle_goal()` — 进球
  - `_setup_restart()` — 死球重新开始（覆盖边线球/角球/球门球）

### 4.3 AI 行为变更

**修改 `decide_off_ball()`**（[ai.py:299-325](python_sim/ai.py#L299-L325)）：球飞行时根据角色区分行为：

| 角色 | 行为 |
|---|---|
| 接球人（`receiver_player_id`） | 全力迎球，使用拦截预判逻辑 |
| 同队非接球人（`passer_player_id` 存在且同队） | 专注跑位支援，**不拦截**自家传球 |
| 防守方 | 照常尝试拦截 |

效果：传球期间非接球队友不再跑向球试图截获——他们继续跑位拉开空间。

---

## 五、涉及的配置参数总览

以下是本轮新增的全部参数（均在 [config.py](python_sim/config.py) 中）：

```python
# 球物理
ball_deceleration: float = 3.8           # 匀减速度 (m/s²)，替代 ball_friction
lead_prediction_quality_factor: float = 0.5  # attack_awareness 对提前量精度的影响

# 开放空间搜索
open_space_radius: float = 5.0           # 搜索半径
open_space_samples: int = 14             # 采样数量
open_space_defender_weight: float = 3.0  # 防守人避让权重

# 带球
dribble_forward_bias: float = 1.5        # 向前偏置

# 无球跑位
support_lane_weight: float = 1.5         # 传球线路质量权重

# 防守
mark_intercept_ratio: float = 0.4        # 盯人站位比例 (0=球侧, 1=对手侧)
```

---

## 六、验证结果

多 seed（7, 13, 42, 99）测试通过：

| 指标 | 结果 |
|---|---|
| 模拟稳定性 | 4/4 seed 无报错 |
| 传球完成率 | 43%–71%（较文档5 的 60–95% 下降，因防守盯人/拦截更积极） |
| 射门数 | 4–19 次/队（较之前 ~7 次明显增加，进攻更活跃） |
| 传球类型分布 | TO_FEET / LEAD_PASS / THROUGH_PASS 三种均有 |
| 死球后第一动作 | 始终为 PASS |
| 前锋单刀行为 | 射程内直冲球门，不再绕开门将 |
| 队友拦截自家传球 | 无主动拦截案例（物理边界的偶发碰球除外） |
| 带球左右变向 | 出现（在防守压力下横向移动找空当） |
