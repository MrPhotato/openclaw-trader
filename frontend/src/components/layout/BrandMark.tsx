export function BrandMark(props: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-3">
      <div className="relative flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-xl border border-white/10 bg-gradient-to-br from-neon/25 via-white/5 to-ember/20 shadow-[0_0_22px_rgba(113,246,209,0.18)]">
        <img
          src="/brand-mark.png"
          alt="OpenClaw 吉祥物"
          className="h-full w-full object-cover"
          draggable={false}
        />
      </div>
      {props.compact ? null : (
        <div className="min-w-0">
          <div className="brand-eyebrow text-neon">OpenClaw</div>
          <div className="text-sm font-semibold leading-tight tracking-tight text-white">Trader 看板</div>
        </div>
      )}
    </div>
  );
}
