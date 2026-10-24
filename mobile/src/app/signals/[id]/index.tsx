import { Link, router, useLocalSearchParams } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, Text, View } from "react-native";

import { api, ApiRequestError } from "@/api";
import { GuideMark } from "@/guide";
import { ChartMark } from "@/marks";
import { quoteTone } from "@/quote";
import { AppShell } from "@/shell";
import type { SignalDetail } from "@/types";
import { colors, ui } from "@/ui";

export default function SignalDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [signal, setSignal] = useState<SignalDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!id) {
      return;
    }
    setSignal(await api<SignalDetail>(`/api/v1/signals/${id}`));
  }, [id]);

  useEffect(() => {
    let cancelled = false;
    load().catch((caught: unknown) => {
      if (!cancelled) {
        setError(caught instanceof ApiRequestError ? caught.message : "That call is not available.");
      }
    });
    return () => {
      cancelled = true;
    };
  }, [load]);

  async function connectBroker() {
    setBusy(true);
    setNotice(null);
    setError(null);
    try {
      await api("/api/v1/broker/connections/simulated", { method: "POST" });
      await load();
    } catch (caught) {
      setError(caught instanceof ApiRequestError ? caught.message : "The broker session was not recorded.");
    } finally {
      setBusy(false);
    }
  }

  async function prepareOrder() {
    if (!signal || signal.suggested_quantity == null) {
      return;
    }
    setBusy(true);
    setNotice(null);
    setError(null);
    try {
      await api("/api/v1/orders", {
        method: "POST",
        body: JSON.stringify({
          signal_id: signal.id,
          idempotency_key: `confirm-${Date.now()}`,
          product: signal.product_hint,
          quantity: signal.suggested_quantity,
        }),
      });
    } catch (caught) {
      const message = caught instanceof ApiRequestError ? caught.message : "The order was not accepted.";
      setNotice(message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell title={signal?.symbol ?? "Call"} onBack={() => router.replace("/signals")}>
      <ScrollView contentContainerStyle={{ paddingHorizontal: 16, paddingBottom: 28 }}>
        {!signal && !error ? <ActivityIndicator style={{ marginTop: 24 }} /> : null}
        {error ? <Text style={ui.error}>{error}</Text> : null}
        {signal ? (
          <>
            <Text style={ui.meta}>
              {signal.provider_name} · {signal.scanner_name}
            </Text>
            <View style={{ flexDirection: "row", marginTop: 8 }}>
              <GuideMark code={signal.guide} label={signal.guide_label} hint={signal.guide_hint} />
            </View>
            <Text style={ui.meta}>{signal.guide_hint}</Text>
            <Text style={ui.meta}>
              {signal.horizon_raw} · {signal.channel_name} · {signal.segment} · lot {signal.lot_size}
            </Text>
            {signal.segment === "equity" && signal.guide !== "no_symbol" ? (
              <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
                <Text style={ui.ltp}>
                  {signal.quote_label ?? "Last LTP"}{" "}
                  <Text
                    style={{
                      color: quoteTone(signal.quote_state === "ready" ? signal.change_percent : null).color,
                    }}
                  >
                    {signal.quote_state === "ready" && signal.last_price ? signal.last_price : "—"}
                    {signal.quote_state === "ready" && signal.last_price
                      ? quoteTone(signal.change_percent).text
                      : ""}
                  </Text>
                </Text>
                <Link href={`/signals/${signal.id}/chart`} asChild>
                  <Pressable style={ui.chartIcon} accessibilityRole="link" accessibilityLabel={`Chart for ${signal.symbol}`}>
                    <ChartMark />
                  </Pressable>
                </Link>
              </View>
            ) : null}
            {signal.quote_state === "unconfigured" ? (
              <Text style={ui.meta}>
                The entry time, the exit time, and the last traded price need a Fyers app. The trigger below is the scanner's price.
              </Text>
            ) : null}
            {signal.quote_state === "unavailable" ? (
              <Text style={ui.meta}>Last traded price could not be read from Fyers.</Text>
            ) : null}

            <Text style={ui.section}>From Mani's</Text>
            <View style={ui.card}>
              <Text style={ui.meta}>These prices come from the scanner.</Text>
              <Text style={[ui.rowTitle, { color: signal.side === "SELL" ? colors.sell : colors.buy }]}>
                {signal.side} · trigger {signal.provider_values.trigger_price}
              </Text>
              <Text style={ui.meta}>Stop {signal.provider_values.stop_loss}</Text>
              {signal.provider_values.targets.map((target) => (
                <Text key={target.label} style={ui.meta}>
                  {target.label} {target.price}
                  {target.risk_reward ? ` · RR ${target.risk_reward}` : ""}
                </Text>
              ))}
              {signal.provider_values.note ? <Text style={ui.meta}>{signal.provider_values.note}</Text> : null}
            </View>

            <Text style={ui.section}>Quantivo quantity</Text>
            <View style={ui.card}>
              <Text style={ui.rowTitle}>
                {signal.quantivo_values.suggested_quantity ?? "None"}
              </Text>
              <Text style={ui.meta}>{signal.quantivo_values.formula}</Text>
              <Text style={ui.meta}>Maximum loss ₹{signal.quantivo_values.max_risk_inr}</Text>
              {signal.quantivo_values.unavailable_reason ? (
                <Text style={ui.error}>{signal.quantivo_values.unavailable_reason}</Text>
              ) : null}
              <Text style={ui.meta}>{signal.quantivo_values.funds_check}</Text>
            </View>

            <Text style={ui.section}>Broker</Text>
            <View style={ui.card}>
              <Text style={ui.rowTitle}>{signal.broker.status}</Text>
              <Text style={ui.meta}>{signal.broker.message}</Text>
              {signal.broker.status !== "connected" ? (
                <Pressable style={[ui.primary, { marginTop: 14 }]} disabled={busy} onPress={connectBroker}>
                  <Text style={ui.primaryText}>Connect simulated broker</Text>
                </Pressable>
              ) : null}
            </View>

            {notice ? <Text style={ui.error}>{notice}</Text> : null}
            <Pressable
              style={ui.primary}
              disabled={busy || !signal.executable || signal.suggested_quantity == null}
              onPress={prepareOrder}
            >
              <Text style={ui.primaryText}>{busy ? "Checking…" : "Prepare order"}</Text>
            </Pressable>
          </>
        ) : null}
      </ScrollView>
    </AppShell>
  );
}
