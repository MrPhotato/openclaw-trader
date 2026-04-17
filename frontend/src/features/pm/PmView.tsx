import type { AgentLatestData } from "../../lib/types";
import { Panel } from "../../components/primitives/Panel";
import { Headline, SectionLabel } from "../../components/primitives/Typography";
import { renderCollection } from "../../components/primitives/Collections";
import {
  nonEmptyText,
  portfolioModeLabel,
  readRechecks,
  readTargets,
  strategyFocusText,
  strategyIdentity,
} from "../../lib/format";
import { AgentHero } from "../agents/AgentHero";
import { agentPages } from "../agents/config";

export function PmView(props: {
  data?: AgentLatestData;
  latestStrategy: Record<string, unknown>;
}) {
  return (
    <section className="space-y-4 sm:space-y-6" data-testid="pm-view">
      <AgentHero agent={agentPages[0]} data={props.data} />
      <section className="grid min-w-0 gap-4 sm:gap-6 lg:grid-cols-[1.05fr_0.95fr]">
        <Panel title="当前正式策略" eyebrow="Strategy">
          <div className="space-y-4">
            <Headline label="策略版本" value={strategyIdentity(props.latestStrategy)} />
            <Headline label="组合模式" value={portfolioModeLabel(props.latestStrategy["portfolio_mode"])} />
            <Headline label="策略重点" value={strategyFocusText(props.latestStrategy)} />
            <Headline
              label="变更摘要"
              value={nonEmptyText(props.latestStrategy["change_summary"], "当前还没有显式写出的变更摘要。")}
            />
            <Headline
              label="翻向条件"
              value={nonEmptyText(props.latestStrategy["flip_triggers"], "当前还没有写明翻向条件。")}
            />
            <Headline
              label="失效条件"
              value={nonEmptyText(props.latestStrategy["portfolio_invalidation"], "暂无明确失效条件。")}
            />
          </div>
        </Panel>
        <Panel title="目标与复核" eyebrow="Targets">
          <div className="grid gap-3">
            {renderCollection(
              readTargets(props.latestStrategy),
              (target) => (
                <div
                  key={target.label}
                  className="rounded-2xl border border-white/10 bg-white/[0.04] p-4 ring-hairline hover-lift"
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-medium">{target.label}</span>
                    <span className="text-xs text-slate-400">{target.direction}</span>
                  </div>
                  <div className="mt-2 text-sm leading-6 text-slate-300">{target.detail}</div>
                </div>
              ),
              "PM 还没有提交具体 target，系统会先维持空白。",
            )}
          </div>
          <div className="mt-4">
            <SectionLabel label="下一轮复核" />
            <div className="mt-3 space-y-2">
              {renderCollection(
                readRechecks(props.latestStrategy),
                (item) => (
                  <div
                    key={item.label}
                    className="rounded-2xl border border-white/10 bg-white/[0.03] px-4 py-3 text-sm leading-6 text-slate-300"
                  >
                    <div className="font-medium text-slate-200">{item.label}</div>
                    <div className="mt-1 text-xs text-slate-400">{item.detail}</div>
                  </div>
                ),
                "当前没有排程中的复核节点。",
              )}
            </div>
          </div>
        </Panel>
      </section>
    </section>
  );
}
