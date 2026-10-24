import { View } from "react-native";

import { colors } from "@/ui";

export function ChartMark() {
  return (
    <View style={{ width: 22, height: 20, flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
      <Stick body={12} wick={18} up />
      <Stick body={8} wick={16} up={false} />
      <Stick body={14} wick={18} up />
    </View>
  );
}

function Stick({ body, wick, up }: { body: number; wick: number; up: boolean }) {
  const color = up ? colors.buy : colors.sell;
  return (
    <View style={{ width: 6, height: wick, alignItems: "center", justifyContent: "center" }}>
      <View style={{ position: "absolute", width: 1, height: wick, backgroundColor: color }} />
      <View style={{ width: 6, height: body, backgroundColor: color, borderRadius: 1 }} />
    </View>
  );
}
