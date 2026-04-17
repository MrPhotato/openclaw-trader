import { useState } from "react";

import type { AssetRecord } from "../../lib/types";
import { Panel } from "../../components/primitives/Panel";
import { PanelToggleButton } from "../../components/primitives/PanelToggleButton";
import { renderAssetCollection } from "../../components/primitives/Collections";
import { MacroEventCard } from "../mea/MacroEventCard";

export function EventFeedPanel(props: { records: AssetRecord[] }) {
  const [expanded, setExpanded] = useState(false);
  const records = props.records;

  return (
    <Panel
      title="高优先事件"
      eyebrow="Signal"
      action={
        records.length > 3 ? (
          <PanelToggleButton
            expanded={expanded}
            onToggle={() => setExpanded((value) => !value)}
            expandLabel="展开更多高优先事件"
            collapseLabel="收起更多高优先事件"
          />
        ) : undefined
      }
    >
      <div className="space-y-3" data-testid="overview-event-disclosure">
        {renderAssetCollection(
          records.slice(0, 3),
          (record) => <MacroEventCard key={record.asset_id} asset={record} />,
          "高影响事件会在这里排到最上面，当前还没有新的正式事件。",
        )}
        {expanded ? (
          <div className="space-y-3">
            {renderAssetCollection(
              records.slice(3),
              (record) => <MacroEventCard key={record.asset_id} asset={record} />,
              "高影响事件会在这里排到最上面，当前还没有新的正式事件。",
            )}
          </div>
        ) : null}
      </div>
    </Panel>
  );
}
