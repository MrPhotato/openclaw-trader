import type { AgentLatestData, OverviewData } from "../../lib/types";
import { Panel } from "../../components/primitives/Panel";
import { MetricCard } from "../../components/primitives/Metrics";
import {
  portfolioModeLabel,
  riskStateLabel,
  riskStateNarrative,
  strategyFocusText,
} from "../../lib/format";
import { AgentPulseCard } from "../agents/AgentPulseCard";
import { agentPages } from "../agents/config";

export function SystemPulsePanel(props: {
  overview?: OverviewData;
  latestPortfolio: Record<string, unknown>;
  latestStrategy: Record<string, unknown>;
  agentDataByRole: Record<string, AgentLatestData | undefined>;
}) {
  return (
    <Panel title="系统脉搏" eyebrow="Pulse">
      <div className="grid gap-3 sm:grid-cols-2">
        <MetricCard
          label="当前风险状态"
          value={riskStateLabel(props.overview?.risk_overlay)}
          detail={riskStateNarrative(props.overview?.risk_overlay, props.latestPortfolio)}
        />
        <MetricCard
          label="最新策略方向"
          value={portfolioModeLabel(props.latestStrategy["portfolio_mode"])}
          detail={strategyFocusText(props.latestStrategy)}
        />
      </div>
      <div className="mt-4 grid gap-3 xl:grid-cols-2">
        {agentPages.map((agent) => (
          <AgentPulseCard key={agent.role} agent={agent} data={props.agentDataByRole[agent.role]} />
        ))}
      </div>
    </Panel>
  );
}
