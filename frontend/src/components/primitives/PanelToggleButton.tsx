export function PanelToggleButton(props: {
  expanded: boolean;
  onToggle: () => void;
  expandLabel: string;
  collapseLabel: string;
}) {
  return (
    <button
      type="button"
      onClick={props.onToggle}
      aria-label={props.expanded ? props.collapseLabel : props.expandLabel}
      className="rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-slate-200 transition hover:border-neon/40 hover:bg-white/10 hover:text-white"
    >
      {props.expanded ? "收起" : "展开更多"}
    </button>
  );
}
