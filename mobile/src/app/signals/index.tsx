import { Link, router, useFocusEffect, useLocalSearchParams } from "expo-router";
import { useCallback, useRef, useState } from "react";
import { ActivityIndicator, FlatList, Pressable, ScrollView, Text, View } from "react-native";

import { api, ApiRequestError } from "@/api";
import { quoteTone } from "@/quote";
import { shownTargets } from "@/targets";
import { useAuth } from "@/auth";
import { GuideMark } from "@/guide";
import { ChartMark } from "@/marks";
import { AppShell } from "@/shell";
import type { ScannerOut, SignalCard, SignalListOut, TraderChannel } from "@/types";
import { colors, ui } from "@/ui";

function ageLabel(publishedAt: string): string {
  const minutes = Math.max(0, Math.round((Date.now() - Date.parse(publishedAt)) / 60000));
  if (minutes < 1) {
    return "just now";
  }
  if (minutes < 60) {
    return minutes === 1 ? "1 min ago" : `${minutes} min ago`;
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return hours === 1 ? "1 hour ago" : `${hours} hours ago`;
  }
  const days = Math.floor(hours / 24);
  if (days < 7) {
    return days === 1 ? "1 day ago" : `${days} days ago`;
  }
  return new Date(publishedAt).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

function rememberedScanner(): string {
  try {
    return sessionStorage.getItem("quantivo.scanner") ?? "";
  } catch {
    return "";
  }
}

function rememberScanner(id: string) {
  try {
    sessionStorage.setItem("quantivo.scanner", id);
  } catch {
    // A native build has no browser session storage.
  }
}

function feedLabel(mode: SignalListOut["feed_mode"] | undefined): string {
  if (mode === "telegram") {
    return "Telegram";
  }
  if (mode === "telegram_pending") {
    return "Telegram selected, worker login not set";
  }
  return "Sample calls until Telegram is configured";
}

export default function SignalListScreen() {
  const { userId, ready } = useAuth();
  const params = useLocalSearchParams<{ scanner?: string }>();
  const requested = typeof params.scanner === "string" ? params.scanner : "";
  const [feed, setFeed] = useState<SignalListOut | null>(null);
  const [scanner, setScanner] = useState<ScannerOut | null>(null);
  const [view, setView] = useState<"actionable" | "all">("actionable");
  const [channel, setChannel] = useState("all");
  const [channels, setChannels] = useState<TraderChannel[]>([]);
  const [held, setHeld] = useState<ScannerOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [priceNote, setPriceNote] = useState(true);
  const [shown, setShown] = useState(40);
  const [shownFor, setShownFor] = useState("actionable:all");
  const channelRef = useRef("all");
  const scannerRef = useRef<ScannerOut | null>(null);
  const viewRef = useRef<"actionable" | "all">("actionable");
  const openedHistory = useRef(false);
  const seenScanner = useRef("");
  const requestSeq = useRef(0);
  const historySeq = useRef(0);
  const feedCache = useRef(new Map<string, SignalListOut>());

  const load = useCallback(async (nextView: "actionable" | "all", nextChannel: string) => {
    const seq = ++requestSeq.current;
    const historyTicket = ++historySeq.current;
    setError(null);
    const catalogue = await api<ScannerOut[]>("/api/v1/scanners");
    if (seq !== requestSeq.current) {
      return;
    }
    const remembered = rememberedScanner();
    const chosen =
      catalogue.find((item) => item.id === requested) ??
      catalogue.find((item) => item.id === remembered && item.entitlement_status === "active") ??
      catalogue.find((item) => item.entitlement_status === "active") ??
      catalogue[0] ??
      null;
    if (chosen) {
      rememberScanner(chosen.id);
    }
    scannerRef.current = chosen;
    setScanner(chosen);
    setHeld(catalogue.filter((item) => item.entitlement_status === "active"));
    if (chosen && seenScanner.current !== chosen.id) {
      seenScanner.current = chosen.id;
      openedHistory.current = false;
      feedCache.current.clear();
    }
    if (!chosen || chosen.entitlement_status !== "active") {
      setFeed(null);
      setChannels([]);
      return;
    }
    const listed = await api<TraderChannel[]>(`/api/v1/source-channels?scanner_id=${chosen.id}`);
    if (seq !== requestSeq.current) {
      return;
    }
    setChannels(listed);
    const channelQuery = nextChannel === "all" ? "" : `&channel_id=${nextChannel}`;
    const signalPath = `/api/v1/signals?scanner_id=${chosen.id}&view=`;
    let body = await api<SignalListOut>(`${signalPath}${nextView}${channelQuery}`);
    if (seq !== requestSeq.current) {
      return;
    }
    if (body.feed_mode === "mock" && chosen.provider_name === "Mani's") {
      await api("/api/v1/dev/mock-feed/sync", { method: "POST" });
      if (seq !== requestSeq.current) {
        return;
      }
      body = await api<SignalListOut>(`${signalPath}${nextView}${channelQuery}`);
    }
    if (seq !== requestSeq.current) {
      return;
    }
    viewRef.current = nextView;
    feedCache.current.set(`${nextView}:${nextChannel}`, body);
    setFeed(body);
    if (!openedHistory.current && nextChannel === "all") {
      openedHistory.current = true;
      if (nextView !== "all" && body.feed_mode !== "mock") {
        void api<SignalListOut>(`${signalPath}all`)
          .then((allBody) => {
            if (historyTicket !== historySeq.current) {
              return;
            }
            feedCache.current.set("all:all", allBody);
          })
          .catch(() => undefined);
      }
    }
  }, [requested]);

  const refreshCalls = useCallback(async () => {
    const chosen = scannerRef.current;
    if (!chosen || chosen.entitlement_status !== "active") {
      return;
    }
    const seq = ++requestSeq.current;
    const nextChannel = channelRef.current;
    const nextView = viewRef.current;
    const channelQuery = nextChannel === "all" ? "" : `&channel_id=${nextChannel}`;
    const body = await api<SignalListOut>(
      `/api/v1/signals?scanner_id=${chosen.id}&view=${nextView}${channelQuery}`,
    );
    if (seq !== requestSeq.current || channelRef.current !== nextChannel || viewRef.current !== nextView) {
      return;
    }
    feedCache.current.set(`${nextView}:${nextChannel}`, body);
    setFeed(body);
  }, []);

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
      let timer: ReturnType<typeof setInterval> | undefined;
      (async () => {
        try {
          await load(view, channelRef.current);
        } catch (caught) {
          if (!cancelled) {
            setError(caught instanceof ApiRequestError ? caught.message : "The feed could not be loaded.");
          }
        }
        if (!cancelled) {
          timer = setInterval(() => {
            void refreshCalls().catch(() => undefined);
          }, 5_000);
        }
      })();
      return () => {
        cancelled = true;
        if (timer) {
          clearInterval(timer);
        }
      };
    }, [channel, load, ready, refreshCalls, userId, view]),
  );

  function showCached(nextView: "actionable" | "all", nextChannel: string) {
    const cached = feedCache.current.get(`${nextView}:${nextChannel}`);
    if (cached) {
      setFeed(cached);
    }
  }

  function chooseView(next: "actionable" | "all") {
    if (view === next) {
      return;
    }
    viewRef.current = next;
    showCached(next, channelRef.current);
    setView(next);
  }

  function chooseChannel(id: string) {
    channelRef.current = id;
    showCached(viewRef.current, id);
    setChannel(id);
  }

  function openScanner(id: string) {
    if (scanner?.id === id) {
      return;
    }
    chooseChannel("all");
    router.replace(`/signals?scanner=${id}`);
  }

  async function register(active: boolean) {
    if (channel === "all") {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api(`/api/v1/source-channels/${channel}/registration`, {
        method: "PUT",
        body: JSON.stringify({ active }),
      });
      await load(view, channel);
    } catch (caught) {
      setError(caught instanceof ApiRequestError ? caught.message : "The channel registration could not be saved.");
    } finally {
      setBusy(false);
    }
  }

  async function activate() {
    if (!scanner) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api(`/api/v1/scanners/${scanner.id}/activate`, { method: "POST" });
      await load("actionable", "all");
      setView("actionable");
    } catch (caught) {
      setError(caught instanceof ApiRequestError ? caught.message : "Activation failed.");
    } finally {
      setBusy(false);
    }
  }

  if (!ready || !userId) {
    return (
      <AppShell title="Home">
        <ActivityIndicator style={{ marginTop: 24 }} />
      </AppShell>
    );
  }

  const needsActivation = scanner != null && scanner.entitlement_status !== "active" && feed == null;
  const scannerHeading =
    held.length > 1 ? (
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        style={ui.barTabs}
        contentContainerStyle={ui.tabRow}
      >
        {held.map((item) => {
          const selected = item.id === scanner?.id;
          return (
            <Pressable
              key={item.id}
              accessibilityRole="tab"
              accessibilityState={{ selected }}
              style={[ui.tab, selected ? ui.tabOn : null]}
              onPress={() => openScanner(item.id)}
            >
              <Text style={selected ? ui.barTabText : ui.barTabTextOff}>{item.name}</Text>
            </Pressable>
          );
        })}
      </ScrollView>
    ) : null;

  const PAGE = 40;
  const listKey = `${view}:${channel}`;
  if (shownFor !== listKey) {
    setShownFor(listKey);
    setShown(PAGE);
  }
  const allRows = feed && channels.length > 0 && !feed.registration_required ? feed.signals : [];
  const actionableCount = feed
    ? view === "actionable"
      ? feed.signals.length
      : Math.max(0, feed.signals.length - feed.hidden_non_actionable)
    : 0;
  const rows = allRows.slice(0, shownFor === listKey ? shown : PAGE);

  return (
    <AppShell title={scanner?.name ?? "Home"} heading={scannerHeading}>
      <FlatList
        style={{ flex: 1 }}
        data={rows}
        keyExtractor={(signal) => signal.id}
        renderItem={({ item }) => <SignalRow signal={item} />}
        initialNumToRender={12}
        maxToRenderPerBatch={8}
        windowSize={5}
        scrollEventThrottle={200}
        onScroll={(event) => {
          const { contentOffset, contentSize, layoutMeasurement } = event.nativeEvent;
          const nearEnd = contentOffset.y + layoutMeasurement.height > contentSize.height - 320;
          if (contentOffset.y > 80 && nearEnd && shown < allRows.length) {
            setShown(Math.min(shown + PAGE, allRows.length));
          }
        }}
        contentContainerStyle={{ paddingHorizontal: 16, paddingBottom: 28 }}
        ListHeaderComponent={
          <View>
            <Text style={ui.meta}>
              {scanner ? `${scanner.provider_name} · ${feedLabel(feed?.feed_mode)}` : "Loading the catalogue"}
            </Text>
            {error ? <Text style={ui.error}>{error}</Text> : null}
            {needsActivation ? (
              <View style={ui.card}>
                <Text style={ui.rowTitle}>{scanner.name}</Text>
                <Text style={ui.meta}>{scanner.description}</Text>
                <Text style={ui.meta}>
                  Catalogue price {scanner.price_inr ? `₹${scanner.price_inr}` : "not listed"}{" "}
                  {scanner.billing_frequency ?? ""}. Activation does not create a payment.
                </Text>
                <Pressable style={[ui.primary, { marginTop: 14, cursor: "pointer" }]} disabled={busy} onPress={activate}>
                  <Text style={ui.primaryText}>{busy ? "Activating…" : "Activate"}</Text>
                </Pressable>
              </View>
            ) : null}
            {feed && channels.length === 0 ? (
              <Text style={[ui.lead, { marginTop: 12 }]}>No channels yet.</Text>
            ) : null}
            {feed && channels.length > 0 ? (
              <>
                <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={ui.tabRow}>
                  <Pressable
                    accessibilityRole="tab"
                    accessibilityState={{ selected: channel === "all" }}
                    style={[ui.tab, channel === "all" ? ui.tabOn : null]}
                    onPress={() => chooseChannel("all")}
                  >
                    <Text style={channel === "all" ? ui.tabTextOn : ui.tabText}>All</Text>
                  </Pressable>
                  {channels.map((item) => (
                    <Pressable
                      key={item.id}
                      accessibilityRole="tab"
                      accessibilityState={{ selected: channel === item.id }}
                      style={[ui.tab, channel === item.id ? ui.tabOn : null]}
                      onPress={() => chooseChannel(item.id)}
                    >
                      <Text style={channel === item.id ? ui.tabTextOn : ui.tabText}>{item.name}</Text>
                    </Pressable>
                  ))}
                </ScrollView>
                <View style={ui.viewBar} accessibilityRole="tablist">
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel={`Actionable calls, ${actionableCount}`}
                    accessibilityState={{ selected: view === "actionable" }}
                    style={[ui.viewSegment, view === "actionable" ? ui.viewSegmentOn : null]}
                    onPress={() => chooseView("actionable")}
                  >
                    <Text style={view === "actionable" ? ui.viewTextOn : ui.viewText}>
                      Actionable
                      <Text style={ui.viewCount}> · {actionableCount.toLocaleString("en-IN")}</Text>
                    </Text>
                  </Pressable>
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel={
                      feed.hidden_non_actionable === 0
                        ? "All calls"
                        : `All calls, ${feed.hidden_non_actionable} closed`
                    }
                    accessibilityState={{ selected: view === "all" }}
                    style={[ui.viewSegment, ui.viewDivider, view === "all" ? ui.viewSegmentOn : null]}
                    onPress={() => chooseView("all")}
                  >
                    <Text style={view === "all" ? ui.viewTextOn : ui.viewText}>
                      All
                      {feed.hidden_non_actionable > 0 ? (
                        <Text style={ui.viewCount}> · {feed.hidden_non_actionable.toLocaleString("en-IN")}</Text>
                      ) : null}
                    </Text>
                  </Pressable>
                </View>
                {channel === "all" && feed.omitted_channels && feed.omitted_channels.length > 0 ? (
                  <Text style={ui.meta}>Not registered for {feed.omitted_channels.join(", ")}. Those calls are left out of All.</Text>
                ) : null}
                {priceNote && feed.quote_feed === "unconfigured" ? (
                  <View style={ui.note}>
                    <Text style={ui.noteText}>
                      Last traded price, and the entry and exit time, need a Fyers app. The trigger on each call is the scanner's price.
                    </Text>
                    <Pressable
                      style={ui.noteClose}
                      accessibilityRole="button"
                      accessibilityLabel="Dismiss price note"
                      onPress={() => setPriceNote(false)}
                    >
                      <Text style={{ fontSize: 18, color: colors.ink }}>×</Text>
                    </Pressable>
                  </View>
                ) : null}
                {feed.quote_feed === "unavailable" ? (
                  <Text style={ui.meta}>Last traded price could not be read from Fyers.</Text>
                ) : null}
              </>
            ) : null}
          </View>
        }
        ListFooterComponent={
          feed && channels.length > 0 ? (
            <View>
              {feed.registration_required ? (
                <View style={ui.card}>
                  <Text style={ui.rowTitle}>You are not registered for {feed.selected_channel_name}</Text>
                  <Text style={ui.meta}>This channel's calls stay hidden until you register. Registration does not create a payment.</Text>
                  <Pressable
                    style={[ui.primary, { marginTop: 14, cursor: "pointer" }]}
                    disabled={busy}
                    onPress={() => register(true)}
                  >
                    <Text style={ui.primaryText}>{busy ? "Saving…" : "Register for this channel"}</Text>
                  </Pressable>
                </View>
              ) : feed.signals.length === 0 ? (
                <Text style={ui.lead}>
                  {feed.feed_mode === "telegram_pending"
                    ? "Sample calls are hidden. Set this worker's Telegram login to load history and new posts."
                    : feed.feed_mode === "telegram"
                      ? "No channel calls in this view yet."
                      : "No calls in this view."}
                </Text>
              ) : null}
              {shown < allRows.length ? (
                <Text style={ui.meta}>Showing {shown.toLocaleString("en-IN")} of {allRows.length.toLocaleString("en-IN")}. Scroll for more.</Text>
              ) : null}
              {channel !== "all" && !feed.registration_required && channels.length > 1 ? (
                <Pressable style={[ui.ghost, { cursor: "pointer" }]} disabled={busy} onPress={() => register(false)}>
                  <Text style={ui.ghostText}>Leave this channel</Text>
                </Pressable>
              ) : null}
            </View>
          ) : undefined
        }
      />
    </AppShell>
  );
}

function quoted(signal: SignalCard): boolean {
  return signal.segment === "equity" && signal.guide !== "no_symbol";
}

function priceLine(signal: SignalCard): { label: string; price: string; color?: string; change: string } | null {
  if (!quoted(signal)) {
    return null;
  }
  const tone = quoteTone(signal.change_percent);
  return {
    label: signal.quote_label ?? "Last LTP",
    price: signal.quote_state === "ready" && signal.last_price ? signal.last_price : "—",
    color: tone.color,
    change: signal.quote_state === "ready" && signal.last_price ? tone.text : "",
  };
}

function SignalRow({ signal }: { signal: SignalCard }) {
  const sideColor = signal.side === "SELL" ? colors.sell : colors.buy;
  const traded = priceLine(signal);
  return (
    <View style={[ui.call, { flexDirection: "row", alignItems: "flex-start" }]}>
      <Link href={`/signals/${signal.id}`} asChild>
        <Pressable style={{ flex: 1, cursor: "pointer" }}>
          <View style={ui.callTop}>
            <View style={{ flex: 1, minWidth: 0, flexDirection: "row", alignItems: "center", gap: 6 }}>
              <Text style={[ui.symbol, { flexShrink: 1 }]} numberOfLines={1}>
                {signal.symbol}
              </Text>
              <Text style={[ui.side, { color: sideColor }]}>{signal.side}</Text>
              <GuideMark code={signal.guide} label={signal.guide_label} hint={signal.guide_hint} />
            </View>
            <View style={ui.qtyCol}>
              <Text style={ui.qty}>{signal.suggested_quantity ?? "—"}</Text>
              <Text style={ui.qtyUnit}>qty</Text>
            </View>
          </View>
          <Text style={ui.callMeta}>
            {signal.horizon_raw} · {signal.channel_name} · {ageLabel(signal.published_at)}
          </Text>
          <Text style={ui.callPrice}>
            {traded ? (
              <Text>
                {traded.label}{" "}
                <Text style={{ fontWeight: "700", color: traded.color }}>
                  {traded.price}
                  {traded.change}
                </Text>
                {" · "}
              </Text>
            ) : null}
            Trigger {signal.provider_values.trigger_price} · Stop {signal.provider_values.stop_loss}
            {shownTargets(signal.provider_values.targets)
              .map((target) => ` · ${target.label} ${target.price}`)
              .join("")}
          </Text>
        </Pressable>
      </Link>
      {quoted(signal) ? (
        <Link href={`/signals/${signal.id}/chart`} asChild>
          <Pressable style={ui.chartIcon} accessibilityRole="link" accessibilityLabel={`Chart for ${signal.symbol}`}>
            <ChartMark />
          </Pressable>
        </Link>
      ) : (
        <View style={ui.chartIcon} />
      )}
    </View>
  );
}
