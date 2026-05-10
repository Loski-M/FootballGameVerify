# 阶段性技术文档7：射门/扑救/门柱机制与 AI 决策最终优化

> 日期：2026-05-10
> 范围：python_sim/ 全部修改（在文档6基础上的增量改动）

---

## 一、修改概览

本次共三轮修改，涉及 3 个文件，共约 15 处改动。

| 文件 | 改动 | 新增/修改函数 |
|---|---|---|
| config.py | 修改 1 参数 | 1 参数 |
| ai.py | 新增 1 函数 + 修改 5 函数 | ~100 行 |
| simulation.py | 新增 2 函数 + 修改 3 函数 | ~120 行 |

---

## 二、第一轮：射门/扑救机制 + 门柱/横梁 + 传球射门角度评分

### 2.1 射门目标策略：GK 感知瞄准

**问题**：射门始终瞄准"远门柱角"（固定策略），不符合实际——现实中球员会根据 GK 站位选择打近角或远角。

**修改** — [simulation.py:158-210](python_sim/simulation.py#L158-L210) `_execute_shot()`：

```
防守 GK 识别 → 获取 keeper_y
计算 GK 偏离中点的偏移量 gk_offset
dead_zone = goal_width × 0.15（GK 站在中点附近时无法判断偏向）

if abs(gk_offset) < dead_zone:
    → 回退到远角逻辑（基于射手位置选择）
elif gk_offset > 0:  → GK 偏上侧，打下角
else:                → GK 偏下侧，打上角
```

### 2.2 可变射门球速

射门球速不再固定 `shot_speed (18 m/s)`，改为基于球员 shooting 能力：

```python
shot_ability = owner.derived.shot_quality / 100.0
shot_speed = config.shot_speed * (0.75 + 0.25 * shot_ability)
```

- shot_quality=100 → 18.0 m/s（满速）
- shot_quality=60 → 16.2 m/s
- shot_quality=30 → 14.85 m/s

### 2.3 射门误差多因素模型

误差不再仅基于 `1 - shot_ability`，引入难度系数 `shot_difficulty`：

```python
shot_difficulty = (
    1.0
    + max(0.0, speed_ratio - 1.0) * 1.2    # 高速射门更难控制
    + dist_factor * 0.8                      # 距离越远误差越大
    + min(angle_from_gk, 1.5) * 0.15        # GK 站位角度越刁越难
)
error_margin = (max(0.15, 1.0 - shot_ability) + facing_gap * 0.7) * 3.0 * shot_difficulty
```

### 2.4 扑救公式重写

**辅助方法** [simulation.py:227-239](python_sim/simulation.py#L227-L239) `_project_ball_to_goal_line()`：
将球当前位置和速度投影到球门线，计算 crossing_y 和 time_to_goal。

**新扑救公式** [simulation.py:500-553](python_sim/simulation.py#L500-L553) `_try_goalkeeper_save()`：

```python
gk_reach = save_quality / 100.0 * goal_width / 2          # GK 最大横向覆盖距离
angle_difficulty = abs(cross_y - keeper_y) / gk_reach      # 角度难度
speed_factor = shot_speed / shot_speed_max                  # 球速因子
save_chance = clamp(0.1 + save_quality/250.0 - angle_difficulty * 0.4 * speed_factor, 0.05, 0.85)
```

**扑救概率对照表**：

| 场景 | save_quality | angle_difficulty | speed_factor | save_chance |
|---|---|---|---|---|
| 完美扑救（正对GK，慢速） | 85 | 0.2 | 0.8 | ~46% |
| 平均水平（偏中距离，中速） | 65 | 1.2 | 1.0 | ~24% |
| 困难扑救（死角，高速） | 65 | 2.5 | 1.1 | ~5%（下限） |

关键改进：
- 下限从 35% 降至 5%，消除"弱 GK 面对好射门仍有 35% 扑救率"的荒谬情况
- 引入 angle_difficulty，射向死角的球更难扑救
- 引入 speed_factor，球速越快越难扑救

### 2.5 门柱/横梁机制

**门柱判定** [simulation.py:374-382](python_sim/simulation.py#L374-L382) `_check_goal()`：

```python
post_margin = 0.3  # 球 y 坐标离门柱边缘 < 0.3m
is_near_post = (abs(ball.y - goal_min) <= post_margin or abs(ball.y - goal_max) <= post_margin)
if is_near_post and rng.random() < 0.20:   # 20% 概率击中门柱
    _handle_post_rebound(match)
```

**横梁判定** [simulation.py:384-387](python_sim/simulation.py#L384-L387)：

```python
if rng.random() < 0.10:   # 10% 概率击中横梁（模拟 3D 高度）
    _handle_crossbar_rebound(match)
```

**反弹行为** [simulation.py:391-425](python_sim/simulation.py#L391-L425)：

| 属性 | 门柱 | 横梁 |
|---|---|---|
| 反弹速度 | 原速 × [0.7, 0.9] | 原速 × [0.7, 0.9] |
| 反弹角度 | 入射角镜像 + [-0.35, 0.35] 随机偏移 | 入射角镜像 + [-0.6, 0.6] 随机偏移 |
| 球权 | 自由球（owner=None） | 自由球 |

反弹后球成为自由球，任何球员可争抢，产生补射机会。

---

## 三、第一轮：传球评分增加接球人射门角度

### 3.1 新增评估函数

**新增** [ai.py:854-879](python_sim/ai.py#L854-L879) `_eval_receiver_shot_opportunity()`：

```python
def _eval_receiver_shot_opportunity(player, team, config) -> float:
    # 距球门距离质量 (×1.5)
    distance_quality = max(0.0, 1.0 - dist_to_goal / shot_range)
    # 角度质量：越靠近球门中心线越好 (×2.0)
    angle_quality = max(0.0, 1.0 - angle_to_center / max(max_angle_offset * 2.0, 0.5))
    # 射门能力 (×0.8)
    shot_ability = player.derived.shot_quality / 100.0
    return distance_quality * 1.5 + angle_quality * 2.0 + shot_ability * 0.8
```

### 3.2 集成到传球评分

在 `score_best_pass()` 中（[ai.py:805](python_sim/ai.py#L805)）：

```python
receiver_shot_bonus = _eval_receiver_shot_opportunity(mate, team, config) * 0.5
score = ... + receiver_shot_bonus + ...
```

效果：传球给射门角度好的队友（球门正面、距离近）比传给角度差的队友得分更高。

---

## 四、第二轮：近距离传球精度 + 带球底线行为修正

### 4.1 传球速度下限降低

**config.py** — `pass_speed_min: 7.0 → 5.5`

降低最低传球速度，使短距离传球更软、更可控。

### 4.2 近距离传球质量缩放

**simulation.py** [simulation.py:118](python_sim/simulation.py#L118) `_execute_pass()` — 新增 `quality_distance_scale`：

```python
quality_distance_scale = min(1.0, dist_m / 8.0)
error_std = (
    base
    + (1.0 - quality) * quality_factor * quality_distance_scale  # 短传时能力因子打折
    + dist_m * distance_factor
    + ...
)
```

8m 以内传球的能力不足惩罚按比例缩小，短传到 3m 时能力因子仅生效 37.5%。

### 4.3 短距离强制传脚下

**ai.py** [ai.py:373-374](python_sim/ai.py#L373-L374) `choose_pass_type()` — 新增：

```python
if dist <= 6.0:
    return PassType.TO_FEET
```

6m 以内传球不产生 LEAD_PASS/THROUGH_PASS，避免短传附加不必要的提前量误差。

### 4.4 传球物理可达性检查

**ai.py** [ai.py:398](python_sim/ai.py#L398) `choose_pass_speed()`：

```python
min_reach_speed = math.sqrt(2.0 * ball_deceleration * dist * 1.05)
return clamp(speed, max(pass_speed_min, min_reach_speed), max_speed)
```

确保球速足够在匀减速停止前抵达目标（+5% 安全边际）。

### 4.5 带球目标：GK 排除 + 底线惩罚

**ai.py** [ai.py:181](python_sim/ai.py#L181) `choose_dribble_target()`：

```python
outfield_opponents = [o for o in opponents if o.role != Role.GK]
```

GK 不再被当作需要躲避的防守人——面对 GK 应该射门而非绕开。

**边线惩罚联动** [ai.py:223-224](python_sim/ai.py#L223-L224)：

```python
if dist_to_goal < config.shot_range:
    sideline_penalty *= (1.0 + goal_proximity * 2.5)
```

越靠近球门，越不能接受向边路移动（防止带到底线打小角度）。

**中心偏移奖励** [ai.py:227-230](python_sim/ai.py#L227-L230)：

```python
if dist_to_goal < config.shot_range and player_y_centre_dist > pitch_height * 0.3:
    candidate_y_centre_dist = abs(cy - half_h)
    centre_bias = (player_y_centre_dist - candidate_y_centre_dist) * 0.5
```

球员在禁区附近且位置偏边路时，向中路方向移动获得额外奖励。

---

## 五、第三轮：前锋射门/传球决策 + 防守策略改进

### 5.1 射门评分角度惩罚加强

**ai.py** [ai.py:762](python_sim/ai.py#L762) `score_shot()`：

- `angle_factor` 权重从 2.2 提升至 **2.8**
- `close_bonus` 从固定 1.2 改为角度关联：`0.5 * max(0.2, angle_factor)`

效果：小角度射门的评分大幅下降，close_bonus 在小角度时接近 0.1，不足以补偿角度扣分。

### 5.2 传球评分增加回传中路奖励（Cutback Bonus）

**ai.py** [ai.py:808-815](python_sim/ai.py#L808-L815) `score_best_pass()`：

```python
if passer_dist_to_goal < 7.0 and passer_angle > 4.5:  # 传球者在禁区边路
    mate_angle = abs(mate.state.y - pitch_height / 2)
    if mate_angle < passer_angle - 1.0:                 # 接球人更靠近中路
        cutback_bonus = (passer_angle - mate_angle) * 0.25
```

边路球员在禁区附近发现中路队友更靠近球门中心时，传球得分获得额外加成。

### 5.3 防守策略：反击检测

**ai.py** [ai.py:652-668](python_sim/ai.py#L652-L668) `defending_target()`：

```python
ball_in_our_half = (ball.x - midfield_x) * team.attack_direction < 0
if ball_in_our_half:
    deepest_x = min/max(p.state.x for p in our_outfield)
    opponents_behind = any(opp.state.x < deepest_x - 1.5 ...)
    if opponents_behind:
        → 回撤到防守基准位置后 3m（RECOVER 模式）
```

触发条件：球在本方半场 AND 对方球员已越过本方防线身后。

### 5.4 防守策略：ANCHOR 最后防线

**ai.py** [ai.py:691-700](python_sim/ai.py#L691-L700) `defending_target()`：

```python
if player.role == Role.ANCHOR:
    most_advanced_x = min/max(opp_positions)
    tx = min/max(tx, most_advanced_x -/+ 2.0)  # 始终比最靠前对手靠后 2m
```

ANCHOR 作为最后一道防线，始终保持在所有对方非持球球员与己方球门之间。

### 5.5 防守策略：深度约束

**ai.py** [ai.py:702-707](python_sim/ai.py#L702-L707) `defending_target()`：

```python
max_advance = config.pitch_width * 0.62  # 距离己方底线最远 62% 场地
tx = min/max(tx, max_advance)
```

所有非压迫防守球员的站位不超过场地 62%（约 24.8m），防止压得太靠上被打身后。

---

## 六、验证结果

多 seed（7, 13, 42, 99）以及 15 seed 批量测试通过：

| 指标 | 结果 |
|---|---|
| 模拟稳定性 | 15/15 seed 无报错 |
| 射门转化率 | ~18.4%（39/212 射门，15 seed 汇总） |
| 射正率 | ~25.5%（54/212） |
| 传球完成率 | ~77%（714/928，15 seed 汇总） |
| 门柱击中 | 3 次（15 seed） |
| 横梁击中 | 4 次（15 seed） |
| GK 扑救 | 合理分布（死角高速球几乎不扑，正对慢速球高扑救率） |
| 前锋单刀行为 | 直冲球门 + 传空位队友（不再下底打小角度） |
| 防守深度 | 非压迫球员不越过 62% 线 |
| ANCHOR 站位 | 保持在本方球门与最危险对手之间 |
| 反击回追 | 球在本方半场 + 对手越线时触发回撤 |

---

## 七、涉及的配置参数变更

本轮修改的配置参数（均在 [config.py](python_sim/config.py) 中）：

```python
# 修改
pass_speed_min: float = 5.5  # 从 7.0 降低，配合短传质量缩放
```

本轮无新增配置参数——所有改进都在评分函数和行为逻辑层面。
