import type { AgentLatestData, AssetRecord, OverviewData } from "../../lib/types";
import { Panel } from "../../components/primitives/Panel";
import { renderAssetCollection, renderCollection } from "../../components/primitives/Collections";
import { AgentHero } from "../agents/AgentHero";
import { agentPages } from "../agents/config";
import { TradeBlotterCard } from "../overview/TradeBlotterCard";
import { RtTacticalBoard } from "./RtTacticalBoard";
import { ThoughtCard } from "./ThoughtCard";

export function RtView(props: {
  data?: AgentLatestData;
  latestStrategy: Record<string, unknown>;
  latestPortfolio: Record<string, unknown>;
  overview?: OverviewData;
  executionResultsOverride?: AssetRecord[];
}) {
  const executionRecords = (
    props.executionResultsOverride ?? props.overview?.recent_execution_results ?? []
  ).slice(0, 4);

  return (
    <section className="space-y-4 sm:space-y-6" data-testid="rt-view">
      <AgentHero agent={agentPages[1]} data={props.data} />
      <section className="grid min-w-0 gap-4 sm:gap-6 lg:grid-cols-[minmax(0,1.65fr)_minmax(300px,0.72fr)]">
        <Panel title="RT 战术地图" eyebrow="Tactical Map">
          <RtTacticalBoard data={props.data} latestStrategy={props.latestStrategy} />
        </Panel>
        <div className="min-w-0 space-y-4 sm:space-y-6">
          <Panel title="最新执行回执" eyebrow="Latest">
            <div className="space-y-3">
              {renderAssetCollection(
                executionRecords,
                (record) => (
                  <TradeBlotterCard key={record.asset_id} asset={record} latestPortfolio={props.latestPortfolio} />
                ),
                "RT 还没有新的正式执行结果。",
              )}
            </div>
          </Panel>
          <Panel title="判断记录" eyebrow="Desk Notes">
            <div className="space-y-3">
              {renderCollection(
                (props.data?.recent_execution_thoughts ?? []).slice(0, 4),
                (thought, index) => (
                  <ThoughtCard key={`${thought.symbol ?? "thought"}-${index}`} thought={thought} />
                ),
                "RT 还没有沉淀出可展示的近期思路记录。",
              )}
            </div>
          </Panel>
        </div>
      </section>
    </section>
  );
}
