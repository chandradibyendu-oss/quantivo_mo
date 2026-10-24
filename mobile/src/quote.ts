import { colors } from "@/ui";

export function quoteTone(percent: string | null | undefined): { color?: string; text: string } {
  if (percent == null || percent === "") {
    return { text: "" };
  }
  const value = Number(percent);
  if (!Number.isFinite(value)) {
    return { text: "" };
  }
  const body = Math.abs(value).toFixed(2);
  if (value > 0) {
    return { color: colors.buy, text: ` +${body}%` };
  }
  if (value < 0) {
    return { color: colors.sell, text: ` -${body}%` };
  }
  return { text: ` ${body}%` };
}
