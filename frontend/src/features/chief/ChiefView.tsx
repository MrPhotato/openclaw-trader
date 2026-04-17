import type { AgentLatestData } from "../../lib/types";
import { AgentHero } from "../agents/AgentHero";
import { agentPages } from "../agents/config";
import { ChiefRetroTimeline } from "./ChiefRetroTimeline";

export function ChiefView(props: {
  data?: AgentLatestData;
  agentDataByRole: Record<string, AgentLatestData | undefined>;
}) {
  return (
    <section className="space-y-4 sm:space-y-6" data-testid="chief-view">
      <AgentHero agent={agentPages[3]} data={props.data} />
      <ChiefRetroTimeline
        data={props.data}
        agentPages={agentPages}
        agentDataByRole={props.agentDataByRole}
      />
    </section>
  );
}
