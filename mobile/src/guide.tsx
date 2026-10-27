import { Text, View } from "react-native";

import { ui } from "@/ui";

const tones: Record<string, { bg: string; ink: string }> = {
  waiting: { bg: "#e7f6ee", ink: "#16804A" },
  checking: { bg: "#e7e0d2", ink: "#3a4450" },
  caution: { bg: "#f6ecd4", ink: "#6d4e12" },
  not_valid: { bg: "#e7e0d2", ink: "#3a4450" },
  entry: { bg: "#d3eadc", ink: "#0d5c48" },
  t1_trail: { bg: "#e5f2ea", ink: "#0b6a34" },
  t2_trail: { bg: "#e5f2ea", ink: "#0b6a34" },
  trail: { bg: "#e5f2ea", ink: "#0b6a34" },
  final: { bg: "#e7f6ee", ink: "#0b6a34" },
  open: { bg: "#e7f6ee", ink: "#16804A" },
  stop: { bg: "#f8e6e4", ink: "#9c1d1d" },
  window_over: { bg: "#e7e0d2", ink: "#3a4450" },
  stale: { bg: "#f6ecd4", ink: "#6d4e12" },
  expired: { bg: "#E8E1D4", ink: "#626B78" },
  no_symbol: { bg: "#fffdf8", ink: "#1c2430" },
};

export function GuideMark({
  code,
  label,
  hint,
}: {
  code: string;
  label: string;
  hint: string;
}) {
  const tone = tones[code] ?? tones.window_over;
  return (
    <View
      accessibilityLabel={`${label}. ${hint}`}
      style={[ui.guide, { backgroundColor: tone.bg }]}
    >
      <View style={[ui.guideDot, { backgroundColor: tone.ink }]} />
      <Text style={[ui.guideText, { color: tone.ink }]}>{label}</Text>
    </View>
  );
}

export function StarMark({ count, hint }: { count: number; hint: string }) {
  const filled = Math.max(0, Math.min(5, count));
  const empty = 5 - filled;
  return (
    <Text
      accessibilityLabel={`${filled} of 5 stars. ${hint}`}
      style={{ fontSize: 13, letterSpacing: 0.4 }}
    >
      <Text style={{ color: "#8a6a12" }}>{"★".repeat(filled)}</Text>
      <Text style={{ color: "#c4bba8" }}>{"☆".repeat(empty)}</Text>
    </Text>
  );
}
