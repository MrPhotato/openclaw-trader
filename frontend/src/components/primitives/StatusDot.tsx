export type StatusDotTone = "online" | "warning" | "error" | "idle";

const TONE_CLASS: Record<StatusDotTone, string> = {
  online: "bg-neon shadow-[0_0_12px_rgba(113,246,209,0.6)]",
  warning: "bg-signal shadow-[0_0_10px_rgba(255,224,102,0.5)]",
  error: "bg-red-400 shadow-[0_0_10px_rgba(248,113,113,0.45)]",
  idle: "bg-slate-500",
};

export function StatusDot(props: { tone: StatusDotTone; pulse?: boolean; className?: string }) {
  const tone = TONE_CLASS[props.tone];
  const pulse = props.pulse ? "animate-pulseDot" : "";
  return (
    <span
      aria-hidden="true"
      className={`inline-block h-1.5 w-1.5 rounded-full ${tone} ${pulse} ${props.className ?? ""}`}
    />
  );
}
