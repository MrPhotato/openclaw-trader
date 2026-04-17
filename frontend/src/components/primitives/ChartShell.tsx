import type { ReactNode } from "react";

export function ChartShell(props: { children: ReactNode }) {
  return (
    <div className="min-w-0 rounded-[18px] border border-white/10 bg-white/[0.03] p-2 ring-hairline sm:rounded-[22px] sm:p-3">
      {props.children}
    </div>
  );
}
