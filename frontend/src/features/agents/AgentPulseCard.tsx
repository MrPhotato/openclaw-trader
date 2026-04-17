import type { AgentLatestData } from "../../lib/types";
import { assetPreview, assetTypeLabel, formatTime, sessionStatusLabel } from "../../lib/format";
import type { AgentPage } from "./config";

export function AgentPulseCard(props: { agent: AgentPage; data?: AgentLatestData }) {
  const sessionStatus = String(props.data?.session?.status ?? "offline");
  const latestAsset = props.data?.latest_asset;
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-4 ring-hairline hover-lift">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className={`text-sm font-medium ${props.agent.accent}`}>{props.agent.label}</div>
          <div className="mt-1 text-xs text-slate-400">{props.agent.name}</div>
        </div>
        <div className="text-xs text-slate-500">{sessionStatusLabel(sessionStatus)}</div>
      </div>
      <div className="mt-3 text-sm leading-6 text-slate-200">{assetPreview(latestAsset)}</div>
      <div className="mt-2 text-xs text-slate-500">
        {latestAsset ? `${assetTypeLabel(latestAsset.asset_type)} · ${formatTime(latestAsset.created_at)}` : "还没有新的正式产物。"}
      </div>
    </div>
  );
}
