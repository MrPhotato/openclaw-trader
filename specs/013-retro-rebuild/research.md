# 研究记录：异步交锋式 Retro 重构

## 决策 1：放弃同步会议，改成异步 brief

- **Decision**：`PM / RT / MEA` 不再按固定轮次在一场会里同步发言，而是各自提交结构化 `retro_brief`。
- **Rationale**：
  - 同步 roundtable 过度依赖单次 lease 和长 session
  - 会议 transcript 不是系统真相，artifact 才是
  - 你真正需要的是交锋，不是会议形式
- **Alternatives considered**：
  - 保留同步会议但加强 helper：仍旧脆
  - 引入群聊插件：解决传输，不解决协议

## 决策 2：把编排权收回 Workflow Orchestrator

- **Decision**：`workflow_orchestrator` 成为 retro 的阶段状态机 owner。
- **Rationale**：
  - retro 本质是多阶段工作流，不是 agent 单次提交
  - WO 应该负责编排、截止时间、降级和收口
  - AG 只该负责 agent-facing 契约，不该主持业务流程
- **Alternatives considered**：
  - 继续由 AG 主持 roundtable：边界继续发脏
  - 把全部逻辑塞进 Chief：会进一步放大 Chief 脆弱性

## 决策 3：保留 AG 作为 pull/submit 契约层

- **Decision**：不把 retro pack / submit schema 迁出 AG。
- **Rationale**：
  - AG 已经是统一 runtime pack 和 schema 校验 owner
  - 复用现有 helper 和 pull/submit 路径风险最低
- **Alternatives considered**：
  - 让 WO 直接拼 prompt 和收 JSON：会把 AG 的职责偷走

## 决策 4：learning 继续只走 self-improving-agent

- **Decision**：learning 不新造协议，不再让 Chief 代发/代写，继续统一走 `/self-improving-agent`。
- **Rationale**：
  - 这已经是项目内现成轮子
  - learning 是每个 agent 的个人责任，不该被 Chief 同步追着确认
- **Alternatives considered**：
  - 新增 learning submit API：复杂且重复
  - 让 Chief 统一写 learning：语义错误

## 决策 5：learning 成功判断改成事实核验

- **Decision**：learning 是否落地以 learning 文件 baseline fingerprint 与当前 fingerprint 比较为准。
- **Rationale**：
  - `sessions_send timeout` 只能说明传输层不稳定，不能说明学习没发生
  - 项目已有 learning 文件 fingerprint 轮子，可直接复用
- **Alternatives considered**：
  - 继续把消息 ACK 当成功标准：误判太多
  - 新增显式 learning ack submit：额外协议负担

## 决策 6：retro 不得跨越 /new 边界

- **Decision**：retro cycle 必须落在一个确定窗口内，不得横跨 `workflow_orchestrator` 的统一 session reset。
- **Rationale**：
  - `/new` 会打断上下文和 lease
  - retro 本身已是跨角色流程，不能再跨 reset 边界
- **Alternatives considered**：
  - 允许跨 reset 自动续跑：复杂且脆
