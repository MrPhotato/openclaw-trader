import type { ReactNode } from "react";

export function Panel(props: {
  title: string;
  action?: ReactNode;
  children: ReactNode;
  variant?: "default" | "hero";
  eyebrow?: string;
}) {
  const base = props.variant === "hero" ? "panel-hero" : "glass-panel";
  return (
    <article
      className={`${base} min-w-0 overflow-hidden rounded-[22px] p-4 sm:rounded-[26px] sm:p-5`}
    >
      <div className="mb-4 flex items-start justify-between gap-3 sm:mb-5">
        <div className="min-w-0">
          {props.eyebrow ? (
            <div className="brand-eyebrow mb-1.5">{props.eyebrow}</div>
          ) : null}
          <h2 className="text-lg font-semibold leading-none tracking-tight sm:text-xl">{props.title}</h2>
        </div>
        {props.action ? <div className="shrink-0">{props.action}</div> : null}
      </div>
      {props.children}
    </article>
  );
}
