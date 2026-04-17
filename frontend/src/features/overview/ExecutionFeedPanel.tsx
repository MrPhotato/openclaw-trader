import { useState } from "react";

import type { AssetRecord } from "../../lib/types";
import { Panel } from "../../components/primitives/Panel";
import { PanelToggleButton } from "../../components/primitives/PanelToggleButton";
import { renderAssetCollection } from "../../components/primitives/Collections";
import { TradeBlotterCard } from "./TradeBlotterCard";

export function ExecutionFeedPanel(props: {
  records: AssetRecord[];
  latestPortfolio: Record<string, unknown>;
}) {
  const [expanded, setExpanded] = useState(false);
  const records = props.records;

  return (
    <Panel
      title="最新成交回执"
      eyebrow="Execution"
      action={
        records.length > 3 ? (
          <PanelToggleButton
            expanded={expanded}
            onToggle={() => setExpanded((value) => !value)}
            expandLabel="展开更多成交回执"
            collapseLabel="收起更多成交回执"
          />
        ) : undefined
      }
    >
      <div className="space-y-3" data-testid="overview-execution-disclosure">
        {renderAssetCollection(
          records.slice(0, 3),
          (record) => <TradeBlotterCard key={record.asset_id} asset={record} latestPortfolio={props.latestPortfolio} />,
          "最近还没有新的正式执行结果。",
        )}
        {expanded ? (
          <div className="space-y-3">
            {renderAssetCollection(
              records.slice(3),
              (record) => <TradeBlotterCard key={record.asset_id} asset={record} latestPortfolio={props.latestPortfolio} />,
              "最近还没有新的正式执行结果。",
            )}
          </div>
        ) : null}
      </div>
    </Panel>
  );
}
