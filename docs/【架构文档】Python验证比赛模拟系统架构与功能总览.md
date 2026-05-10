# Python 验证比赛模拟系统：架构与功能总览

> 日期：2026-05-10
> 基于：8 轮阶段性技术迭代（文档1–8）的最终状态

---

## 一、项目定位

这是一个 **Python 2D 五人制足球比赛模拟验证系统**。目标：
- 验证球员 AI 分层决策是否成立
- 验证球权状态机是否能驱动出足球比赛过程
- 验证持球/无球/防守决策是否能形成稳定节奏
- 为后续 Godot 正式游戏提供可迁移的 AI 内核

它**不是**正式游戏——没有动画、玩家操作、3D 渲染。它是纯逻辑内核。

---

## 二、代码文件结构

```
FootballGameVerify/
├── python_sim/                    # 核心模拟库
│   ├── __init__.py
│   ├── config.py                  # 可调参数（46 个）
│   ├── models.py                  # 数据模型（dataclass 定义）
│   ├── ai.py                      # AI 决策系统（~950 行）
│   ├── simulation.py              # 模拟引擎（~820 行）
│   ├── sample_data.py             # 样本比赛数据构建
│   ├── reporting.py               # 文本比赛报告
│   └── visualizer.py              # Tkinter 2D 可视化回放
├── run_match.py                   # 单场模拟入口
├── visualize_match.py             # 可视化回放入口
└── docs/                          # 设计文档与技术文档
```

---

## 三、核心架构

### 3.1 tick 引擎

```
┌─ tick (0.2s) ───────────────────────────────────────┐
│ 1. update_team_phase()     → 更新两队战术阶段       │
│ 2. decide_all_players()    → 所有 10 名球员 AI 决策 │
│ 3. [dead_ball]             → 死球处理               │
│    [live]                  → 动作执行 + 无球移动     │
│                              + 自由球物理 + 球权判定 │
│ 4. _update_facing()        → 球员朝向更新           │
│ 5. _apply_separation()     → 队友物理分离           │
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
│   ├─ score_best_pass()  → PASS 评分
│   ├─ score_dribble()    → DRIBBLE 评分
│   ├─ +噪声 → max 选择
│   └─ choose_dribble_target() / choose_pass_type() / choose_pass_speed()
│
├─ off-ball → decide_off_ball()     无球人决策
│   ├─ 球飞行中 + 我是接球人 → 迎球
│   ├─ 球飞行中 + 同队非接球人 → 支援跑位（不拦截自家球）
│   ├─ 球飞行中 + 对手传球 → 尝试拦截
│   ├─ 己方控球 → structured_target() + _find_open_support_position()
│   └─ 对方控球 → defending_target()
│       ├─ GK → 角度封堵站位
│       ├─ 压迫者(1-2人) → 直接上抢
│       └─ 非压迫者 → 盯人/拦截 + 防线对齐 + 风格深度约束 + 反击回撤
│
└─ dead_ball → decide_restart_position()  死球站位
```

---

## 四、已实现功能清单

### 4.1 物理引擎
| 功能 | 实现方式 |
|---|---|
| 球的匀减速运动 | 每 tick 速度减 `deceleration × dt`，速度降至 ≤0 时停止 |
| 球员有限移动 | move_speed × stamina × dt 步长限制 |
| 朝向旋转 | 每 tick 最大旋转 = turn_rate × dt |
| 队友物理分离 | 距离 < player_radius × 2.2 时互相推开 |

### 4.2 传球系统
| 功能 | 实现方式 |
|---|---|
| 三种传球类型 | TO_FEET / LEAD_PASS / THROUGH_PASS |
| 可变球速 | 基于距离、类型加成、防守压力、球员能力的动态球速 |
| 物理可达性检查 | 球速不低于 `√(2a·d·1.05)` |
| 提前距离设计 | `desired_lead = base + receiver_speed × factor + through_extra`，先定提前距离再算球速 |
| 传球人意识影响 | attack_awareness 通过 `lead_prediction_quality_factor` 影响提前量精度 |
| 高斯误差模型 | Box-Muller 变换，多因素标准差（基础/质量/距离/速度/朝向） |
| 近距离质量保护 | 8m 内传球能力因子按比例折扣 |
| 短传类型强制 | ≤6m 自动 TO_FEET |
| 传球线路封堵检测 | 点→线段距离扫描，防守人在线路上施加惩罚 |
| 落点防守避让 | 9 候选偏移采样，选防守压力最小的点 |
| 传球人/接球人追踪 | passer_player_id / receiver_player_id 生命周期管理 |
| 中路推进奖励 | 传球从边路→中路的横向推进在评分中获得额外加分 |

### 4.3 射门系统
| 功能 | 实现方式 |
|---|---|
| GK 感知瞄准 | 获取 GK 位置，打 GK 不在的一侧；GK 居中时回退远角逻辑 |
| 可变射门球速 | `shot_speed × (0.75 + 0.25 × shot_ability)` |
| 多因素误差 | 球速难度 + 距离因子 + GK 站位角度 |

### 4.4 扑救系统
| 功能 | 实现方式 |
|---|---|
| 球线投影预判 | 投影球到球门线的 crossing_y 和到达时间 |
| 角度难度 | `abs(cross_y - keeper_y) / gk_reach` |
| 球速影响 | angle_difficulty 权重 × speed_factor |
| 扑救范围 | 5%–85%（下限防弱 GK 不合理扑救，上限防完美 GK 无敌） |

### 4.5 门柱/横梁
| 功能 | 实现方式 |
|---|---|
| 门柱判定 | y 距门柱 ≤ 0.3m 时 20% 概率 |
| 横梁判定 | 10% 概率（模拟 3D 高度） |
| 反弹 | 原速 × [0.7, 0.9]，入射角镜像 + 随机偏移，球变为自由球 |

### 4.6 带球系统
| 功能 | 实现方式 |
|---|---|
| 开放空间采样 | 前方弧形 3 距离 × N 角度采样 |
| 防守避让 | GK 排除，距出线防守人距离加权 |
| 射程内特殊行为 | 搜索角缩窄、防守避让权重衰减、前向偏置增加 |
| 底线硬惩罚 | 距球门 < 2m 返回 -10 |
| 边线惩罚联动 | 越靠近球门边线惩罚越重 |
| 中心偏向 | 禁区边路时向中路移动获奖励 |

### 4.7 无球跑位系统
| 功能 | 实现方式 |
|---|---|
| 开放空间支援站位 | 角色基准位置周围全向采样，综合防守压力 + 传球线路质量 |
| 传球期间角色区分 | 接球人迎球 / 同队非接球人支援跑位 / 防守方拦截 |
| 接球模式 | COME_SHORT / MEET_BALL / RUN_ONTO |
| 拦截预判 | 14 步球轨迹预测，匹配到达时间 |

### 4.8 防守系统
| 功能 | 实现方式 |
|---|---|
| 分层防守 | 压迫者（1-2 人）上抢 + 非压迫者盯人/拦截 |
| GK 站位 | 沿球→球门角度偏移封堵近角 |
| GK 出击 | 仅当距球 < 最近对手 − 0.5m 时出击 |
| 盯人拦截 | 站位在持球人与危险目标连线的 40% 处 |
| 危险度评估 | forward_pos × 1.5 + PIVOT_bonus(2.0) − 距球距离 × 0.08 |
| 深度约束 | 防线深度比率 × 场地宽（风格决定：Control=0.55，Direct=0.68） |
| 防线对齐 | 非压迫球员参考最靠后队友位置，纵向差距 > 8m 时回拉 |
| ANCHOR 最后防线 | 始终比最靠前对手靠后 2m |
| 反击检测 | 球在本方半场 + 对方越线 → 触发回撤 |
| 抢断 | press_quality × stamina + 随机 vs ball_control × stamina + 6 |

### 4.9 球队整体性
| 功能 | 实现方式 |
|---|---|
| 防线对齐 | 所有非压迫球员的站位不超过 `deepest_x + gap_max` |
| 进攻层次保持 | PIVOT 与 ANCHOR 纵向距离 ≤ 12m |
| 弱侧收拢 | 球在异侧时边路球员收窄至 4m 宽度 |
| 战术风格差异化 | Control：防线深(0.55)、进攻宽(7.5m)；Direct：防线高(0.68)、进攻窄(6.0m) |

### 4.10 死球与重新开始
| 功能 | 实现方式 |
|---|---|
| 边线球 | y 出界 → 对方发球 |
| 球门球/角球 | x 出界 + y 判定 → 防守方球门球 / 进攻方角球 |
| 开球 | 进球后双方传送回防守 home position |
| 强制传球 | 重新开始后第一动作强制为 PASS |
| 发球冷却 | 开球 10s，其他 5s |

### 4.11 体力系统
| 功能 | 实现方式 |
|---|---|
| 高强度消耗 | PRESS/DRIBBLE/SHOOT 时 +20% |
| 低强度恢复 | 非高强度 + 非控球队时缓慢恢复 |
| 体力范围 | 55%–100% |

### 4.12 战术与角色
| 功能 | 实现方式 |
|---|---|
| 队伍阶段 | POSSESSION_BUILD_UP / POSSESSION_ATTACK / DEFENSIVE_SHAPE / HIGH_PRESS / RESTART |
| 阶段判定 | 刚获球 2s→BUILD_UP，之后→ATTACK；非控球 pressure>0.18+球在前场→HIGH_PRESS |
| 角色系统 | GK / ANCHOR / LEFT / RIGHT / PIVOT |
| 左右方向修正 | `_role_flank_sign()` 基于 attack_direction 自适应 |
| 攻防基准位置 | `role_home_position(attacking=True/False)` |

### 4.13 可视化与报告
| 功能 | 实现方式 |
|---|---|
| Tkinter 2D 回放 | 场地/球员/球/事件显示，逐帧播放 |
| 文本报告 | 比分、射门/传球/抢断统计、控球时间、事件日志 |

---

## 五、数据模型

### 5.1 枚举
```
Role          : GK | ANCHOR | LEFT | RIGHT | PIVOT
TeamPhase     : POSSESSION_BUILD_UP | POSSESSION_ATTACK | DEFENSIVE_SHAPE | HIGH_PRESS | RESTART
PlayerAction  : IDLE | SUPPORT | SPREAD | PRESS | RECOVER | DRIBBLE | PASS | SHOOT
PassType      : TO_FEET | LEAD_PASS | THROUGH_PASS
ReceiveMode   : NONE | COME_SHORT | MEET_BALL | RUN_ONTO
```

### 5.2 数据结构
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
MatchState         → teams + ball + time + events + stats + frames + dead_ball + restart_* + passer/receiver
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

## 六、配置参数（46 个）

### 场地与时间（6）
```
pitch_width=40.0, pitch_height=24.0, goal_width=6.0
tick_seconds=0.2, match_duration_seconds=180.0, decision_interval_seconds=0.4
```

### 球员物理（6）
```
player_radius=0.6, ball_control_radius=1.0
possession_radius=1.2, tackle_radius=1.2, press_radius=4.5, shot_block_radius=1.2
```

### 球基础（2）
```
pass_speed=12.0, shot_speed=18.0, ball_deceleration=3.8
```

### 传球球速（6）
```
pass_speed_min=5.5, pass_speed_max=17.0, pass_speed_distance_per_m=0.4
pass_speed_type_through_bonus=2.0, pass_speed_type_lead_bonus=1.0
pass_speed_pressure_malus=2.5
```

### 提前距离（5）
```
lead_distance_base=1.5, lead_distance_speed_factor=0.35
lead_distance_through_extra=3.5
lead_defender_nudge_radius=2.8, lead_defender_nudge_strength=1.2
```

### 传球误差（7）
```
pass_error_base=0.12, pass_error_quality_factor=0.85
pass_error_distance_per_m=0.014, pass_error_speed_factor=0.03
pass_error_facing_factor=0.4, lead_prediction_quality_factor=0.5
ball_deceleration=3.8
```

### 跑位与防守（14）
```
open_space_radius=5.0, open_space_samples=14, open_space_defender_weight=3.0
support_lane_weight=1.5, dribble_forward_bias=1.5
mark_intercept_ratio=0.4, dribble_push=1.1
support_distance=8.0, shot_range=13.0
defensive_line_gap_max=8.0, attack_layer_gap_max=12.0, weak_side_width=4.0
```

### 体力（2）
```
fatigue_decay_per_second=0.015, recovery_decay_per_second=0.006
```

---

## 七、已验证指标（20 seed）

| 指标 | 数值 |
|---|---|
| 场均射门 | 5–19 次/队 |
| 射门转化率 | ~18% |
| 射正率 | ~32% |
| 传球完成率 | ~85% |
| 门柱/横梁击中 | 每场约 0.5 次 |
| 模拟稳定性 | 100%（所有 seed 无报错） |
| 传球类型分布 | TO_FEET(~41%) / LEAD_PASS(~55%) / THROUGH_PASS(~4%) |
| 横向传球占比 | ~55% |
| 死球后第一动作 | 始终为 PASS |
| 战术风格差异 | Control 防守散布 8.8m vs Direct 9.3m |

---

## 八、当前局限与可探索方向

### 已识别但未完全解决的问题

1. **防线整体性**：防线对齐已实现（参考最靠后队友），但约束是软性的（目标位置调整），球员实际到达需要时间。在转换阶段防线仍会被拉开。
2. **射程内目标偏向曲线**：当前为线性过渡（goal_proximity 0→1），可改为指数过渡使禁区行为更激进。
3. **高位防守的风险**：Direct 风格防线高（68% 场地），反击时更容易被打穿——当前靠反击检测缓解，但未根本解决。

### 尚未探索的方向

4. **犯规与定位球**：无犯规机制，无任意球/点球。
5. **高空球**：无高空过顶长传设定。
6. **阵容多样化**：仅支持 1-2-1（GK-ANCHOR-LEFT/RIGHT-PIVOT），不支持变阵。
7. **球员间纵向间距下限**：仅有"太近推开"，没有"太远拉近"的吸引力。
8. **防守横向压缩**：防守时球队不主动横向收窄。
9. **Zonal marking**：所有盯人是 man-oriented 找最危险对手，无区域防守。
10. **参数自动调优**：46 个参数全部手工设定。
11. **批量模拟框架**：无参数扫描/数据收集工具。

---

## 九、技术文档索引

| 编号 | 文档 | 核心内容 |
|---|---|---|
| 1 | 阶段性技术文档1 | 初始修改方案 |
| 2 | 阶段性技术文档2 | 传接球与预判跑位 |
| 3 | 阶段性技术文档3 | 修改日志 |
| 4 | 阶段性技术文档4 | 中期功能总结 |
| 5 | 阶段性技术文档5 | 可变球速/动态提前量/高斯误差/死球修正/左右修正 |
| 6 | 阶段性技术文档6 | 匀减速球物理/带球空当/无球跑位/防守盯人/传球人状态 |
| 7 | 阶段性技术文档7 | 射门GK瞄准/新扑救公式/门柱横梁/传球射门角度/近距离精度 |
| 8 | 阶段性技术文档8 | 球队整体性/提前距离修正/战术风格差异化 |
| — | 分析文档 | 问题分析与改进方向 |
| — | 架构文档 | 本文档 |
