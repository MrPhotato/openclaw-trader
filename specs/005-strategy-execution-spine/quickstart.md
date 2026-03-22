# Quickstart：如何使用 005 主脊梁

## 1. 上游输入

- `005` 只读取 `004` 提供的市场和风险守卫结构化输出。
- 所有主动流程由 `003` 的控制平面触发。

## 2. 下游使用

- `006` 读取 `ExecutionContext` 和 `ExecutionDecision`
- `007` 读取 `ExecutionResult`

## 3. 约束

- 任何 Agent 都不能直接产出 `ExecutionResult`
- 任何执行适配层都不能直接改写 `StrategyIntent`
- 第一批主工作流停在 `ExecutionContext`
