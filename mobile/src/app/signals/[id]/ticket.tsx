import { useEffect, useState } from "react";
import { Pressable, Text, TextInput, View } from "react-native";

import { api, ApiRequestError } from "@/api";
import { shownTargets } from "@/targets";
import type { OrderIntent, OrderPreview, SignalDetail } from "@/types";
import { colors, ui } from "@/ui";

type Side = "BUY" | "SELL";
type Draft = {
  side: Side;
  product: "MIS" | "CNC";
  trigger: string;
  stop: string;
  targets: { label: string; price: string }[];
  key: string;
};

export function OrderTicket({ signal }: { signal: SignalDetail }) {
  const [product, setProduct] = useState<"MIS" | "CNC">("MIS");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [editing, setEditing] = useState(false);
  const [preview, setPreview] = useState<OrderPreview | null>(null);
  const [quantityText, setQuantityText] = useState(() =>
    signal.suggested_quantity == null ? "" : String(signal.suggested_quantity),
  );
  const [quantityEdited, setQuantityEdited] = useState(false);
  const [saved, setSaved] = useState<OrderIntent | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setProduct("MIS");
  }, [signal.id]);

  useEffect(() => {
    let cancelled = false;
    api<OrderIntent>(`/api/v1/orders/open?signal_id=${signal.id}`)
      .then((order) => {
        if (!cancelled) {
          setSaved(order);
        }
      })
      .catch((caught: unknown) => {
        if (!cancelled && !(caught instanceof ApiRequestError && caught.status === 404)) {
          setNotice(caught instanceof ApiRequestError ? caught.message : "The saved order could not be read.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [signal.id]);

  const quoteSide = draft?.side ?? (signal.side === "SELL" ? "SELL" : "BUY");
  const quoteProduct = draft?.product ?? product;
  const quoteTrigger = draft?.trigger ?? signal.provider_values.trigger_price;
  const quoteStop = draft?.stop ?? signal.provider_values.stop_loss;
  const quoteTargets = draft?.targets ?? signal.provider_values.targets;
  const quoteTargetsKey = quoteTargets.map((target) => `${target.label}:${target.price}`).join("|");

  useEffect(() => {
    if (!signal.executable || (!draft && signal.broker.status !== "connected")) {
      return;
    }
    const price = /^(?:0|[1-9]\d{0,9})(?:\.\d{1,4})?$/;
    if (!price.test(quoteTrigger) || !price.test(quoteStop) || quoteTargets.some((target) => !price.test(target.price))) {
      setPreview(null);
      return;
    }
    const handle = setTimeout(() => {
      api<OrderPreview>("/api/v1/orders/preview", {
        method: "POST",
        body: JSON.stringify({
          signal_id: signal.id,
          side: quoteSide,
          product: quoteProduct,
          trigger_price: quoteTrigger,
          stop_loss: quoteStop,
          targets: quoteTargets,
          quantity: /^[1-9]\d*$/.test(quantityText) ? Number(quantityText) : undefined,
        }),
      })
        .then((next) => setPreview(next))
        .catch((caught: unknown) => {
          setPreview(null);
          setNotice(caught instanceof ApiRequestError ? caught.message : "The quantity could not be calculated.");
        });
    }, 250);
    return () => clearTimeout(handle);
  }, [
    draft,
    quantityText,
    quoteProduct,
    quoteSide,
    quoteStop,
    quoteTargets,
    quoteTargetsKey,
    quoteTrigger,
    signal.broker.status,
    signal.executable,
    signal.id,
  ]);

  useEffect(() => {
    setQuantityEdited(false);
    setQuantityText(signal.suggested_quantity == null ? "" : String(signal.suggested_quantity));
  }, [signal.id]);

  useEffect(() => {
    if (quantityEdited || !preview?.ok || preview.quantity == null) {
      return;
    }
    setQuantityText(String(preview.quantity));
  }, [preview, quantityEdited]);

  function open(side: Side) {
    setNotice(null);
    setPreview(null);
    setEditing(false);
    setDraft({
      side,
      product,
      trigger: signal.provider_values.trigger_price,
      stop: signal.provider_values.stop_loss,
      targets: signal.provider_values.targets.map((target) => ({ label: target.label, price: target.price })),
      key: `intent-${Date.now()}`,
    });
  }

  function edit(patch: Partial<Draft>) {
    setDraft((current) => {
      if (!current) {
        return current;
      }
      return { ...current, ...patch, key: saved ? `intent-${Date.now()}` : current.key };
    });
    if (saved) {
      setSaved(null);
    }
  }

  function changeQuantity(value: string) {
    setQuantityEdited(true);
    setQuantityText(value.replace(/\D/g, ""));
    setDraft((current) => {
      if (!current || !saved) {
        return current;
      }
      return { ...current, key: `intent-${Date.now()}` };
    });
    if (saved) {
      setSaved(null);
    }
  }

  async function confirm() {
    if (!draft || !preview?.ok || quantity == null) {
      return;
    }
    if (!signedIn) {
      setNotice("Sign in on Zerodha before confirming. No order was saved.");
      return;
    }
    setBusy(true);
    setNotice(null);
    try {
      const order = await api<OrderIntent>("/api/v1/orders", {
        method: "POST",
        body: JSON.stringify({
          signal_id: signal.id,
          idempotency_key: draft.key,
          product: draft.product,
          quantity,
          side: draft.side,
          trigger_price: draft.trigger,
          stop_loss: draft.stop,
          targets: draft.targets,
        }),
      });
      setSaved(order);
      setEditing(false);
    } catch (caught) {
      setNotice(caught instanceof ApiRequestError ? caught.message : "The order was not saved.");
    } finally {
      setBusy(false);
    }
  }

  const ready = signal.executable && signal.suggested_quantity != null;
  const signedIn = signal.broker.status === "connected";
  const suggested = draft
    ? preview?.ok
      ? preview.quantity
      : null
    : signal.suggested_quantity;
  const lot = signal.lot_size > 0 ? signal.lot_size : 1;
  const parsed = /^[1-9]\d*$/.test(quantityText) ? Number(quantityText) : null;
  let quantityError: string | null = null;
  if (quantityText !== "") {
    if (parsed == null) {
      quantityError = "Enter a whole number.";
    } else if (parsed % lot !== 0) {
      quantityError = `Quantity must be a whole number of lots of ${lot}.`;
    }
  } else if (quantityEdited) {
    quantityError = "Enter a quantity.";
  }
  const quantity = quantityError == null ? parsed : null;
  const prices = draft
    ? { side: draft.side, trigger: draft.trigger, stop: draft.stop, targets: draft.targets }
    : {
        side: signal.side,
        trigger: signal.provider_values.trigger_price,
        stop: signal.provider_values.stop_loss,
        targets: signal.provider_values.targets,
      };
  const shownQuantity = ready ? quantity : signal.suggested_quantity;
  const amounts =
    shownQuantity == null
      ? null
      : tradeAmounts(prices.side, prices.trigger, prices.stop, prices.targets, shownQuantity);
  const verb = draft?.side === "SELL" ? "sell" : "buy";
  const chosen = draft?.product ?? product;

  function choose(next: "MIS" | "CNC") {
    setProduct(next);
    if (draft) {
      edit({ product: next });
    }
  }

  return (
    <View>
      {saved && !draft ? <Text style={[ui.meta, { color: colors.ink }]}>{saved.message}</Text> : null}
      {signal.suggested_quantity == null ? (
        <Text style={ui.rowTitle}>None</Text>
      ) : !ready ? (
        <View>
          <Text style={[ui.rowTitle, { marginBottom: 6 }]}>{signal.suggested_quantity}</Text>
          {amounts ? (
            <Text style={ui.meta}>
              Risk {amounts.risk}
              {amounts.rewards.length
                ? `\nReward ${amounts.rewards.map((item) => `${item.label} ${item.amount}`).join(" · ")}`
                : ""}
            </Text>
          ) : null}
        </View>
      ) : (
        <View>
          <TextInput
            value={quantityText}
            onChangeText={changeQuantity}
            keyboardType="number-pad"
            inputMode="numeric"
            accessibilityLabel="Quantity"
            style={[ui.input, { fontSize: 28, fontWeight: "700", marginBottom: 6 }]}
          />
          {amounts ? (
            <Text style={ui.meta}>
              Risk {amounts.risk}
              {amounts.rewards.length
                ? `\nReward ${amounts.rewards.map((item) => `${item.label} ${item.amount}`).join(" · ")}`
                : ""}
            </Text>
          ) : null}
          {suggested != null ? (
            <Text style={ui.meta}>
              Suggested {suggested}.{lot > 1 ? ` Use a multiple of ${lot}.` : ""}
            </Text>
          ) : null}
          {signedIn && preview?.margin_reason ? (
            <Text style={ui.error}>{preview.margin_reason}</Text>
          ) : signedIn && preview?.margin_required && preview.margin_available ? (
            <Text style={ui.meta}>
              Needs ₹{preview.margin_required}. Available ₹{preview.margin_available}.
            </Text>
          ) : null}
          {quantityError ? <Text style={ui.error}>{quantityError}</Text> : null}
        </View>
      )}
      <Text style={[ui.label, { marginTop: 12 }]}>Product</Text>
      <View style={{ flexDirection: "row", gap: 8 }}>
        {([
          ["MIS", "MIS · Intraday"],
          ["CNC", "CNC · Delivery"],
        ] as const).map(([code, label]) => {
          const selected = chosen === code;
          return (
            <Pressable
              key={code}
              accessibilityRole="button"
              accessibilityState={{ selected }}
              onPress={() => choose(code)}
              style={[ui.chip, selected ? ui.chipOn : null]}
            >
              <Text style={selected ? ui.chipTextOn : ui.chipText}>{label}</Text>
            </Pressable>
          );
        })}
      </View>
      <View style={{ flexDirection: "row", gap: 10, marginTop: 12 }}>
        <Pressable
          style={[ui.primary, { flex: 1, backgroundColor: colors.buy }]}
          disabled={!ready || busy}
          onPress={() => open("BUY")}
        >
          <Text style={ui.primaryText}>Buy</Text>
        </Pressable>
        <Pressable
          style={[ui.primary, { flex: 1, backgroundColor: colors.sell }]}
          disabled={!ready || busy}
          onPress={() => open("SELL")}
        >
          <Text style={ui.primaryText}>Sell</Text>
        </Pressable>
      </View>
      {draft ? (
        <View style={[ui.card, { marginTop: 14 }]}>
          <Text style={ui.rowTitle}>{draft.side === "BUY" ? "Buy" : "Sell"} {signal.symbol}</Text>
          <Text style={ui.meta}>Prices start from the call. Quantity starts from your maximum loss.</Text>
          <PriceRow label="Trigger" value={draft.trigger} editing={editing} onChange={(trigger) => edit({ trigger })} />
          <PriceRow label="Stop" value={draft.stop} editing={editing} onChange={(stop) => edit({ stop })} />
          {draft.targets.map((target, index) => (
            <PriceRow
              key={target.label}
              label={shownTargets(draft.targets)[index]?.label ?? target.label}
              value={target.price}
              editing={editing}
              onChange={(price) => {
                const targets = draft.targets.map((item, itemIndex) =>
                  itemIndex === index ? { ...item, price } : item,
                );
                edit({ targets });
              }}
            />
          ))}
          {preview && !preview.ok && preview.reason ? <Text style={ui.error}>{preview.reason}</Text> : null}
          <Pressable onPress={() => setEditing((value) => !value)} style={ui.ghost}>
            <Text style={ui.ghostText}>{editing ? "Hide price edits" : "Edit prices"}</Text>
          </Pressable>
          <Pressable
            style={[ui.primary, { backgroundColor: draft.side === "SELL" ? colors.sell : colors.buy }]}
            disabled={busy || quantity == null || (signedIn && Boolean(preview?.margin_reason))}
            onPress={confirm}
          >
            <Text style={ui.primaryText}>
              {busy ? "Saving…" : `Confirm ${verb}${quantity == null ? "" : ` ${quantity}`} · ${chosen}`}
            </Text>
          </Pressable>
          {saved ? <Text style={[ui.meta, { color: colors.ink, marginTop: 10 }]}>{saved.message}</Text> : null}
        </View>
      ) : null}
      {notice ? <Text style={ui.error}>{notice}</Text> : null}
    </View>
  );
}

function tradeAmounts(
  side: string,
  trigger: string,
  stop: string,
  targets: { label: string; price: string }[],
  quantity: number,
): { risk: string; rewards: { label: string; amount: string }[] } | null {
  const triggerUnits = priceUnits(trigger);
  const stopUnits = priceUnits(stop);
  if (triggerUnits == null || stopUnits == null || quantity < 1) {
    return null;
  }
  const riskUnits = stopUnits > triggerUnits ? stopUnits - triggerUnits : triggerUnits - stopUnits;
  const stopOnLosingSide = side === "SELL" ? stopUnits > triggerUnits : stopUnits < triggerUnits;
  if (!stopOnLosingSide || riskUnits <= 0n) {
    return null;
  }
  const rewards = shownTargets(targets).flatMap((target) => {
    const targetUnits = priceUnits(target.price);
    if (targetUnits == null) {
      return [];
    }
    const rewardUnits = side === "SELL" ? triggerUnits - targetUnits : targetUnits - triggerUnits;
    if (rewardUnits <= 0n) {
      return [];
    }
    return [{ label: target.label, amount: formatInr(rewardUnits * BigInt(quantity)) }];
  });
  return { risk: formatInr(riskUnits * BigInt(quantity)), rewards };
}

function priceUnits(value: string): bigint | null {
  if (!/^(?:0|[1-9]\d{0,9})(?:\.\d{1,4})?$/.test(value)) {
    return null;
  }
  const [whole, fraction = ""] = value.split(".");
  return BigInt(whole) * 10000n + BigInt((fraction + "0000").slice(0, 4));
}

function formatInr(units: bigint): string {
  const paise = (units + 50n) / 100n;
  const whole = (paise / 100n).toString();
  const fraction = (paise % 100n).toString().padStart(2, "0");
  const grouped = whole.length <= 3 ? whole : `${whole.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ",")},${whole.slice(-3)}`;
  return `₹${grouped}.${fraction}`;
}

function PriceRow({
  label,
  value,
  editing,
  onChange,
}: {
  label: string;
  value: string;
  editing: boolean;
  onChange: (value: string) => void;
}) {
  if (!editing) {
    return (
      <Text style={ui.meta}>
        {label} {value}
      </Text>
    );
  }
  return (
    <View>
      <Text style={ui.meta}>{label}</Text>
      <TextInput
        value={value}
        onChangeText={onChange}
        keyboardType="decimal-pad"
        style={ui.input}
      />
    </View>
  );
}
