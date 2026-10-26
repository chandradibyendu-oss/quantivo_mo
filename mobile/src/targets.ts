export type TargetPrice = { label: string; price: string };

/** The final published price is Last. T2 appears only when a price sits between T1 and Last. */
export function shownTargets(targets: TargetPrice[]): TargetPrice[] {
  if (targets.length === 0) {
    return [];
  }
  if (targets.length === 1) {
    return [{ label: "Last", price: targets[0].price }];
  }
  return targets.map((target, index) => ({
    label: index === targets.length - 1 ? "Last" : `T${index + 1}`,
    price: target.price,
  }));
}
