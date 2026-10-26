import { router, useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { ActivityIndicator, Linking, Pressable, ScrollView, Text, TextInput, View } from "react-native";

import { API_URL, api, ApiRequestError } from "@/api";
import { useAuth } from "@/auth";
import { AppShell } from "@/shell";
import type {
  ChannelLookupOut,
  ChannelMatch,
  FeedKind,
  CallClocksOut,
  FeedOut,
  FyersConfigOut,
  FyersConnectOut,
  KiteAppOut,
  AdminOrderRow,
  MeOut,
  ScannerOut,
  TelegramLoginOut,
} from "@/types";
import { colors, ui } from "@/ui";

type Draft = {
  kind: FeedKind;
  status: "active" | "inactive";
  displayName: string;
  channelName: string;
  channelId: string;
  pollLimit: string;
  url: string;
  pollSeconds: string;
  authEnv: string;
};

function draftFrom(feed: FeedOut): Draft {
  const options = feed.options;
  return {
    kind: feed.kind,
    status: feed.status,
    displayName: feed.channel_name,
    channelName: "",
    channelId: String(options.channel_id ?? ""),
    pollLimit: String(options.poll_limit ?? 40),
    url: String(options.url ?? ""),
    pollSeconds: String(options.poll_seconds ?? 60),
    authEnv: String(options.auth_env ?? ""),
  };
}

function optionsFor(draft: Draft): Record<string, string | number> {
  if (draft.kind === "none") {
    return {};
  }
  if (draft.kind === "telegram") {
    return {
      channel_id: draft.channelId.trim(),
      parser: "equity_calls",
      poll_limit: Number(draft.pollLimit),
    };
  }
  const body: Record<string, string | number> = {
    url: draft.url.trim(),
    method: "GET",
    poll_seconds: Number(draft.pollSeconds),
  };
  if (draft.authEnv.trim()) {
    body.auth_env = draft.authEnv.trim();
  }
  return body;
}

export default function AdminScreen() {
  const { userId, ready } = useAuth();
  const [login, setLogin] = useState<TelegramLoginOut | null>(null);
  const [fyers, setFyers] = useState<FyersConfigOut | null>(null);
  const [clocks, setClocks] = useState<CallClocksOut | null>(null);
  const [intradayMinutes, setIntradayMinutes] = useState("30");
  const [shortDays, setShortDays] = useState("30");
  const [longDays, setLongDays] = useState("30");
  const [clockNote, setClockNote] = useState<string | null>(null);
  const [clockError, setClockError] = useState(false);
  const [clockSaving, setClockSaving] = useState(false);
  const [fyersAppId, setFyersAppId] = useState("");
  const [fyersSecret, setFyersSecret] = useState("");
  const [fyersPin, setFyersPin] = useState("");
  const [fyersClient, setFyersClient] = useState("");
  const [fyersTotp, setFyersTotp] = useState("");
  const [fyersEdit, setFyersEdit] = useState(false);
  const fyersRedirect = `${API_URL.replace(/\/$/, "")}/api/v1/admin/fyers/callback`;
  const [fyersNote, setFyersNote] = useState<string | null>(null);
  const [fyersError, setFyersError] = useState(false);
  const [fyersSaving, setFyersSaving] = useState(false);
  const [fyersRemove, setFyersRemove] = useState(false);
  const [kite, setKite] = useState<KiteAppOut | null>(null);
  const [kiteKey, setKiteKey] = useState("");
  const [kiteSecret, setKiteSecret] = useState("");
  const [kiteEdit, setKiteEdit] = useState(false);
  const kiteRedirect = `${API_URL.replace(/\/$/, "")}/api/v1/broker/zerodha/callback`;
  const [kiteNote, setKiteNote] = useState<string | null>(null);
  const [kiteError, setKiteError] = useState(false);
  const [kiteSaving, setKiteSaving] = useState(false);
  const [kiteRemove, setKiteRemove] = useState(false);
  const [feeds, setFeeds] = useState<FeedOut[]>([]);
  const [scanners, setScanners] = useState<ScannerOut[]>([]);
  const [channelScannerId, setChannelScannerId] = useState("");
  const [providerName, setProviderName] = useState("");
  const [scannerName, setScannerName] = useState("");
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<{ channelId: string; text: string; error: boolean } | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [newSegment, setNewSegment] = useState<"equity" | "fno" | "commodity">("equity");
  const [adding, setAdding] = useState(false);
  const [scannerDrafts, setScannerDrafts] = useState<Record<string, string>>({});
  const [savingScanner, setSavingScanner] = useState<string | null>(null);
  const [scannerNote, setScannerNote] = useState<{ id: string; text: string; error: boolean } | null>(null);
  const [added, setAdded] = useState<string | null>(null);
  const [warning, setWarning] = useState<{ channelId: string; kind: "stop" | "delete" } | null>(null);
  const [orders, setOrders] = useState<AdminOrderRow[]>([]);
  const [orderTarget, setOrderTarget] = useState<AdminOrderRow | null>(null);
  const [orderBusy, setOrderBusy] = useState(false);
  const [orderNote, setOrderNote] = useState<string | null>(null);
  const [orderError, setOrderError] = useState(false);

  const load = useCallback(async () => {
    const profile = await api<MeOut>("/api/v1/me");
    if (!profile.roles.includes("admin")) {
      router.replace("/signals");
      return;
    }
    const [nextLogin, nextFyers, nextKite, nextClocks, nextFeeds, catalogue, nextOrders] = await Promise.all([
      api<TelegramLoginOut>("/api/v1/admin/telegram-login"),
      api<FyersConfigOut>("/api/v1/admin/fyers"),
      api<KiteAppOut>("/api/v1/admin/zerodha"),
      api<CallClocksOut>("/api/v1/admin/call-clocks"),
      api<FeedOut[]>("/api/v1/admin/source-channels"),
      api<ScannerOut[]>("/api/v1/scanners"),
      api<AdminOrderRow[]>("/api/v1/admin/orders"),
    ]);
    setLogin(nextLogin);
    applyFyers(nextFyers);
    setKite(nextKite);
    setClocks(nextClocks);
    setIntradayMinutes(String(nextClocks.intraday_btst_minutes));
    setShortDays(String(nextClocks.short_term_days));
    setLongDays(String(nextClocks.long_term_days));
    setFeeds(nextFeeds);
    setOrders(nextOrders);
    setScanners(catalogue);
    setScannerDrafts((current) => {
      const next = { ...current };
      for (const scanner of catalogue) {
        if (next[scanner.id] === undefined) {
          next[scanner.id] = scanner.name;
        }
      }
      return next;
    });
    setChannelScannerId((current) => current || catalogue[0]?.id || "");
    setDrafts((current) => {
      const next = { ...current };
      for (const feed of nextFeeds) {
        if (!next[feed.channel_id]) {
          next[feed.channel_id] = draftFrom(feed);
        }
      }
      return next;
    });
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
      (async () => {
        try {
          await load();
        } catch (caught) {
          if (!cancelled) {
            setError(caught instanceof ApiRequestError ? caught.message : "The configuration could not be loaded.");
          }
        }
      })();
      return () => {
        cancelled = true;
      };
    }, [load, ready, userId]),
  );

  async function removeOrder(order: AdminOrderRow) {
    setOrderBusy(true);
    setOrderNote(null);
    setOrderError(false);
    try {
      await api(`/api/v1/admin/orders/${order.id}`, { method: "DELETE" });
      setOrders((current) => current.filter((item) => item.id !== order.id));
      setOrderTarget(null);
      setOrderNote(`Removed the saved ${order.side === "BUY" ? "buy" : "sell"} of ${order.symbol}. The call stays.`);
    } catch (caught) {
      setOrderError(true);
      setOrderNote(caught instanceof ApiRequestError ? caught.message : "The saved order could not be removed.");
    } finally {
      setOrderBusy(false);
    }
  }

  function update(channelId: string, patch: Partial<Draft>) {
    setDrafts((current) => ({ ...current, [channelId]: { ...current[channelId], ...patch } }));
    setFeedback((current) => (current?.channelId === channelId ? null : current));
  }

  async function save(feed: FeedOut) {
    const draft = drafts[feed.channel_id];
    if (!draft) {
      return;
    }
    if (draft.status === "inactive" && feed.status === "active") {
      setWarning({ channelId: feed.channel_id, kind: "stop" });
      return;
    }
    setWarning(null);
    await persist(feed, draft);
  }

  async function persist(feed: FeedOut, draft: Draft) {
    setSaving(feed.channel_id);
    setFeedback(null);
    try {
      const named = draft.displayName.trim();
      if (named && named !== feed.channel_name) {
        await api<FeedOut>(`/api/v1/admin/source-channels/${feed.channel_id}`, {
          method: "PUT",
          body: JSON.stringify({ name: named }),
        });
      }
      const saved = await api<FeedOut>(`/api/v1/admin/source-channels/${feed.channel_id}/feed`, {
        method: "PUT",
        body: JSON.stringify({
          kind: draft.kind,
          status: draft.status,
          options: optionsFor(draft),
        }),
      });
      setFeeds((current) => current.map((row) => (row.channel_id === saved.channel_id ? saved : row)));
      setDrafts((current) => ({
        ...current,
        [saved.channel_id]: {
          ...draftFrom(saved),
          displayName: named || saved.channel_name,
          channelName: draft.channelName,
        },
      }));
      const storedId = String(saved.options.channel_id ?? "");
      const stopped = draft.status === "inactive" && feed.status === "active";
      const text = stopped
        ? `${feed.channel_name} is stopped. The channel and its stored calls stay.`
        : storedId
          ? `Configuration saved. Channel id ${storedId} is stored.`
          : "Configuration saved.";
      setFeedback({ channelId: saved.channel_id, text, error: false });
    } catch (caught) {
      setFeedback({
        channelId: feed.channel_id,
        text: caught instanceof ApiRequestError ? caught.message : "The channel could not be saved.",
        error: true,
      });
    } finally {
      setSaving(null);
    }
  }

  async function remove(feed: FeedOut) {
    setSaving(feed.channel_id);
    setWarning(null);
    setFeedback(null);
    try {
      await api(`/api/v1/admin/source-channels/${feed.channel_id}`, { method: "DELETE" });
      setFeeds((current) => current.filter((row) => row.channel_id !== feed.channel_id));
      setAdded(`${feed.channel_name} is deleted.`);
    } catch (caught) {
      setFeedback({
        channelId: feed.channel_id,
        text: caught instanceof ApiRequestError ? caught.message : "The channel could not be deleted.",
        error: true,
      });
    } finally {
      setSaving(null);
    }
  }

  async function addChannel() {
    setAdding(true);
    setAdded(null);
    setError(null);
    try {
      const created = await api<FeedOut>("/api/v1/admin/source-channels", {
        method: "POST",
        body: JSON.stringify({
          name: newName.trim(),
          segment: newSegment,
          scanner_id: channelScannerId || null,
        }),
      });
      setNewName("");
      setAdded(`${created.channel_name} added. Traders register for it separately. Its feed starts as sample.`);
      await load();
    } catch (caught) {
      setError(caught instanceof ApiRequestError ? caught.message : "The channel could not be added.");
    } finally {
      setAdding(false);
    }
  }

  function clockValue(raw: string): number | null {
    if (!/^\d+$/.test(raw.trim())) return null;
    return Number(raw.trim());
  }

  async function saveClocks() {
    const intraday = clockValue(intradayMinutes);
    const shortTerm = clockValue(shortDays);
    const longTerm = clockValue(longDays);
    if (intraday == null || shortTerm == null || longTerm == null) {
      setClockError(true);
      setClockNote("Enter a whole number for each clock.");
      return;
    }
    setClockSaving(true);
    setClockNote(null);
    try {
      const saved = await api<CallClocksOut>("/api/v1/admin/call-clocks", {
        method: "PUT",
        body: JSON.stringify({
          intraday_btst_minutes: intraday,
          short_term_days: shortTerm,
          long_term_days: longTerm,
        }),
      });
      setClocks(saved);
      setIntradayMinutes(String(saved.intraday_btst_minutes));
      setShortDays(String(saved.short_term_days));
      setLongDays(String(saved.long_term_days));
      setClockError(false);
      setClockNote("Saved. The next refresh uses these clocks.");
    } catch (caught) {
      setClockError(true);
      setClockNote(caught instanceof ApiRequestError ? caught.message : "The clocks could not be saved.");
    } finally {
      setClockSaving(false);
    }
  }

  function applyFyers(saved: FyersConfigOut) {
    setFyers(saved);
    setFyersAppId(saved.app_id ?? "");
    setFyersClient(saved.client_id ?? "");
    setFyersSecret("");
    setFyersPin("");
    setFyersTotp("");
  }

  async function saveFyers() {
    setFyersSaving(true);
    setFyersNote(null);
    setFyersRemove(false);
    try {
      const saved = await api<FyersConfigOut>("/api/v1/admin/fyers", {
        method: "PUT",
        body: JSON.stringify({
          app_id: fyersAppId.trim(),
          app_secret: fyersSecret.trim(),
          pin: fyersPin.trim(),
          redirect_uri: fyersRedirect,
          client_id: fyersClient.trim(),
          totp_key: fyersTotp.trim(),
        }),
      });
      applyFyers(saved);
      setFyersEdit(false);
      setFyersError(false);
      setFyersNote(
        saved.totp_saved
          ? "Saved. The server signs in after 6:30 AM IST. Restart the API once so this process loads the key."
          : "Saved. Add the Fyers client id and TOTP key, or sign in on Fyers.",
      );
    } catch (caught) {
      setFyersError(true);
      setFyersNote(caught instanceof ApiRequestError ? caught.message : "The Fyers app could not be saved.");
    } finally {
      setFyersSaving(false);
    }
  }

  async function saveKite() {
    setKiteSaving(true);
    setKiteNote(null);
    setKiteRemove(false);
    try {
      const saved = await api<KiteAppOut>("/api/v1/admin/zerodha", {
        method: "PUT",
        body: JSON.stringify({
          api_key: kiteKey.trim(),
          api_secret: kiteSecret.trim(),
          redirect_uri: kiteRedirect,
        }),
      });
      setKite(saved);
      setKiteKey("");
      setKiteSecret("");
      setKiteEdit(false);
      setKiteError(false);
      setKiteNote("Saved. Traders sign in on Zerodha from Account. The session ends at 6:00 AM IST.");
    } catch (caught) {
      setKiteError(true);
      setKiteNote(caught instanceof ApiRequestError ? caught.message : "The Kite app could not be saved.");
    } finally {
      setKiteSaving(false);
    }
  }

  async function removeKite() {
    setKiteSaving(true);
    setKiteNote(null);
    try {
      setKite(await api<KiteAppOut>("/api/v1/admin/zerodha", { method: "DELETE" }));
      setKiteRemove(false);
      setKiteEdit(false);
      setKiteError(false);
      setKiteNote("Removed. Traders sign in again after a Kite app is saved.");
    } catch (caught) {
      setKiteError(true);
      setKiteNote(caught instanceof ApiRequestError ? caught.message : "The Kite app could not be removed.");
    } finally {
      setKiteSaving(false);
    }
  }

  async function signInFyers() {
    setFyersSaving(true);
    setFyersNote(null);
    setFyersRemove(false);
    try {
      const started = await api<FyersConnectOut>("/api/v1/admin/fyers/connect", { method: "POST" });
      await Linking.openURL(started.url);
      setFyersError(false);
      setFyersNote("Fyers is open. Sign in there. The access token lasts until 6:30 AM IST.");
    } catch (caught) {
      setFyersError(true);
      setFyersNote(caught instanceof ApiRequestError ? caught.message : "Fyers could not be opened.");
    } finally {
      setFyersSaving(false);
    }
  }

  async function removeFyers() {
    setFyersSaving(true);
    setFyersNote(null);
    try {
      applyFyers(await api<FyersConfigOut>("/api/v1/admin/fyers", { method: "DELETE" }));
      setFyersEdit(false);
      setFyersRemove(false);
      setFyersError(false);
      setFyersNote("Removed. Last traded price stays blank until a Fyers app is saved and signed in again.");
    } catch (caught) {
      setFyersError(true);
      setFyersNote(caught instanceof ApiRequestError ? caught.message : "The Fyers app could not be removed.");
    } finally {
      setFyersSaving(false);
    }
  }

  async function saveScanner(scanner: ScannerOut) {
    const named = (scannerDrafts[scanner.id] ?? scanner.name).trim();
    if (!named) {
      setScannerNote({ id: scanner.id, text: "Enter a scanner name.", error: true });
      return;
    }
    setSavingScanner(scanner.id);
    setScannerNote(null);
    try {
      const saved = await api<{ id: string; name: string; provider_name: string }>(
        `/api/v1/admin/scanners/${scanner.id}`,
        { method: "PUT", body: JSON.stringify({ name: named }) },
      );
      setScanners((current) =>
        current.map((item) => (item.id === saved.id ? { ...item, name: saved.name } : item)),
      );
      setFeeds((current) =>
        current.map((feed) =>
          feed.scanner_id === saved.id ? { ...feed, scanner_name: saved.name } : feed,
        ),
      );
      setScannerDrafts((current) => ({ ...current, [saved.id]: saved.name }));
      setScannerNote({ id: saved.id, text: `${saved.name} saved.`, error: false });
    } catch (caught) {
      setScannerNote({
        id: scanner.id,
        text: caught instanceof ApiRequestError ? caught.message : "The scanner could not be saved.",
        error: true,
      });
    } finally {
      setSavingScanner(null);
    }
  }

  async function addScanner() {
    setAdding(true);
    setAdded(null);
    setError(null);
    try {
      const created = await api<{ id: string; name: string; provider_name: string }>("/api/v1/admin/scanners", {
        method: "POST",
        body: JSON.stringify({ provider_name: providerName.trim(), name: scannerName.trim() }),
      });
      setProviderName("");
      setScannerName("");
      setAdded(`${created.provider_name} · ${created.name} added. Add a channel under it next.`);
      await load();
      setChannelScannerId(created.id);
    } catch (caught) {
      setError(caught instanceof ApiRequestError ? caught.message : "The scanner could not be added.");
    } finally {
      setAdding(false);
    }
  }

  if (!ready || !userId || ((!login || !fyers || !clocks) && !error)) {
    return (
      <AppShell title="Admin">
        <ActivityIndicator style={{ marginTop: 24 }} />
      </AppShell>
    );
  }

  return (
    <AppShell title="Admin">
      <ScrollView contentContainerStyle={{ paddingHorizontal: 16, paddingBottom: 28 }}>
        <Text style={ui.lead}>
          A provider can have more than one scanner. Each scanner has its own channels. One Telegram login is shared by every Telegram channel.
        </Text>
        {error ? <Text style={ui.error}>{error}</Text> : null}
        <Text style={ui.section}>Global</Text>
        <View style={ui.card}>
          <Text style={ui.rowTitle}>Telegram login</Text>
          <Text style={ui.meta}>{login?.status === "present" ? "Present on this worker" : "Not set on this worker"}</Text>
          <Text style={ui.meta}>{login?.detail}</Text>
        </View>
        <View style={ui.card}>
          <Text style={ui.rowTitle}>How long a call stays actionable</Text>
          <Text style={ui.meta}>
            Intraday and BTST use minutes. Short term and long term use days. At 30 days those two match expiry, so the chip says Expired. A shorter number marks the call Stale sooner. Intraday to 7 days expires 7 days after the post.
          </Text>
          <Text style={[ui.label, { marginTop: 12 }]}>Intraday and BTST, minutes</Text>
          <TextInput
            style={ui.input}
            value={intradayMinutes}
            onChangeText={(value) => {
              setIntradayMinutes(value);
              setClockNote(null);
            }}
            keyboardType="number-pad"
            placeholder="30"
            placeholderTextColor={colors.muted}
          />
          <Text style={ui.label}>Short term, days</Text>
          <TextInput
            style={ui.input}
            value={shortDays}
            onChangeText={(value) => {
              setShortDays(value);
              setClockNote(null);
            }}
            keyboardType="number-pad"
            placeholder="30"
            placeholderTextColor={colors.muted}
          />
          <Text style={ui.label}>Long term, days</Text>
          <TextInput
            style={ui.input}
            value={longDays}
            onChangeText={(value) => {
              setLongDays(value);
              setClockNote(null);
            }}
            keyboardType="number-pad"
            placeholder="30"
            placeholderTextColor={colors.muted}
          />
          <Pressable style={ui.primary} disabled={clockSaving} onPress={() => void saveClocks()}>
            <Text style={ui.primaryText}>{clockSaving ? "Saving…" : "Save clocks"}</Text>
          </Pressable>
          {clockNote ? (
            <Text style={[ui.meta, { color: clockError ? colors.danger : colors.accent, marginTop: 12 }]}>
              {clockNote}
            </Text>
          ) : null}
        </View>
        <View style={ui.card}>
          <Text style={ui.rowTitle}>Fyers quotes</Text>
          <Text style={ui.meta}>
            {fyers?.connected ? "Connected" : fyers?.app_saved ? "Sign-in needed" : "Not set"}
          </Text>
          <Text style={ui.meta}>{fyers?.detail}</Text>
          {fyers?.app_saved ? (
            <>
              <Text style={ui.meta}>{fyers.app_id ? `App id ${fyers.app_id}` : "App id saved"}</Text>
              <Text style={ui.meta}>{fyers.client_id ? `Client id ${fyers.client_id}` : "Client id not saved"}</Text>
              <Text style={ui.meta}>{fyers.totp_saved ? "TOTP key saved" : "TOTP key not saved"}</Text>
            </>
          ) : null}
          {fyersRemove ? (
            <Warning
              title="Remove the Fyers app?"
              body="Actionable calls will stop showing last traded price until the Fyers app is saved and signed in again."
              confirmLabel="Remove Fyers app"
              cancelLabel="Keep the Fyers app"
              busy={fyersSaving}
              onCancel={() => setFyersRemove(false)}
              onConfirm={() => void removeFyers()}
            />
          ) : (
            <>
              {!fyers?.app_saved || fyersEdit ? (
                <>
                  <Text style={[ui.label, { marginTop: 12 }]}>Callback URL</Text>
                  <Text selectable style={ui.meta}>{fyersRedirect}</Text>
                  <Text style={ui.meta}>Register this exact URL on the Fyers app before you save.</Text>
                  <Text style={ui.label}>App id</Text>
                  <TextInput
                    style={ui.input}
                    value={fyersAppId}
                    onChangeText={(value) => {
                      setFyersAppId(value);
                      setFyersNote(null);
                    }}
                    autoCapitalize="none"
                    autoCorrect={false}
                    placeholder={fyers?.app_saved ? "Saved app id" : "Fyers app id"}
                    placeholderTextColor={colors.muted}
                  />
                  <Text style={ui.label}>App secret</Text>
                  <TextInput
                    style={ui.input}
                    value={fyersSecret}
                    onChangeText={(value) => {
                      setFyersSecret(value);
                      setFyersNote(null);
                    }}
                    autoCapitalize="none"
                    autoCorrect={false}
                    secureTextEntry
                    placeholder={fyers?.app_saved ? "Saved. Leave blank to keep it." : "Fyers app secret"}
                    placeholderTextColor={colors.muted}
                  />
                  <Text style={ui.label}>Fyers PIN</Text>
                  <TextInput
                    style={ui.input}
                    value={fyersPin}
                    onChangeText={(value) => {
                      setFyersPin(value.replace(/\D/g, "").slice(0, 4));
                      setFyersNote(null);
                    }}
                    keyboardType="number-pad"
                    secureTextEntry
                    placeholder={fyers?.app_saved ? "Saved. Leave blank to keep it." : "4-digit PIN"}
                    placeholderTextColor={colors.muted}
                  />
                  <Text style={ui.meta}>
                    {fyers?.app_saved
                      ? "The secret and PIN stay on the server. Leave a field blank to keep the saved value."
                      : "The PIN stays on the server. It is not your Fyers password."}
                  </Text>
                  <Text style={ui.label}>Fyers client id</Text>
                  <TextInput
                    style={ui.input}
                    value={fyersClient}
                    onChangeText={(value) => {
                      setFyersClient(value.toUpperCase());
                      setFyersNote(null);
                    }}
                    autoCapitalize="characters"
                    autoCorrect={false}
                    placeholder="Client id from the Fyers login page"
                    placeholderTextColor={colors.muted}
                  />
                  <Text style={ui.label}>TOTP key</Text>
                  <TextInput
                    style={ui.input}
                    value={fyersTotp}
                    onChangeText={(value) => {
                      setFyersTotp(value.replace(/\s/g, "").toUpperCase());
                      setFyersNote(null);
                    }}
                    autoCapitalize="characters"
                    autoCorrect={false}
                    secureTextEntry
                    placeholder={
                      fyers?.totp_saved
                        ? "Saved. Leave blank to keep it."
                        : "External TOTP key, not a 6-digit code"
                    }
                    placeholderTextColor={colors.muted}
                  />
                  <Text style={ui.meta}>
                    Save both once. After 6:30 AM IST the server signs in with this key and the PIN.
                  </Text>
                  <Pressable
                    style={ui.primary}
                    disabled={
                      fyersSaving
                      || (!fyers?.app_saved && (
                        fyersAppId.trim().length === 0
                        || fyersSecret.trim().length === 0
                        || fyersPin.length !== 4
                      ))
                      || (Boolean(fyers?.app_saved) && fyersPin.length > 0 && fyersPin.length !== 4)
                      || !(
                        (fyersClient.trim().length === 0 && fyersTotp.trim().length === 0)
                        || (fyersClient.trim().length > 0 && fyersTotp.trim().length > 0)
                        || Boolean(fyers?.totp_saved && fyersTotp.trim().length === 0)
                      )
                    }
                    onPress={() => void saveFyers()}
                  >
                    <Text style={ui.primaryText}>{fyersSaving ? "Saving…" : "Save Fyers app"}</Text>
                  </Pressable>
                </>
              ) : (
                <Pressable style={ui.ghost} disabled={fyersSaving} onPress={() => setFyersEdit(true)}>
                  <Text style={ui.ghostText}>Update the Fyers app</Text>
                </Pressable>
              )}
              {fyers?.app_saved && !fyers.totp_saved && !fyers.connected ? (
                <Pressable style={ui.primary} disabled={fyersSaving} onPress={() => void signInFyers()}>
                  <Text style={ui.primaryText}>{fyersSaving ? "Opening…" : "Sign in on Fyers"}</Text>
                </Pressable>
              ) : null}
              {fyers?.app_saved ? (
                <Pressable style={ui.ghost} disabled={fyersSaving} onPress={() => setFyersRemove(true)}>
                  <Text style={[ui.ghostText, { color: colors.danger }]}>Remove Fyers app</Text>
                </Pressable>
              ) : null}
            </>
          )}
          {fyersNote ? (
            <Text style={[ui.meta, { color: fyersError ? colors.danger : colors.accent, marginTop: 12 }]}>{fyersNote}</Text>
          ) : null}
        </View>
        <View style={ui.card}>
          <Text style={ui.rowTitle}>Zerodha trading</Text>
          <Text style={ui.meta}>{kite?.app_saved ? "Kite app saved" : "Not set"}</Text>
          <Text style={ui.meta}>{kite?.detail}</Text>
          {kiteRemove ? (
            <Warning
              title="Remove the Kite app?"
              body="Traders will need to sign in on Zerodha again after the app is saved. This build does not send an order."
              confirmLabel="Remove Kite app"
              cancelLabel="Keep the Kite app"
              busy={kiteSaving}
              onCancel={() => setKiteRemove(false)}
              onConfirm={() => void removeKite()}
            />
          ) : (
            <>
              {!kite?.app_saved || kiteEdit ? (
                <>
                  <Text style={[ui.label, { marginTop: 12 }]}>Callback URL</Text>
                  <Text selectable style={ui.meta}>{kiteRedirect}</Text>
                  <Text style={ui.meta}>Register this exact URL on the Kite Connect app before you save.</Text>
                  <Text style={ui.label}>Api key</Text>
                  <TextInput
                    style={ui.input}
                    value={kiteKey}
                    onChangeText={(value) => {
                      setKiteKey(value);
                      setKiteNote(null);
                    }}
                    autoCapitalize="none"
                    autoCorrect={false}
                    placeholder="Kite api key"
                    placeholderTextColor={colors.muted}
                  />
                  <Text style={ui.label}>Api secret</Text>
                  <TextInput
                    style={ui.input}
                    value={kiteSecret}
                    onChangeText={(value) => {
                      setKiteSecret(value);
                      setKiteNote(null);
                    }}
                    autoCapitalize="none"
                    autoCorrect={false}
                    secureTextEntry
                    placeholder="Kite api secret"
                    placeholderTextColor={colors.muted}
                  />
                  <Pressable
                    style={ui.primary}
                    disabled={kiteSaving || kiteKey.trim().length === 0 || kiteSecret.trim().length === 0}
                    onPress={() => void saveKite()}
                  >
                    <Text style={ui.primaryText}>{kiteSaving ? "Saving…" : "Save Kite app"}</Text>
                  </Pressable>
                </>
              ) : (
                <Pressable style={ui.ghost} disabled={kiteSaving} onPress={() => setKiteEdit(true)}>
                  <Text style={ui.ghostText}>Update the Kite app</Text>
                </Pressable>
              )}
              {kite?.app_saved ? (
                <Pressable style={ui.ghost} disabled={kiteSaving} onPress={() => setKiteRemove(true)}>
                  <Text style={[ui.ghostText, { color: colors.danger }]}>Remove Kite app</Text>
                </Pressable>
              ) : null}
            </>
          )}
          {kiteNote ? (
            <Text style={[ui.meta, { color: kiteError ? colors.danger : colors.accent, marginTop: 12 }]}>{kiteNote}</Text>
          ) : null}
        </View>
        <Text style={ui.section}>Saved orders</Text>
        <View style={ui.card}>
          <Text style={ui.meta}>
            These are proposed orders that were not sent to Zerodha. Deleting one removes that saved intent. The call stays.
          </Text>
          {orders.length === 0 ? <Text style={[ui.lead, { marginTop: 12 }]}>No saved orders.</Text> : null}
          {orders.map((order) =>
            orderTarget?.id === order.id ? (
              <Warning
                key={order.id}
                title={`Delete the saved ${order.side === "BUY" ? "buy" : "sell"} of ${order.symbol}?`}
                body={`${order.product} · quantity ${order.quantity} · trigger ${order.trigger_price}. Zerodha was not sent this order. The call stays. This cannot be undone.`}
                confirmLabel={`Delete ${order.symbol}`}
                cancelLabel="Keep this order"
                busy={orderBusy}
                onCancel={() => setOrderTarget(null)}
                onConfirm={() => void removeOrder(order)}
              />
            ) : (
              <View key={order.id} style={{ marginTop: 12 }}>
                <Text style={ui.rowTitle}>
                  {order.symbol} {order.side} · {order.product}
                </Text>
                <Text style={ui.meta}>
                  Quantity {order.quantity} · trigger {order.trigger_price} · stop {order.stop_loss}
                </Text>
                <Text style={ui.meta}>{order.phone_e164} · Proposed</Text>
                <Pressable style={ui.ghost} disabled={orderBusy} onPress={() => setOrderTarget(order)}>
                  <Text style={[ui.ghostText, { color: colors.danger }]}>Delete saved order</Text>
                </Pressable>
              </View>
            ),
          )}
          {orderNote ? (
            <Text style={[ui.meta, { color: orderError ? colors.danger : colors.accent, marginTop: 12 }]}>{orderNote}</Text>
          ) : null}
        </View>
        <Text style={ui.section}>Scanners</Text>
        <View style={ui.card}>
          <Text style={ui.rowTitle}>Add a scanner</Text>
          <Text style={ui.meta}>The provider name is who publishes it. The scanner name is what traders open. It starts with no channels and no price.</Text>
          <Text style={[ui.label, { marginTop: 12 }]}>Provider</Text>
          <TextInput
            style={ui.input}
            value={providerName}
            onChangeText={setProviderName}
            placeholder="Provider name"
            placeholderTextColor={colors.muted}
          />
          <Text style={ui.label}>Scanner</Text>
          <TextInput
            style={ui.input}
            value={scannerName}
            onChangeText={setScannerName}
            placeholder="Scanner name"
            placeholderTextColor={colors.muted}
          />
          <Pressable
            style={ui.primary}
            disabled={adding || providerName.trim().length === 0 || scannerName.trim().length === 0}
            onPress={addScanner}
          >
            <Text style={ui.primaryText}>{adding ? "Adding…" : "Add scanner"}</Text>
          </Pressable>
        </View>
        {scanners.map((scanner) => (
          <View key={scanner.id} style={ui.card}>
            <Text style={ui.rowTitle}>{scanner.provider_name}</Text>
            <Text style={ui.meta}>The scanner name is what traders open.</Text>
            <Text style={[ui.label, { marginTop: 12 }]}>Scanner name</Text>
            <TextInput
              style={ui.input}
              value={scannerDrafts[scanner.id] ?? scanner.name}
              onChangeText={(value) =>
                setScannerDrafts((current) => ({ ...current, [scanner.id]: value }))
              }
            />
            <Pressable
              style={ui.primary}
              disabled={savingScanner === scanner.id}
              onPress={() => saveScanner(scanner)}
            >
              <Text style={ui.primaryText}>{savingScanner === scanner.id ? "Saving…" : "Save scanner"}</Text>
            </Pressable>
            {scannerNote?.id === scanner.id ? (
              <Text style={[ui.meta, { color: scannerNote.error ? colors.danger : colors.accent, marginTop: 12 }]}>
                {scannerNote.text}
              </Text>
            ) : null}
          </View>
        ))}
        <Text style={ui.section}>Channels</Text>
        <View style={ui.card}>
          <Text style={ui.rowTitle}>Add a channel</Text>
          <Text style={ui.meta}>The name is what traders see. Choose which scanner it belongs to. A new channel has no calls until its feed is configured.</Text>
          <Text style={[ui.label, { marginTop: 12 }]}>Scanner</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8, paddingBottom: 12 }}>
            {scanners.map((scanner) => (
              <Choice
                key={scanner.id}
                label={`${scanner.provider_name} · ${scanner.name}`}
                selected={channelScannerId === scanner.id}
                onPress={() => setChannelScannerId(scanner.id)}
              />
            ))}
          </ScrollView>
          <Text style={[ui.label, { marginTop: 12 }]}>Channel name</Text>
          <TextInput
            style={ui.input}
            value={newName}
            onChangeText={(value) => {
              setNewName(value);
              setAdded(null);
            }}
            placeholder="F&O"
            placeholderTextColor={colors.muted}
          />
          <View style={{ flexDirection: "row", gap: 8, marginBottom: 12 }}>
            <Choice label="Equity" selected={newSegment === "equity"} onPress={() => setNewSegment("equity")} />
            <Choice label="F&O" selected={newSegment === "fno"} onPress={() => setNewSegment("fno")} />
            <Choice label="Commodity" selected={newSegment === "commodity"} onPress={() => setNewSegment("commodity")} />
          </View>
          <Pressable style={ui.primary} disabled={adding || newName.trim().length === 0} onPress={addChannel}>
            <Text style={ui.primaryText}>{adding ? "Adding…" : "Add channel"}</Text>
          </Pressable>
          {added ? <Text style={[ui.meta, { color: colors.accent, marginTop: 12 }]}>{added}</Text> : null}
        </View>
        {scanners.map((scanner) => {
          const rows = feeds.filter((feed) => feed.scanner_id === scanner.id);
          return (
            <View key={scanner.id}>
              <Text style={ui.section}>{scanner.provider_name} · {scanner.name}</Text>
              {rows.length === 0 ? <Text style={[ui.meta, { marginBottom: 12 }]}>No channels yet.</Text> : null}
              {rows.map((feed) => (
          <ChannelCard
            key={feed.channel_id}
            feed={feed}
            draft={drafts[feed.channel_id]}
            saving={saving === feed.channel_id}
            feedback={feedback?.channelId === feed.channel_id ? feedback : null}
            warning={warning?.channelId === feed.channel_id ? warning.kind : null}
            onChange={(patch) => update(feed.channel_id, patch)}
            onSave={() => save(feed)}
            onAskDelete={() => setWarning({ channelId: feed.channel_id, kind: "delete" })}
            onCancelWarning={() => {
              if (warning?.kind === "stop" && warning.channelId === feed.channel_id) {
                update(feed.channel_id, { status: feed.status });
              }
              setWarning(null);
            }}
            onConfirmStop={() => {
              const draft = drafts[feed.channel_id];
              if (!draft) {
                return;
              }
              setWarning(null);
              update(feed.channel_id, { status: "inactive" });
              void persist(feed, { ...draft, status: "inactive" });
            }}
            onConfirmDelete={() => remove(feed)}
          />
              ))}
            </View>
          );
        })}
      </ScrollView>
    </AppShell>
  );
}

function Warning({
  title,
  body,
  confirmLabel,
  cancelLabel = "Keep this channel",
  busy,
  onCancel,
  onConfirm,
}: {
  title: string;
  body: string;
  confirmLabel: string;
  cancelLabel?: string;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <View style={{ borderWidth: 2, borderColor: colors.danger, borderRadius: 12, padding: 12, marginBottom: 8 }}>
      <Text style={[ui.rowTitle, { color: colors.danger }]}>{title}</Text>
      <Text style={[ui.meta, { color: colors.ink, marginTop: 8 }]}>{body}</Text>
      <Pressable
        style={[ui.primary, { backgroundColor: colors.danger, marginTop: 14 }]}
        disabled={busy}
        onPress={onConfirm}
      >
        <Text style={ui.primaryText}>{busy ? "Working…" : confirmLabel}</Text>
      </Pressable>
      <Pressable style={ui.ghost} disabled={busy} onPress={onCancel}>
        <Text style={ui.ghostText}>{cancelLabel}</Text>
      </Pressable>
    </View>
  );
}

function ChannelCard({
  feed,
  draft,
  saving,
  feedback,
  warning,
  onChange,
  onSave,
  onAskDelete,
  onCancelWarning,
  onConfirmStop,
  onConfirmDelete,
}: {
  feed: FeedOut;
  draft: Draft | undefined;
  saving: boolean;
  feedback: { text: string; error: boolean } | null;
  warning: "stop" | "delete" | null;
  onChange: (patch: Partial<Draft>) => void;
  onSave: () => void;
  onAskDelete: () => void;
  onCancelWarning: () => void;
  onConfirmStop: () => void;
  onConfirmDelete: () => void;
}) {
  if (!draft) {
    return null;
  }
  const telegramAllowed = feed.segment === "equity";
  return (
    <View style={ui.card}>
      <Text style={ui.rowTitle}>
        {feed.channel_name} · {feed.segment}
      </Text>
      <Text style={ui.meta}>
        {feed.scanner_name} · {feed.reader.detail}
      </Text>
      <Text style={[ui.label, { marginTop: 12 }]}>Channel name</Text>
      <TextInput
        style={ui.input}
        value={draft.displayName}
        onChangeText={(displayName) => onChange({ displayName })}
      />
      <Text style={ui.label}>Feed</Text>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: 12 }}>
        <Choice label="Sample" selected={draft.kind === "none"} onPress={() => onChange({ kind: "none" })} />
        <Choice
          label="Telegram"
          selected={draft.kind === "telegram"}
          disabled={!telegramAllowed}
          onPress={() => onChange({ kind: "telegram" })}
        />
        <Choice label="HTTP" selected={draft.kind === "http_api"} onPress={() => onChange({ kind: "http_api" })} />
      </View>
      {telegramAllowed ? null : (
        <Text style={ui.meta}>Telegram for this segment waits until its parser exists. Sample and HTTP can be saved.</Text>
      )}
      {draft.kind === "telegram" ? (
        <>
          <ChannelNameField draft={draft} onChange={onChange} />
          <Text style={ui.meta}>Parser equity_calls. Recent posts read per pass</Text>
          <TextInput
            style={ui.input}
            value={draft.pollLimit}
            onChangeText={(pollLimit) => onChange({ pollLimit: pollLimit.replace(/\D/g, "") })}
            keyboardType="number-pad"
          />
        </>
      ) : null}
      {draft.kind === "http_api" ? (
        <>
          <Text style={ui.label}>URL</Text>
          <TextInput
            style={ui.input}
            value={draft.url}
            onChangeText={(url) => onChange({ url })}
            autoCapitalize="none"
            placeholder="https://"
            placeholderTextColor={colors.muted}
          />
          <Text style={ui.label}>Poll seconds</Text>
          <TextInput
            style={ui.input}
            value={draft.pollSeconds}
            onChangeText={(pollSeconds) => onChange({ pollSeconds: pollSeconds.replace(/\D/g, "") })}
            keyboardType="number-pad"
          />
          <Text style={ui.label}>Secret variable name</Text>
          <TextInput
            style={ui.input}
            value={draft.authEnv}
            onChangeText={(authEnv) => onChange({ authEnv })}
            autoCapitalize="characters"
            placeholder="MARKET_FEED_KEY"
            placeholderTextColor={colors.muted}
          />
          <Text style={ui.meta}>The name only. The value stays on the server. Method is GET.</Text>
        </>
      ) : null}
      <Text style={ui.label}>Status</Text>
      <View style={{ flexDirection: "row", gap: 8, marginBottom: 12 }}>
        <Choice label="Active" selected={draft.status === "active"} onPress={() => onChange({ status: "active" })} />
        <Choice label="Inactive" selected={draft.status === "inactive"} onPress={() => onChange({ status: "inactive" })} />
      </View>
      {warning === "stop" ? (
        <Warning
          title={`Stop reading ${feed.channel_name}?`}
          body={`The worker will not store new posts from this channel. The channel stays on the trader list, and ${feed.stored_calls} stored calls stay visible.`}
          confirmLabel="Stop this feed"
          busy={saving}
          onCancel={onCancelWarning}
          onConfirm={onConfirmStop}
        />
      ) : null}
      {warning === "delete" ? (
        <Warning
          title={`Delete ${feed.channel_name}?`}
          body={
            feed.stored_calls > 0
              ? `This removes the channel and ${feed.stored_calls} stored calls. Traders will no longer see it. This cannot be undone.`
              : "This removes the channel. It has no stored calls. Traders will no longer see it. This cannot be undone."
          }
          confirmLabel={`Delete ${feed.channel_name}`}
          busy={saving}
          onCancel={onCancelWarning}
          onConfirm={onConfirmDelete}
        />
      ) : null}
      {warning ? null : (
        <>
          <Pressable style={ui.primary} disabled={saving} onPress={onSave}>
            <Text style={ui.primaryText}>{saving ? "Saving…" : "Save channel"}</Text>
          </Pressable>
          <Pressable style={ui.ghost} disabled={saving} onPress={onAskDelete}>
            <Text style={[ui.ghostText, { color: colors.danger }]}>Delete channel</Text>
          </Pressable>
        </>
      )}
      {feedback ? (
        <Text style={[ui.meta, { color: feedback.error ? colors.danger : colors.accent, marginTop: 12 }]}>
          {feedback.text}
        </Text>
      ) : null}
    </View>
  );
}

function ChannelNameField({
  draft,
  onChange,
}: {
  draft: Draft;
  onChange: (patch: Partial<Draft>) => void;
}) {
  const [looking, setLooking] = useState(false);
  const [matches, setMatches] = useState<ChannelMatch[]>([]);
  const [lookupError, setLookupError] = useState<string | null>(null);

  async function findChannel() {
    setLooking(true);
    setLookupError(null);
    setMatches([]);
    try {
      const result = await api<ChannelLookupOut>("/api/v1/admin/telegram-channels/lookup", {
        method: "POST",
        body: JSON.stringify({ name: draft.channelName }),
      });
      if (result.matches.length === 1) {
        onChange({ channelId: result.matches[0].channel_id, channelName: result.matches[0].title });
        return;
      }
      if (result.matches.length === 0) {
        onChange({ channelId: "" });
        setLookupError("No joined channel has that name.");
        return;
      }
      setMatches(result.matches);
    } catch (caught) {
      setLookupError(caught instanceof ApiRequestError ? caught.message : "The channel could not be found.");
    } finally {
      setLooking(false);
    }
  }

  return (
    <>
      <Text style={ui.label}>Telegram channel</Text>
      <TextInput
        style={ui.input}
        value={draft.channelName}
        onChangeText={(channelName) => onChange({ channelName, channelId: "" })}
        autoCapitalize="words"
        placeholder="Equity Premium SEBI Reg"
        placeholderTextColor={colors.muted}
      />
      <Pressable style={[ui.primary, { marginBottom: 12 }]} disabled={looking} onPress={findChannel}>
        <Text style={ui.primaryText}>{looking ? "Finding…" : "Find channel"}</Text>
      </Pressable>
      {lookupError ? <Text style={ui.error}>{lookupError}</Text> : null}
      {matches.map((match) => (
        <Pressable
          key={match.channel_id}
          style={ui.card}
          onPress={() => {
            onChange({ channelId: match.channel_id, channelName: match.title });
            setMatches([]);
          }}
        >
          <Text style={ui.rowTitle}>{match.title}</Text>
          <Text style={ui.meta}>{match.channel_id}</Text>
        </Pressable>
      ))}
      {draft.channelId ? <Text style={ui.meta}>Channel id {draft.channelId}</Text> : null}
    </>
  );
}

function Choice({
  label,
  selected,
  disabled,
  onPress,
}: {
  label: string;
  selected: boolean;
  disabled?: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable
      disabled={disabled}
      onPress={onPress}
      style={{
        borderWidth: 2,
        borderColor: selected ? colors.accent : colors.ink,
        backgroundColor: selected ? colors.accent : colors.card,
        borderRadius: 999,
        paddingHorizontal: 14,
        minHeight: 48,
        alignItems: "center",
        justifyContent: "center",
        opacity: disabled ? 0.4 : 1,
      }}
    >
      <Text style={{ color: selected ? colors.accentInk : colors.ink, fontSize: 16, fontWeight: "800" }}>{label}</Text>
    </Pressable>
  );
}
