import type { ReactNode } from "react";

import type { AgentLatestData } from "../../lib/types";
import { Panel } from "../../components/primitives/Panel";
import { EmptyState } from "../../components/primitives/EmptyState";
import { HeroMetric } from "../../components/primitives/Metrics";
import { AgentPulseCard } from "../agents/AgentPulseCard";
import type { AgentPage } from "../agents/config";
import {
  GRADE_TONE,
  ROLE_LABEL,
  asRecord,
  chiefLearningChainState,
  chiefRetroModeLabel,
  formatTime,
  hasTextualLearningSection,
  nonEmptyText,
  normalizeRetroChallengePrompts,
  parseRoleJudgement,
  stripLeadingOrdinal,
} from "../../lib/format";

function RetroPhasePanel(props: { step: number; title: string; timestamp: string; children: ReactNode }) {
  return (
    <article className="glass-panel min-w-0 overflow-hidden rounded-[22px] sm:rounded-[26px]">
      <div className="flex items-center gap-3 border-b border-white/5 px-4 py-3 sm:px-5">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-amber-500/20 text-xs font-bold text-amber-200">
          {props.step}
        </span>
        <h2 className="text-lg font-semibold tracking-tight sm:text-xl">{props.title}</h2>
        {props.timestamp ? <span className="ml-auto text-xs tabular-nums text-slate-500">{props.timestamp}</span> : null}
      </div>
      <div className="p-4 sm:p-5">{props.children}</div>
    </article>
  );
}

function BriefField(props: { label: string; value: unknown }) {
  const text = typeof props.value === "string" ? props.value.trim() : "";
  if (!text) return null;
  return (
    <div>
      <div className="mb-1 text-[11px] uppercase tracking-[0.22em] text-slate-500">{props.label}</div>
      <div className="whitespace-pre-line text-sm leading-6 text-slate-300">{text}</div>
    </div>
  );
}

export function ChiefRetroTimeline(props: {
  data?: AgentLatestData;
  agentPages: readonly AgentPage[];
  agentDataByRole: Record<string, AgentLatestData | undefined>;
}) {
  const { data } = props;
  const chain = data?.retro_chain;
  const retro = data?.latest_chief_retro ?? data?.latest_asset;
  const retroPayload = asRecord(retro?.payload);

  if (!retro && !chain) {
    return (
      <Panel title="复盘时间线" eyebrow="Retro">
        <EmptyState message="还没有已完成的复盘记录。" />
      </Panel>
    );
  }

  const rc = chain?.retro_case ? asRecord(chain.retro_case) : null;
  const briefs = chain?.briefs ?? [];
  const directives = chain?.learning_directives ?? [];
  const learningResults = Array.isArray(retroPayload?.learning_results)
    ? (retroPayload.learning_results as Record<string, unknown>[])
    : [];
  const rootCauseRanking = Array.isArray(retroPayload?.root_cause_ranking)
    ? (retroPayload.root_cause_ranking as string[])
    : [];
  const roleJudgements = asRecord(retroPayload?.role_judgements);
  const ownerSummary = typeof retroPayload?.owner_summary === "string" ? retroPayload.owner_summary : "";
  const challengePrompts = normalizeRetroChallengePrompts(rc?.challenge_prompts);
  const learningDirectiveEmptyMessage = hasTextualLearningSection(ownerSummary)
    ? "这轮只在文本里写了学习要求，没提交结构化 learning_directives。"
    : "此次复盘没有生成学习指令。";
  const learningResultEmptyMessage =
    directives.length > 0
      ? "学习指令已生成，但学习结果尚未回写。"
      : hasTextualLearningSection(ownerSummary)
        ? "这轮没有结构化学习指令，所以也没有可核验的学习落实记录。"
        : "学习结果尚未回写。";
  const learningChain = chiefLearningChainState({
    ownerSummary,
    directives,
    learningResults,
    learningCompleted: retroPayload?.learning_completed === true,
  });

  return (
    <div className="space-y-4 sm:space-y-6">
      {/* ① 复盘准备 */}
      <RetroPhasePanel
        step={1}
        title="复盘准备"
        timestamp={rc ? formatTime(String(rc.created_at_utc ?? rc.created_at ?? "")) : ""}
      >
        {rc ? (
          <div className="space-y-4">
            <div className="flex flex-wrap gap-3">
              <HeroMetric label="复盘日期" value={String(rc.case_day_utc ?? "—")} tone="text-slate-100" />
              <HeroMetric label="目标收益" value={`${rc.target_return_pct ?? 1}%`} tone="text-amber-200" />
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-4 ring-hairline">
              <div className="mb-2 text-[10px] uppercase tracking-[0.26em] text-slate-500">核心问题</div>
              <div className="text-sm font-medium text-slate-100">{nonEmptyText(rc.primary_question, "—")}</div>
            </div>
            {typeof rc.objective_summary === "string" && rc.objective_summary && (
              <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-4 ring-hairline">
                <div className="mb-2 text-[10px] uppercase tracking-[0.26em] text-slate-500">客观摘要</div>
                <div className="whitespace-pre-line text-sm leading-7 text-slate-300">{String(rc.objective_summary)}</div>
              </div>
            )}
            {challengePrompts.length > 0 && (
              <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-4 ring-hairline">
                <div className="mb-3 text-[10px] uppercase tracking-[0.26em] text-slate-500">挑战提示</div>
                <div className="space-y-2">
                  {challengePrompts.map((prompt, i) => (
                    <div key={i} className="flex gap-2 text-sm">
                      {prompt.label ? <span className="shrink-0 font-medium text-slate-400">{prompt.label}:</span> : null}
                      <span className="text-slate-300">{prompt.text}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : (
          <EmptyState message="此次复盘没有关联到 retro case。" />
        )}
      </RetroPhasePanel>

      {/* ② 角色自述 */}
      <RetroPhasePanel step={2} title="角色自述" timestamp="">
        {briefs.length > 0 ? (
          <div className="grid gap-4 lg:grid-cols-3">
            {briefs.map((brief) => {
              const b = asRecord(brief) ?? {};
              const role = String(b.agent_role ?? "");
              return (
                <div
                  key={`${role}-${b.brief_id}`}
                  className="space-y-3 rounded-2xl border border-white/10 bg-white/[0.04] p-4 ring-hairline"
                >
                  <div className="flex items-center gap-2">
                    <span className="text-base font-semibold text-slate-100">{ROLE_LABEL[role] ?? role}</span>
                    <span className="text-xs tabular-nums text-slate-500">{formatTime(String(b.created_at_utc ?? ""))}</span>
                  </div>
                  <BriefField label="根因分析" value={b.root_cause} />
                  <BriefField label="自我批评" value={b.self_critique} />
                  <BriefField label="互相挑战" value={b.cross_role_challenge} />
                  <BriefField label="明日改进" value={b.tomorrow_change} />
                </div>
              );
            })}
          </div>
        ) : (
          <EmptyState message="此次复盘没有收到角色自述 brief。" />
        )}
      </RetroPhasePanel>

      {/* ③ Chief 综合 */}
      <RetroPhasePanel step={3} title="Chief 综合判断" timestamp={retro ? formatTime(retro.created_at) : ""}>
        {retroPayload ? (
          <div className="space-y-4">
            <div className="whitespace-pre-line rounded-2xl border border-white/10 bg-white/[0.04] p-4 text-sm leading-7 text-slate-300 ring-hairline">
              {nonEmptyText(retroPayload.owner_summary, "此次复盘还没有 owner summary。")}
            </div>
            {rootCauseRanking.length > 0 && (
              <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-4 ring-hairline">
                <div className="mb-3 text-[10px] uppercase tracking-[0.26em] text-slate-500">根因排序</div>
                <ol className="list-inside list-decimal space-y-1 text-sm text-slate-300">
                  {rootCauseRanking.map((cause, i) => (
                    <li key={i}>{stripLeadingOrdinal(String(cause))}</li>
                  ))}
                </ol>
              </div>
            )}
            {roleJudgements && (
              <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-4 ring-hairline">
                <div className="mb-3 text-[10px] uppercase tracking-[0.26em] text-slate-500">角色裁决</div>
                <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                  {Object.entries(roleJudgements).map(([role, judgement]) => {
                    const parsed = parseRoleJudgement(judgement);
                    return (
                      <div key={role} className="rounded-xl border border-white/5 bg-white/[0.03] p-3">
                        <div className="text-xs text-slate-500">{ROLE_LABEL[role] ?? role}</div>
                        {parsed.grade ? (
                          <>
                            <div className={`mt-1 text-2xl font-bold ${GRADE_TONE[parsed.grade] ?? "text-slate-200"}`}>
                              {parsed.grade}
                            </div>
                            {parsed.comment ? (
                              <div className="mt-2 text-xs leading-5 text-slate-400">{parsed.comment}</div>
                            ) : null}
                          </>
                        ) : (
                          <div className="mt-2 text-sm leading-6 text-slate-300">{parsed.comment || "暂无结构化裁决。"}</div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
            <div className="grid gap-3 sm:grid-cols-3">
              <HeroMetric label="复盘模式" value={chiefRetroModeLabel(retroPayload?.round_count)} tone="text-slate-100" />
              <HeroMetric label="学习链路" value={learningChain.value} tone={learningChain.tone} />
              <HeroMetric label="复盘时间" value={retro ? formatTime(retro.created_at) : "—"} tone="text-slate-200" />
            </div>
          </div>
        ) : (
          <EmptyState message="Chief 还没有提交综合判断。" />
        )}
      </RetroPhasePanel>

      {/* ④ 学习指令 */}
      <RetroPhasePanel step={4} title="学习指令" timestamp="">
        {directives.length > 0 ? (
          <div className="space-y-3">
            {directives.map((dir) => {
              const d = asRecord(dir) ?? {};
              const role = String(d.agent_role ?? "");
              return (
                <div
                  key={String(d.directive_id ?? role)}
                  className="rounded-2xl border border-white/10 bg-white/[0.04] p-4 ring-hairline"
                >
                  <div className="mb-2 flex items-center gap-2">
                    <span className="rounded-full bg-amber-500/20 px-2 py-0.5 text-xs font-medium text-amber-200">
                      {ROLE_LABEL[role] ?? role}
                    </span>
                  </div>
                  <div className="text-sm leading-7 text-slate-200">{nonEmptyText(d.directive, "无具体指令。")}</div>
                  {typeof d.rationale === "string" && d.rationale ? (
                    <div className="mt-2 text-xs text-slate-500">依据：{String(d.rationale)}</div>
                  ) : null}
                </div>
              );
            })}
          </div>
        ) : (
          <EmptyState message={learningDirectiveEmptyMessage} />
        )}
      </RetroPhasePanel>

      {/* ⑤ 学习落实 */}
      <RetroPhasePanel step={5} title="学习落实" timestamp="">
        {learningResults.length > 0 ? (
          <div className="space-y-3">
            {learningResults.map((item, i) => {
              const record = asRecord(item) ?? {};
              const role = String(record.agent_role ?? "agent");
              return (
                <div
                  key={`${role}-${i}`}
                  className="rounded-2xl border border-white/10 bg-white/[0.04] p-4 ring-hairline"
                >
                  <div className="font-medium text-slate-100">{ROLE_LABEL[role] ?? role.toUpperCase()} 学习记录</div>
                  <div className="mt-2 text-sm leading-7 text-slate-300">
                    {nonEmptyText(record.learning_summary, "本轮没有写出额外的学习摘要。")}
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <EmptyState message={learningResultEmptyMessage} />
        )}
      </RetroPhasePanel>

      {/* 席位状态 */}
      <Panel title="席位状态" eyebrow="Seats">
        <div className="grid gap-3">
          {props.agentPages.map((agent) => (
            <AgentPulseCard key={agent.role} agent={agent} data={props.agentDataByRole[agent.role]} />
          ))}
        </div>
      </Panel>
    </div>
  );
}
