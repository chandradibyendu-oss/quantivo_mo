import { router, useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, Text, View } from "react-native";

import { api, ApiRequestError } from "@/api";
import { useAuth } from "@/auth";
import { AppShell } from "@/shell";
import type { MeOut, OrderBookRow } from "@/types";
import { colors, ui } from "@/ui";

function savedOn(value: string): string {
  return new Date(value).toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function statusLabel(status: string): string {
  if (!status) {
    return "Proposed";
  }
  return status.charAt(0).toUpperCase() + status.slice(1).replace(/_/g, " ");
}

export default function OrdersScreen() {
  const { userId, ready } = useAuth();
  const [rows, setRows] = useState<OrderBookRow[] | null>(null);
  const [operator, setOperator] = useState(false);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [book, me] = await Promise.all([api<OrderBookRow[]>("/api/v1/orders"), api<MeOut>("/api/v1/me")]);
    setRows(book);
    setOperator(me.roles.includes("admin"));
  }, []);

  async function remove(row: OrderBookRow) {
    setBusy(true);
    setError(null);
    try {
      await api(`/api/v1/admin/orders/${row.id}`, { method: "DELETE" });
      setRows((current) => (current ?? []).filter((item) => item.id !== row.id));
      setPendingId(null);
    } catch (caught) {
      setError(caught instanceof ApiRequestError ? caught.message : "The saved order could not be removed.");
    } finally {
      setBusy(false);
    }
  }

  useFocusEffect(
    useCallback(() => {
      if (!ready) {
        return;
      }
      if (!userId) {
        router.replace("/");
        return;
      }
      let cancelled = false;
      load().catch((caught: unknown) => {
        if (!cancelled) {
          setError(caught instanceof ApiRequestError ? caught.message : "Orders could not be loaded.");
        }
      });
      return () => {
        cancelled = true;
      };
    }, [load, ready, userId]),
  );

  return (
    <AppShell title="Orders">
      <ScrollView contentContainerStyle={{ paddingHorizontal: 16, paddingBottom: 28 }}>
        <Text style={ui.meta}>
          Saved orders for this account. Zerodha is not sent an order. The stop and targets stay inactive.
        </Text>
        {rows == null && !error ? <ActivityIndicator style={{ marginTop: 24 }} /> : null}
        {error ? <Text style={ui.error}>{error}</Text> : null}
        {rows && rows.length === 0 ? <Text style={[ui.meta, { marginTop: 16 }]}>No saved orders.</Text> : null}
        {rows?.map((row) => (
          <View key={row.id} style={[ui.card, { marginTop: 12 }]}>
            <Pressable onPress={() => router.push(`/signals/${row.signal_id}`)}>
              <Text style={ui.rowTitle}>
                {row.symbol} · {row.side === "BUY" ? "Buy" : "Sell"}
              </Text>
              <Text style={ui.meta}>
                {statusLabel(row.status)} · {row.product} · {row.quantity}
              </Text>
              <Text style={ui.meta}>
                Trigger {row.trigger_price} · Stop {row.stop_loss}
              </Text>
              <Text style={ui.meta}>{savedOn(row.saved_at)} IST</Text>
              <Text style={[ui.meta, { color: colors.ink, marginTop: 6 }]}>{row.message}</Text>
            </Pressable>
            {operator && row.status === "proposed" && !row.sent_to_broker ? (
              pendingId === row.id ? (
                <View style={{ marginTop: 12 }}>
                  <Text style={[ui.meta, { color: colors.ink }]}>
                    Delete this saved {row.side === "BUY" ? "buy" : "sell"}? Zerodha was not sent it. The call stays.
                  </Text>
                  <Pressable
                    style={[ui.primary, { backgroundColor: colors.danger, marginTop: 10 }]}
                    disabled={busy}
                    onPress={() => void remove(row)}
                  >
                    <Text style={ui.primaryText}>{busy ? "Removing…" : `Delete ${row.symbol}`}</Text>
                  </Pressable>
                  <Pressable style={ui.ghost} disabled={busy} onPress={() => setPendingId(null)}>
                    <Text style={ui.ghostText}>Keep this order</Text>
                  </Pressable>
                </View>
              ) : (
                <Pressable style={ui.ghost} disabled={busy} onPress={() => setPendingId(row.id)}>
                  <Text style={[ui.ghostText, { color: colors.danger }]}>Delete saved order</Text>
                </Pressable>
              )
            ) : null}
          </View>
        ))}
      </ScrollView>
    </AppShell>
  );
}
