export function connectionStateLabel(state: string, streamDisabled = false): string {
  if (streamDisabled) {
    return "半实时轮询";
  }
  if (state === "open") {
    return "已连接";
  }
  if (state === "error") {
    return "异常";
  }
  return "连接中";
}

export function streamBadgeTone(state: string, streamDisabled = false): string {
  if (streamDisabled) {
    return "text-amber-200";
  }
  if (state === "open") {
    return "text-neon";
  }
  if (state === "error") {
    return "text-red-300";
  }
  return "text-signal";
}
