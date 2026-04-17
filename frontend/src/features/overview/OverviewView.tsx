import type { AgentLatestData, AssetRecord, MarketContextData, OverviewData } from "../../lib/types";
import type { BalanceGranularity } from "../../lib/format";
import { BalancePanel } from "./BalancePanel";
import { SystemPulsePanel } from "./SystemPulsePanel";
import { ExecutionFeedPanel } from "./ExecutionFeedPanel";
import { EventFeedPanel } from "./EventFeedPanel";

export function OverviewView(props: {
  overview?: OverviewData;
  latestPortfolio: Record<string, unknown>;
  latestStrategy: Record<string, unknown>;
  agentDataByRole: Record<string, AgentLatestData | undefined>;
  marketContext?: MarketContextData;
  executionRecords: AssetRecord[];
  macroEventRecords: AssetRecord[];
  balanceGranularity: BalanceGranularity;
  onBalanceGranularityChange: (value: BalanceGranularity) => void;
}) {
  return (
    <section
      className="grid min-w-0 gap-4 sm:gap-6 lg:grid-cols-[1.25fr_0.95fr]"
      data-testid="overview-view"
    >
      <div className="min-w-0 space-y-4 sm:space-y-6">
        <BalancePanel
          overview={props.overview}
          latestPortfolio={props.latestPortfolio}
          latestStrategy={props.latestStrategy}
          granularity={props.balanceGranularity}
          onGranularityChange={props.onBalanceGranularityChange}
          executionRecords={props.executionRecords}
          marketContext={props.marketContext}
        />
        <SystemPulsePanel
          overview={props.overview}
          latestPortfolio={props.latestPortfolio}
          latestStrategy={props.latestStrategy}
          agentDataByRole={props.agentDataByRole}
        />
      </div>
      <div className="min-w-0 space-y-4 sm:space-y-6">
        <ExecutionFeedPanel records={props.executionRecords} latestPortfolio={props.latestPortfolio} />
        <EventFeedPanel records={props.macroEventRecords} />
      </div>
    </section>
  );
}
