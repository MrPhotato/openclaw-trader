import type { ReactNode } from "react";

import type { ViewKey } from "../../lib/types";
import { useIsDesktop } from "../../lib/useMedia";
import { Sidebar } from "./Sidebar";
import { MobileTopBar } from "./MobileTopBar";
import type { StatusDotTone } from "../primitives/StatusDot";

export function Shell(props: {
  activeView: ViewKey;
  activeViewLabel: string;
  onSelect: (view: ViewKey) => void;
  connectionLabel: string;
  connectionDotTone: StatusDotTone;
  strategyValue: string;
  activeAgents: number;
  children: ReactNode;
}) {
  const isDesktop = useIsDesktop();

  return (
    <div className="min-h-screen text-slate-100">
      <div className="lg:flex lg:min-h-screen">
        {isDesktop ? (
          <Sidebar
            activeView={props.activeView}
            onSelect={props.onSelect}
            connectionLabel={props.connectionLabel}
            connectionTone={props.connectionDotTone}
            strategyValue={props.strategyValue}
            activeAgents={props.activeAgents}
          />
        ) : (
          <MobileTopBar
            activeView={props.activeView}
            onSelect={props.onSelect}
            connectionLabel={props.connectionLabel}
            connectionTone={props.connectionDotTone}
          />
        )}

        <main className="min-w-0 flex-1">
          <div className="bg-command-grid bg-[size:160px_160px,24px_24px,24px_24px]">
            <div className="mx-auto flex min-h-screen max-w-7xl min-w-0 flex-col gap-4 px-3 pb-8 pt-3 sm:gap-6 sm:px-6 sm:pt-5 lg:px-8">
              {isDesktop ? (
                <header className="flex flex-col gap-2">
                  <div className="brand-eyebrow flex items-center gap-3">
                    <span className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-neon">
                      {props.activeViewLabel}
                    </span>
                    <span className="h-px w-16 animate-pulseLine bg-gradient-to-r from-neon via-white/30 to-transparent" />
                    <span className="text-slate-400">公开看板</span>
                  </div>
                  <h1 className="text-3xl font-semibold leading-none tracking-tight sm:text-4xl">
                    Openclaw Trader AI交易
                  </h1>
                  <p className="max-w-3xl text-xs leading-5 text-slate-400 sm:text-sm sm:leading-6">
                    <span className="text-slate-300">
                      基于 OpenClaw 的 4 Agent Crypto永续合约交易集群实验，本金为 $1000。
                    </span>
                    <a
                      href="https://github.com/MrPhotato/openclaw-trader"
                      target="_blank"
                      rel="noreferrer"
                      className="ml-2 inline-flex items-center text-neon underline decoration-neon/50 underline-offset-4 hover:text-white"
                    >
                      GitHub
                    </a>
                    <span className="ml-2 text-slate-500">·</span>
                    <span className="ml-2 text-slate-400">作者 MrPhotato</span>
                  </p>
                </header>
              ) : (
                <section>
                  <h1 className="text-2xl font-semibold leading-tight tracking-tight">Openclaw Trader AI交易</h1>
                  <p className="mt-1.5 text-xs leading-5 text-slate-400">
                    <span className="text-slate-300">
                      基于 OpenClaw 的 4 Agent Crypto永续合约交易集群实验，本金为 $1000。
                    </span>
                    <a
                      href="https://github.com/MrPhotato/openclaw-trader"
                      target="_blank"
                      rel="noreferrer"
                      className="ml-1 text-neon underline decoration-neon/50 underline-offset-4"
                    >
                      GitHub
                    </a>
                    <span className="ml-1 text-slate-500">·</span>
                    <span className="ml-1 text-slate-400">作者 MrPhotato</span>
                  </p>
                </section>
              )}

              {props.children}
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
