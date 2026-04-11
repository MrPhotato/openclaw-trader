# 蓝图阅读快速导览

如果你想快速理解这套蓝图，建议按下面顺序阅读：

1. [`spec.md`](specs/001-system-blueprint/spec.md)
   - 先看这份，理解这次蓝图交付到底要解决什么问题。
2. [`architecture/00-current-system-baseline.md`](specs/001-system-blueprint/architecture/00-current-system-baseline.md)
   - 看当前系统真实长什么样。
3. [`architecture/01-target-architecture.md`](specs/001-system-blueprint/architecture/01-target-architecture.md)
   - 看未来 10 模块、3 条平面、4 个 Agent 的总图。
4. [`architecture/02-module-inventory.md`](specs/001-system-blueprint/architecture/02-module-inventory.md)
   - 看当前代码如何映射到未来模块。
5. [`architecture/04-state-machine.md`](specs/001-system-blueprint/architecture/04-state-machine.md)
   - 看系统流程怎么切换。
6. [`architecture/05-event-bus-topology.md`](specs/001-system-blueprint/architecture/05-event-bus-topology.md)
   - 看模块之间如何通过消息通信。
7. [`architecture/10-trading-semantics-and-learnings.md`](specs/001-system-blueprint/architecture/10-trading-semantics-and-learnings.md)
   - 看当前策略语义、近期放宽项和经验教训。
8. [`contracts/`](specs/001-system-blueprint/contracts)
   - 看接口契约、事件协议、OpenClaw 适配。
9. [`analysis.md`](specs/001-system-blueprint/analysis.md)
   - 看规格、计划、任务和契约之间是否一致。
10. [`tasks.md`](specs/001-system-blueprint/tasks.md)
   - 看如何按波次实施。
11. [`architecture/11-live-runtime-reproduction.md`](specs/001-system-blueprint/architecture/11-live-runtime-reproduction.md)
   - 看当前 live 运行态怎么复现。
12. [`architecture/12-quant-model-reproduction.md`](specs/001-system-blueprint/architecture/12-quant-model-reproduction.md)
   - 看量化小模型框架、训练与推理怎么复现。
13. [`architecture/13-openclaw-agent-runtime.md`](specs/001-system-blueprint/architecture/13-openclaw-agent-runtime.md)
   - 看 OpenClaw / Agent 运行事实。
14. [`architecture/14-deployment-topology.md`](specs/001-system-blueprint/architecture/14-deployment-topology.md)
   - 看本机常驻部署拓扑。
15. [`architecture/15-interface-storage-inventory.md`](specs/001-system-blueprint/architecture/15-interface-storage-inventory.md)
   - 看当前接口和数据载体清单。

## 本蓝图的阅读原则

- “当前系统”与“目标系统”是两层文档，不要混看。
- 凡是涉及系统事实、当前文件落点、当前接口，都以基线文档为准。
- 凡是涉及未来模块边界、事件总线、统一外部入口、多 Agent 分工，都以目标架构和契约文档为准。

## 本蓝图不做的事

- 不直接替你重写所有代码。
- 不假装当前系统已经完全模块化。
- 不把所有运行态问题归咎于一个模块，而是先把边界与责任讲清楚。
