import type { AssetRecord, EventEnvelope } from "../types";
import { humanizeToken } from "./misc";

export const moduleLabels: Record<string, string> = {
  agent_gateway: "Agent Gateway",
  workflow_orchestrator: "工作流编排",
  trade_gateway: "交易网关",
  market_data: "市场数据",
  policy_risk: "风控",
  notification_service: "通知",
  memory_assets: "资产归档",
  news_events: "新闻事件",
  quant_intelligence: "量化洞察",
};

export function newsCategoryLabel(value: unknown): string {
  const category = String(value ?? "macro");
  if (category === "macro") {
    return "宏观";
  }
  if (category === "policy") {
    return "政策";
  }
  if (category === "onchain") {
    return "链上";
  }
  return category;
}

export function impactLabel(value: string): string {
  if (value === "high") {
    return "高";
  }
  if (value === "medium") {
    return "中";
  }
  return "低";
}

export function impactTone(impact: string): string {
  if (impact === "high") {
    return "text-ember";
  }
  if (impact === "medium") {
    return "text-signal";
  }
  return "text-neon";
}

export function urgencyLabel(value: unknown): string {
  const raw = String(value ?? "").toLowerCase();
  if (raw === "high") {
    return "高优先";
  }
  if (raw === "medium") {
    return "中优先";
  }
  if (raw === "low") {
    return "低优先";
  }
  return "常规";
}

export function buildImpactBreakdown(records: AssetRecord[]): Array<{ impact: string; count: number; fill: string }> {
  const counts = new Map<string, number>();
  for (const record of records) {
    const impact = String(record.payload["impact_level"] ?? "low");
    counts.set(impact, (counts.get(impact) ?? 0) + 1);
  }
  return ["high", "medium", "low"].map((impact) => ({
    impact: impactLabel(impact),
    count: counts.get(impact) ?? 0,
    fill: impact === "high" ? "#ff7d45" : impact === "medium" ? "#ffe066" : "#71f6d1",
  }));
}

export function summarizeEvent(event: EventEnvelope): { title: string; detail: string } {
  const eventType = event.event_type;
  const payload = event.payload;
  if (eventType === "strategy.submitted") {
    return {
      title: "PM 提交了新策略",
      detail: "新的策略版本已经正式落地。",
    };
  }
  if (eventType === "execution.submitted") {
    return {
      title: "RT 提交了执行决策",
      detail: "新的执行批次已经送审。",
    };
  }
  if (eventType === "execution.result.completed") {
    return {
      title: "交易网关返回了执行结果",
      detail: typeof payload["message"] === "string" ? payload["message"] : "执行结果已经写回系统。",
    };
  }
  if (eventType === "workflow.state.completed") {
    return {
      title: "流程完成",
      detail: "这条链路已经正常走完。",
    };
  }
  if (eventType === "workflow.state.degraded") {
    return {
      title: "流程降级",
      detail: "链路完成了部分步骤，但过程中出现了问题。",
    };
  }
  if (eventType === "notification.sent") {
    return {
      title: "通知已发出",
      detail: "重要结果已经推送给对应接收方。",
    };
  }
  return {
    title: humanizeToken(eventType),
    detail: `${moduleLabels[event.source_module] ?? event.source_module} 发出了一条正式事件。`,
  };
}
