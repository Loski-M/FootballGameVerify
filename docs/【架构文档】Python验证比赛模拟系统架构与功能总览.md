# Python 验证比赛模拟系统：架构与功能总览

> 日期：2026-05-10
> 基于：7 轮阶段性技术迭代（文档1–7）的最终状态

---

## 一、项目定位与目标

这是一个 **Python 2D 五人制足球比赛模拟验证系统**，目标是：
- 验证球员 AI 建模是否成立
- 验证球权状态机是否能驱动出足球比赛过程
- 验证持球/无球/防守决策是否能形成稳定节奏
- 为后续 Godot 正式游戏提供可迁移的 AI 内核

它**不是**正式游戏——没有动画、没有玩家操作、没有 3D。它是纯逻辑内核。

---

## 二、代码文件结构

```
FootballGameVerify/
├── python_sim/                    # 核心模拟库
│   ├── __init__.py
│   ├── config.py                  # 可调参数（55 个参数）
│   ├── models.py                  # 数据模型（dataclass 定义）
│   ├── ai.py                      # AI 决策系统（~880 行）
│   ├── simulation.py              # 模拟引擎（~790 行）
│   ├── sample_data.py             # 样本比赛数据构建
│   ├── reporting.py               # 文本比赛报告
│   └── visualizer.py              # Tkinter 2D 可视化回放
├── run_match.py                   # 单场模拟入口
├── visualize_match.py             # 可视化回放入口
└── docs/                          # 设计文档与技术文档
    ├── 【模拟器总体方案】Python验证比赛模拟系统架构与实现思路.md
    ├── 【架构文档】Python验证比赛模拟系统架构与功能总览.md  (本文档)
    ├── 【分析文档】当前问题与未来改进方向.md
    ├── 【已完成】【阶段性技术文档1–7】*.md  (7 份迭代文档)
    └── 其他方案/预研文档
```

---

## 三、核心架构

### 3.1 tick 引擎（三层循环）

```
┌─ tick (0.2s) ───────────────────────────────────────┐
│ 1. update_team_phase()     → 更新两队战术阶段       │
│ 2. decide_all_players()    → 所有 10 名球员 AI 决策 │
│ 3. [dead_ball]             → 死球处理               │
│    [live]                  → 动作执行 + 无球移动     │
│                              + 自由球物理 + 球权判定 │
│ 4. _update_facing()        → 球员朝向更新           │
│ 5. _apply_separation()     → 队友分离（防扎堆）     │
│ 6. _update_stamina()       → 体力更新               │
│ 7. _update_possession_stats() → 控球统计            │
│ 8. _record_frame()         → 帧快照保存             │
└─────────────────────────────────────────────────────┘
```

### 3.2 球权状态机

```
      ┌────────────────────────────────┐
      │         DEAD BALL              │
      │  (开球/边线球/角球/球门球)      │
      └──────────┬─────────────────────┘
                 │ restart settled
                 ▼
      ┌────────────────────────────────┐
      │       PLAYER POSSESSION        │
      │  ├─ DRIBBLE → 球跟随球员       │
      │  ├─ PASS   → 球发射 (free)     │
      │  └─ SHOOT  → 球发射 (free)     │
      └──────┬─────────┬───────────────┘
             │         │
      tackle│         │ pass/shoot executed
             ▼         ▼
      ┌────────────────────────────────┐
      │       FREE BALL                │
      │  ├─ 匀速移动 + 匀减速          │
      │  ├─ GK 扑救检测                │
      │  ├─ 进球检测(含门柱/横梁)      │
      │  └─ 边界出界检测               │
      └──────┬─────────────────────────┘
             │
             ▼
      ┌────────────────────────────────┐
      │    LOOSE BALL RESOLUTION       │
      │  ├─ 最近球员 → 控球            │
      │  └─ 无人 → 继续 free           │
      └────────────────────────────────┘
```

### 3.3 AI 决策分层

```
decide_all_players()
├─ owner?  → decide_ball_owner()    持球人决策
│   ├─ GK? → 直接传球
│   ├─ restart? → 强制传球
│   ├─ score_shot()      → SHOOT 评分
│   ├─ score_best_pass()  → PASS 评分 + 接球人射门机会
│   ├─ score_dribble()    → DRIBBLE 评分
│   ├─ +噪声 → max 选择
│   └─ choose_dribble_target() / choose_pass_type() / choose_pass_speed()
│
├─ off-ball → decide_off_ball()     无球人决策
│   ├─ 球飞行中 + 我是接球人 → 迎球
│   ├─ 球飞行中 + 同队非接球人 → 支援跑位
│   ├─ 球飞行中 + 对手传球 → 尝试拦截
│   ├─ 己方控球 → structured_target() + _find_open_support_position()
│   └─ 对方控球 → defending_target()
│       ├─ GK → 随球角度封堵
│       ├─ 压迫者(1-2人) → 直接上抢
│       └─ 非压迫者 → 盯人/拦截线路 + 深度约束 + 反击回撤
│
└─ dead_ball → decide_restart_position()  死球站位
```

---

## 四、已实现功能清单

### 4.1 物理引擎
| 功能 | 实现方式 | 关键参数 |
|---|---|---|
| 球的匀减速运动 | 每 tick 速度减去 `deceleration × dt`，速度≤0 时停止 | `ball_deceleration = 3.8 m/s²` |
| 球员有限移动 | 基于 move_speed × stamina × dt 的步长限制 | move_speed 由 speed + acceleration 派生 |
| 朝向旋转 | 每 tick 最大旋转 = turn_rate × dt | turn_rate 由 acceleration + dribbling 派生 |
| 传球飞行时间 | 匀减速公式：t = (v₀ − √(v₀² − 2ad)) / a | — |
| 队友分离 | 距离 < 2×radius 时互相排斥 | — |

### 4.2 传球系统
| 功能 | 实现方式 |
|---|---|
| 三种传球类型 | TO_FEET（传到脚下）、LEAD_PASS（提前量）、THROUGH_PASS（直塞） |
| 可变球速 | 基于距离（+0.4m/s per m）、类型加成、防守压力、球员能力的动态球速 |
| 物理可达性 | 球速不低于 `√(2×a×d×1.05)`，确保球能到达目标 |
| 动态提前量 | lead_time = min + flight_time × 0.85 + receiver_speed × factor + through_extra |
| 传球人意识影响 | attack_awareness 影响提前量精度（高意识 = 精确 lead，低意识 = 保守偏近） |
| 高斯误差模型 | Box-Muller 变换，多因素误差标准差（基础/质量/距离/速度/朝向） |
| 近距离质量保护 | 8m 内传球，能力因子按比例折扣（3m 时仅 37.5%） |
| 短传类型强制 | ≤6m 自动 TO_FEET，避免短距离 LEAD 的额外误差 |
| 传球线路封堵 | 点→线段距离扫描，防守人在线路上时施加惩罚 |
| 落点防守避让 | 9 候选偏移采样，选防守压力最小的点 |
| 传球人/接球人追踪 | passer_player_id / receiver_player_id 生命周期管理 |

### 4.3 射门系统
| 功能 | 实现方式 |
|---|---|
| GK 感知瞄准 | 实时获取 GK 位置，打 GK 不在的一侧；GK 居中时回退远角逻辑 |
| 可变射门球速 | 基于 shooting 能力：`shot_speed × (0.75 + 0.25 × ability)` |
| 多因素误差 | 球速难度 + 距离因子 + GK 站位角度——三者加权 |
| 射门目标选择 | 射门角度评分权重 2.8，近距离奖励与角度联动 |

### 4.4 扑救系统
| 功能 | 实现方式 |
|---|---|
| 球线投影预判 | `_project_ball_to_goal_line()`：投影球到球门线的 crossing_y |
| 反应时间模型 | 基于 crossing time 的 GK 站位预判 |
| 角度难度 | `abs(cross_y - keeper_y) / gk_reach` |
| 球速影响 | 球速越快 angle_difficulty 权重越大 |
| 扑救下限 | 5%（消除弱 GK 的不合理扑救率） |
| 扑救上限 | 85%（即使完美 GK 也不可能扑出所有球） |

### 4.5 门柱/横梁系统
| 功能 | 实现方式 |
|---|---|
| 门柱判定 | y 距 goal_min/goal_max ≤ 0.3m 时 20% 概率击中 |
| 横梁判定 | 10% 概率（模拟 3D 高度） |
| 反弹速度 | 原速 × [0.7, 0.9] |
| 反弹角度 | 入射角镜像 + 随机偏移（门柱 ±0.35rad，横梁 ±0.6rad） |
| 后续处理 | 反弹球变为自由球，产生补射机会 |

### 4.6 带球系统
| 功能 | 实现方式 |
|---|---|
| 开放空间采样 | 前方弧形区域 3 距离 × N 角度采样 |
| 防守避让 | 距最近出线防守人距离 × open_space_defender_weight（GK 排除） |
| 射程内特殊行为 | 搜索角 150°→30°、防守避让权重衰减至 0、前向偏置增至 4× |
| 底线硬惩罚 | 距球门 < 2m 返回 -10，强制传球或射门 |
| 边线惩罚联动 | 越靠近球门，边线惩罚越重 |
| 中心偏向 | 禁区附近偏边路时，向中路移动获额外奖励 |
| 队友拥挤 | 候选位置有队友时轻微扣分 |

### 4.7 无球跑位系统
| 功能 | 实现方式 |
|---|---|
| 开放空间支援站位 | 角色基准位置周围全向采样，综合防守压力 + 传球线路质量评分 |
| 角色区分 | 传球期间：接球人迎球、同队非接球人支援、对手拦截 |
| 接球模式 | COME_SHORT / MEET_BALL / RUN_ONTO 三种 |
| 队友分离 | 距最近队友 < 3m 时反向移动 |
| 拦截预判 | 14 步球轨迹预测，计算到达时间与球到达时间的最优匹配 |

### 4.8 防守系统
| 功能 | 实现方式 |
|---|---|
| 分层防守 | 压迫者（1-2 人）上抢 + 非压迫者盯人/拦截 |
| 压迫者选择 | 按距持球人距离排序，HIGH_PRESS 时 2 人、否则 1 人 |
| GK 站位 | 沿球→球门角度偏移（`out_dist = min(2.5, dist_to_ball × 0.25)`），封堵近角 |
| GK 出击判断 | 仅当距球距离 < 最近对手距离 − 0.5m 时才出击 |
| 盯人拦截 | 站位在持球人与危险目标连线的 40% 处 |
| 危险度评估 | forward_pos × 1.5 + PIVOT_bonus(2.0) − 距球距离 × 0.08 |
| 深度约束 | 非压迫球员不超过场地 62%（距己方底线 24.8m） |
| ANCHOR 最后防线 | 始终比最靠前对手靠后 2m |
| 反击检测 | 球在本方半场 + 对方球员越线 → 触发回追 |
| 拦截点锁定 | 锁定 0.4–1.0s，避免频繁切换目标 |
| 抢断 | press_quality × stamina + 随机 vs ball_control × stamina + 6 |

### 4.9 死球与重新开始
| 功能 | 实现方式 |
|---|---|
| 边线球 | y 出界 → 对方最后触球方发球，最近球员为发球人 |
| 球门球/角球 | x 出界 + y 在/不在球门范围 → 防守方球门球 / 进攻方角球 |
| 开球 | 进球后双方传送回防守 home position，球放中场 |
| 强制传球 | 所有重新开始后第一动作强制为 PASS |
| 发球冷却 | 开球 10s、其他 5s 决策冷却 |

### 4.10 体力系统
| 功能 | 实现方式 |
|---|---|
| 高强度消耗 | PRESS/DRIBBLE/SHOOT 时 +20% 消耗 |
| 低强度恢复 | 非高强度 + 非控球队 → 缓慢恢复 |
| 体力下限 | 55%（不会无限下降） |

### 4.11 战术与角色
| 功能 | 实现方式 |
|---|---|
| 队伍阶段 | POSSESSION_BUILD_UP / POSSESSION_ATTACK / DEFENSIVE_SHAPE / HIGH_PRESS / RESTART |
| 阶段判定 | 控球队：刚获球(POSSESSION_BUILD_UP) → 2s后(POSSESSION_ATTACK)；非控球队：pressure > 0.18 + 球在前场 → HIGH_PRESS，否则 DEFENSIVE_SHAPE |
| 角色系统 | GK / ANCHOR / LEFT / RIGHT / PIVOT 五角色 |
| 左右方向修正 | `_role_flank_sign()` 基于 attack_direction 自适应 |
| 攻防基准位置 | `role_home_position(attacking=True/False)` |
| 队伍风格 | Control（低压）/ Direct（高压） |

### 4.12 可视化与报告
| 功能 | 实现方式 |
|---|---|
| Tkinter 2D 回放 | 场地绘制、球员图标、球轨迹、事件显示、逐帧播放/自动播放 |
| 文本报告 | 比分、射门/传球/抢断统计、控球时间、事件日志 |

---

## 五、数据模型总览

### 5.1 核心枚举
```
Role          : GK | ANCHOR | LEFT | RIGHT | PIVOT
TeamPhase     : POSSESSION_BUILD_UP | POSSESSION_ATTACK | DEFENSIVE_SHAPE | HIGH_PRESS | RESTART
PlayerAction  : IDLE | SUPPORT | SPREAD | PRESS | RECOVER | DRIBBLE | PASS | SHOOT
PassType      : TO_FEET | LEAD_PASS | THROUGH_PASS
ReceiveMode   : NONE | COME_SHORT | MEET_BALL | RUN_ONTO
```

### 5.2 核心数据结构
```
PlayerAttributes   → 9 项基础能力值
PlayerDerived      → 8 项派生属性
PlayerState        → 位置/速度/朝向/体力/决策冷却/接球模式/拦截锁定
Intent             → 动作类型 + 目标坐标 + 目标球员 + 传球类型 + 球速
Player             → id + name + team_id + role + attrs + derived + state
TeamTactics        → style + base_pressure
TeamState          → phase + possession_time + last_gain_time
Team               → id + name + attack_direction + tactics + state + players
BallState          → 位置/速度/控球队/控球人/最后触球队/最后触球人/最后动作
MatchState         → teams + ball + time + events + stats + frames + dead_ball + restart_*
FrameSnapshot      → 逐帧完整状态快照
```

### 5.3 派生属性公式
```
move_speed      = 2.8 + speed × 0.035 + acceleration × 0.01
ball_control    = dribbling × 0.65 + attack_awareness × 0.35
pass_quality    = passing × 0.70 + attack_awareness × 0.30
shot_quality    = shooting × 0.75 + attack_awareness × 0.25
press_quality   = defence_awareness × 0.65 + acceleration × 0.35
recover_quality = defence_awareness × 0.55 + speed × 0.45
save_quality    = goalkeeping
turn_rate       = 1.8 + acceleration × 0.01 + dribbling × 0.004
```

---

## 六、配置参数总览（55 个参数）

### 场地与时间
```
pitch_width=40.0, pitch_height=24.0, goal_width=6.0
tick_seconds=0.2, match_duration_seconds=180.0, decision_interval_seconds=0.4
```

### 球员物理
```
player_radius=0.6, ball_control_radius=1.0
possession_radius=1.2, tackle_radius=1.2, press_radius=4.5, shot_block_radius=1.2
```

### 球物理
```
pass_speed=12.0, shot_speed=18.0, ball_deceleration=3.8
```

### 传球系统（17 参数）
```
pass_speed_min=5.5, pass_speed_max=17.0, pass_speed_distance_per_m=0.4
pass_speed_type_through_bonus=2.0, pass_speed_type_lead_bonus=1.0, pass_speed_pressure_malus=2.5
lead_time_min=0.25, lead_time_flight_fraction=0.85, lead_time_receiver_speed_factor=0.06
lead_time_through_extra=0.4, lead_defender_nudge_radius=2.8, lead_defender_nudge_strength=1.2
pass_error_base=0.12, pass_error_quality_factor=0.85, pass_error_distance_per_m=0.014
pass_error_speed_factor=0.03, pass_error_facing_factor=0.4
lead_prediction_quality_factor=0.5
```

### 跑位与防守（7 参数）
```
open_space_radius=5.0, open_space_samples=14
open_space_defender_weight=3.0, support_lane_weight=1.5
dribble_forward_bias=1.5, mark_intercept_ratio=0.4
dribble_push=1.1, support_distance=8.0, shot_range=13.0
```

### 体力
```
fatigue_decay_per_second=0.015, recovery_decay_per_second=0.006
```

---

## 七、已验证指标（15 seed 汇总）

| 指标 | 典型数值 |
|---|---|
| 场均射门 | 5–19 次/队 |
| 射门转化率 | ~18% |
| 射正率 | ~26% |
| 传球完成率 | 74–88% |
| 门柱击中/场 | ~0.2 次 |
| 横梁击中/场 | ~0.27 次 |
| 模拟稳定性 | 100%（所有 seed 无报错） |
| 传球类型分布 | TO_FEET/LEAD_PASS/THROUGH_PASS 三种均有 |
| 死球后第一动作 | 始终为 PASS |
| 前锋单刀行为 | 直冲球门或传空位队友 |
| 门前回传（cutback） | 出现 |

---

## 八、下一步考虑方向

### 剩余问题（来自分析文档）

1. **防线整体性**：防守球员的纵向位置应参考最靠后队友的位置，避免防线脱节。当前每个球员独立计算深度约束。
2. **射程内目标偏向曲线**：将线性过渡改为指数过渡（`goal_proximity²`），让靠近球门时更激进地直冲。
3. **禁区边线惩罚联动**：射程内边线惩罚应与距球门距离联动——当前已实现，可进一步调参。

### 可探索的新方向

4. **犯规与定位球**：加入拉人/铲球犯规判定，任意球/点球机制。
5. **越位规则**：加入 offside line 判定（需考虑这是五人制还是十一人制足球的越位规则）。
6. **阵容多样化**：允许不同的角色分配（如 2-1-1、1-2-1 等）。
7. **参数自动调优**：使用进化策略或贝叶斯优化，自动化 55 个参数的调优。
8. **ML/RL 引入**：在启发式 AI 框架内嵌入轻量级策略网络，替代部分评分函数。

### 架构性工作

9. **Godot 迁移准备**：将评分函数和状态机抽取为语言无关的配置/规则描述。
10. **批量模拟框架**：支持数百场模拟的参数扫描和数据收集。

---

## 九、技术文档索引

| 编号 | 文档 | 核心内容 |
|---|---|---|
| 1 | [阶段性技术文档1](【已完成】【阶段性技术文档1】Python验证版后续修改方案.md) | 初始修改方案 |
| 2 | [阶段性技术文档2](【已完成 】【阶段性技术文档2】Python验证版传接球与预判跑位改进方案.md) | 传接球与跑位 |
| 3 | [阶段性技术文档3](【已完成】【阶段性技术文档3】202605091135修改日志.md) | 修改日志 |
| 4 | [阶段性技术文档4](【阶段性技术文档4】Python验证比赛模拟系统目前的实现思路与已实现功能总结.md) | 中期功能总结 |
| 5 | [阶段性技术文档5](【已完成】【阶段性技术文档5】传球系统改进与细节修正.md) | 可变球速/动态提前量/高斯误差/死球修正/左右修正 |
| 6 | [阶段性技术文档6](【已完成】【阶段性技术文档6】AI决策系统改进与物理修正.md) | 匀减速球物理/带球找空当/无球跑位/防守盯人/传球人状态 |
| 7 | [阶段性技术文档7](【已完成】【阶段性技术文档7】射门扑救门柱与AI决策最终优化.md) | 射门GK瞄准/新扑救公式/门柱横梁/传球射门角度/近距离精度/防守深度 |
| — | [分析文档](【分析文档】当前问题与未来改进方向.md) | 问题分析与改进方向 |
| — | [架构文档](【架构文档】Python验证比赛模拟系统架构与功能总览.md) | 本文档 |
