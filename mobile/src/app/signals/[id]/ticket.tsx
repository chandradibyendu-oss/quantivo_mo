import { useEffect, useState } from "react";
import { Pressable, Text, TextInput, View } from "react-native";

import { api, ApiRequestError } from "@/api";
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
  const [product, setProduct] = useState<"MIS" | "CNC">(signal.product_hint === "CNC" ? "CNC" : "MIS");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [editing, setEditing] = useState(false);
  const [preview, setPreview] = useState<OrderPreview | null>(null);
  const [saved, setSaved] = useState<OrderIntent | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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

  useEffect(() => {
    if (!draft) {
      return;
    }
    const ticket = draft;
    const price = /^(?:0|[1-9]\d{0,9})(?:\.\d{1,4})?$/;
    if (!price.test(ticket.trigger) || !price.test(ticket.stop) || ticket.targets.some((target) => !price.test(target.price))) {
      setPreview(null);
      return;
    }
    const handle = setTimeout(() => {
      api<OrderPreview>("/api/v1/orders/preview", {
        method: "POST",
        body: JSON.stringify({
          signal_id: signal.id,
          side: ticket.side,
          product: ticket.product,
          trigger_price: ticket.trigger,
          stop_loss: ticket.stop,
          targets: ticket.targets,
        }),
      })
        .then((next) => setPreview(next))
        .catch((caught: unknown) => {
          setPreview(null);
          setNotice(caught instanceof ApiRequestError ? caught.message : "The quantity could not be calculated.");
        });
    }, 250);
    return () => clearTimeout(handle);
  }, [draft, signal.id]);

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

  async function confirm() {
    if (!draft || !preview?.ok || preview.quantity == null) {
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
          quantity: preview.quantity,
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
  const quantity = preview?.ok ? preview.quantity : null;
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
          <Text style={ui.meta}>Prices start from the call. Quantity follows your maximum loss.</Text>
          <PriceRow label="Trigger" value={draft.trigger} editing={editing} onChange={(trigger) => edit({ trigger })} />
          <PriceRow label="Stop" value={draft.stop} editing={editing} onChange={(stop) => edit({ stop })} />
          {draft.targets.map((target, index) => (
            <PriceRow
              key={target.label}
              label={target.label}
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
          <Text style={ui.rowTitle}>{quantity ?? "None"}</Text>
          {preview && !preview.ok && preview.reason ? <Text style={ui.error}>{preview.reason}</Text> : null}
          <Pressable onPress={() => setEditing((value) => !value)} style={ui.ghost}>
            <Text style={ui.ghostText}>{editing ? "Hide price edits" : "Edit prices"}</Text>
          </Pressable>
          <Pressable style={[ui.primary, { backgroundColor: draft.side === "SELL" ? colors.sell : colors.buy }]} disabled={busy || quantity == null} onPress={confirm}>
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
