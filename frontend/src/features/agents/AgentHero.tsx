import type { AgentLatestData } from "../../lib/types";
import { HeroMetric } from "../../components/primitives/Metrics";
import { assetTypeLabel, sessionStatusLabel, latestAssetTimestamp } from "../../lib/format";
import type { AgentPage } from "./config";

export function AgentHero(props: { agent: AgentPage; data?: AgentLatestData }) {
  const sessionStatus = String(props.data?.session?.status ?? "offline");
  const latestType = String(props.data?.latest_asset?.asset_type ?? "none");
  const latestAt = latestAssetTimestamp(props.data);

  return (
    <section className="panel-hero rounded-[24px] px-4 py-5 sm:rounded-[28px] sm:px-6 sm:py-6">
      <div className="grid gap-4 lg:grid-cols-[1.1fr_0.9fr] lg:items-end">
        <div className="space-y-3">
          <div className={`brand-eyebrow ${props.agent.accent}`}>{props.agent.label}</div>
          <div>
            <h2 className="text-3xl font-semibold tracking-tight sm:text-4xl">{props.agent.name}</h2>
            <p className="mt-2 max-w-2xl text-sm leading-7 text-slate-300">{props.agent.intro}</p>
          </div>
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          <HeroMetric label="会话状态" value={sessionStatusLabel(sessionStatus)} tone={props.agent.accent} />
          <HeroMetric label="最近产物" value={assetTypeLabel(latestType)} tone="text-slate-100" />
          <HeroMetric label="最近活跃" value={latestAt} tone="text-slate-200" />
        </div>
      </div>
    </section>
  );
}
