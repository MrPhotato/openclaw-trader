export function EmptyState(props: { message: string }) {
  return (
    <div className="rounded-2xl border border-dashed border-white/10 bg-white/[0.02] px-4 py-5 text-sm leading-6 text-slate-400">
      {props.message}
    </div>
  );
}
