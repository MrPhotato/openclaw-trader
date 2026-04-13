# 复盘流程

首选复盘窗口：
- 在 WO 准备好 `retro_case + retro_briefs` 之后

将复盘作为异步判断流程执行，而非实时会议。

工作顺序：

1. 读取 `retro_case`
- 理解目标：
  - 桌面为什么没能赚到 `1%`
  - **桌面方向做对了但仓位太小、错过大部分利润的情况同样重要——这和做错方向是对等的失败**
  - 明确的挑战提示是什么

停止条件：
- 如果 `retro_case` 缺失，或 `pending_retro_brief_roles[]` 非空，立即停止
- 不要自行创建替代 briefs
- 不要将复盘转变为同步圆桌会议

2. 读取全部三份角色 briefs
- `pm_retro_brief`
- `rt_retro_brief`
- `mea_retro_brief`

3. 评判 briefs
- 识别谁看对了方向
- 识别谁过于防守、过于迟缓、或噪音过多
- **识别谁在方向正确时仓位过小（under-positioned），导致团队没有把判断变成利润**
- 区分：
  - 信号质量
  - 执行质量（包括是否充分利用了 discretion 空间）
  - 流程质量
  - 运气

4. 撰写 Chief 综合报告
- `owner_summary`
- `root_cause_ranking`
- `role_judgements`
- `learning_directives`

方法：
- 默认使用 AAR 结构
- 仅在重大失败时使用 `5 Whys`
