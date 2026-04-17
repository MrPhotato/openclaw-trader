export function Headline(props: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-[0.28em] text-slate-500">{props.label}</div>
      <div className="mt-1 text-base leading-7 text-slate-100">{props.value}</div>
    </div>
  );
}

export function SectionLabel(props: { label: string }) {
  return <div className="text-[10px] uppercase tracking-[0.28em] text-slate-500">{props.label}</div>;
}
