import type { ViewKey } from "../../lib/types";

export const agentPages = [
  {
    view: "pm",
    role: "pm",
    label: "PM",
    name: "Portfolio Manager",
    accent: "text-emerald-200",
    intro: "负责给出组合方向、风险预算和再检查节奏。这里展示的是正式策略，不是内部草稿。",
  },
  {
    view: "rt",
    role: "risk_trader",
    label: "RT",
    name: "Risk Trader",
    accent: "text-orange-200",
    intro: "负责把 PM 的组合框架转成可执行决策。重点看战术地图、风险锁和最新成交回执。",
  },
  {
    view: "mea",
    role: "macro_event_analyst",
    label: "MEA",
    name: "Macro & Event Analyst",
    accent: "text-sky-200",
    intro: "负责跟踪宏观与事件冲击，筛出真正会改变交易判断的新闻，而不是堆信息流。",
  },
  {
    view: "chief",
    role: "crypto_chief",
    label: "Chief",
    name: "Crypto Chief",
    accent: "text-amber-200",
    intro: "负责复盘、owner summary 和四个席位的会后学习。这里看的是当天这套系统学到了什么。",
  },
] as const;

export type AgentPage = (typeof agentPages)[number];

export const navItems: Array<{ key: ViewKey; label: string }> = [
  { key: "overview", label: "总览" },
  { key: "pm", label: "PM" },
  { key: "rt", label: "RT" },
  { key: "mea", label: "MEA" },
  { key: "chief", label: "Chief" },
];
