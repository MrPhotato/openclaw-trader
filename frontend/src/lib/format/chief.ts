import { asRecord, nonEmptyText, toNumber } from "./misc";

export const ROLE_LABEL: Record<string, string> = {
  pm: "PM",
  risk_trader: "RT",
  macro_event_analyst: "MEA",
  crypto_chief: "Chief",
};

export const GRADE_TONE: Record<string, string> = {
  A: "text-emerald-300",
  "A+": "text-emerald-300",
  "A-": "text-emerald-300",
  B: "text-sky-300",
  "B+": "text-sky-300",
  "B-": "text-sky-300",
  C: "text-amber-300",
  "C+": "text-amber-300",
  "C-": "text-amber-300",
  D: "text-red-400",
  "D+": "text-red-400",
  "D-": "text-red-400",
  F: "text-red-500",
};

export function normalizeRetroChallengePrompts(value: unknown): Array<{ label: string | null; text: string }> {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.flatMap((item) => {
    if (typeof item === "string" && item.trim().length > 0) {
      return [{ label: null, text: item.trim() }];
    }
    const record = asRecord(item);
    if (!record) {
      return [];
    }
    const text = nonEmptyText(record.prompt ?? record.question ?? record.text, "");
    if (!text) {
      return [];
    }
    const role = typeof record.role === "string" ? record.role.trim() : "";
    return [{ label: role ? (ROLE_LABEL[role] ?? role) : null, text }];
  });
}

export function stripLeadingOrdinal(value: string): string {
  return value.replace(/^\s*\d+\.\s*/, "").trim();
}

export function parseRoleJudgement(value: unknown): { grade: string | null; comment: string } {
  const record = asRecord(value);
  const explicitGrade = record ? nonEmptyText(record.grade, "") : "";
  const explicitComment = record ? nonEmptyText(record.comment ?? record.summary, "") : "";
  if (explicitGrade) {
    return {
      grade: explicitGrade,
      comment: explicitComment,
    };
  }
  const raw = nonEmptyText(value, "");
  const match = raw.match(/^(A[+-]?|B[+-]?|C[+-]?|D[+-]?|F)\s*(?:\|\s*(.+))?$/);
  if (match) {
    return {
      grade: match[1],
      comment: (match[2] ?? "").trim(),
    };
  }
  return {
    grade: null,
    comment: raw,
  };
}

export function chiefRetroModeLabel(roundCount: unknown): string {
  const count = toNumber(roundCount);
  if (count === null) {
    return "异步 briefs";
  }
  return `同步 ${Math.trunc(count)} 轮`;
}

export function hasTextualLearningSection(ownerSummary: string): boolean {
  return /学习指令|学习落实|学习结果|会后学习/.test(ownerSummary);
}

export function chiefLearningChainState(props: {
  ownerSummary: string;
  directives: Array<Record<string, unknown>>;
  learningResults: Array<Record<string, unknown>>;
  learningCompleted: boolean;
}): { value: string; tone: string } {
  if (props.learningResults.length > 0) {
    return {
      value: props.learningCompleted ? "已回写" : "部分回写",
      tone: props.learningCompleted ? "text-emerald-300" : "text-sky-300",
    };
  }
  if (props.directives.length > 0) {
    return {
      value: "待落实",
      tone: "text-amber-300",
    };
  }
  if (hasTextualLearningSection(props.ownerSummary)) {
    return {
      value: "仅文本提及",
      tone: "text-amber-300",
    };
  }
  if (props.learningCompleted) {
    return {
      value: "已完成",
      tone: "text-emerald-300",
    };
  }
  return {
    value: "未结构化提交",
    tone: "text-slate-200",
  };
}
