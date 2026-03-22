# 任务清单：Agent Gateway

**规格文档**：`specs/modules/agent_gateway/spec.md`

- [ ] T001 固化 `news`、`strategy`、`execution` 三类正式提交模板
- [ ] T002 为三类模板补齐 schema、prompt 说明与 example
- [ ] T003 定义 `ValidatedSubmissionEnvelope` 与默认消费者关系
- [ ] T004 明确 AG 只做准入校验与分发，不做长期记忆、策略版本化或执行语义解释
- [ ] T005 回写旧 `006` 与总览文档中的提交通道描述
