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
  const [fyersEdit, setFyersEdit] = useState(false);
  const fyersRedirect = `${API_URL.replace(/\/$/, "")}/api/v1/admin/fyers/callback`;
  const [fyersNote, setFyersNote] = useState<string | null>(null);
  const [fyersError, setFyersError] = useState(false);
  const [fyersSaving, setFyersSaving] = useState(false);
  const [fyersRemove, setFyersRemove] = useState(false);
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
  const [added, setAdded] = useState<string | null>(null);
  const [warning, setWarning] = useState<{ channelId: string; kind: "stop" | "delete" } | null>(null);

  const load = useCallback(async () => {
    const profile = await api<MeOut>("/api/v1/me");
    if (!profile.roles.includes("admin")) {
      router.replace("/signals");
      return;
    }
    const [nextLogin, nextFyers, nextClocks, nextFeeds, catalogue] = await Promise.all([
      api<TelegramLoginOut>("/api/v1/admin/telegram-login"),
      api<FyersConfigOut>("/api/v1/admin/fyers"),
      api<CallClocksOut>("/api/v1/admin/call-clocks"),
      api<FeedOut[]>("/api/v1/admin/source-channels"),
      api<ScannerOut[]>("/api/v1/scanners"),
    ]);
    setLogin(nextLogin);
    setFyers(nextFyers);
    setClocks(nextClocks);
    setIntradayMinutes(String(nextClocks.intraday_btst_minutes));
    setShortDays(String(nextClocks.short_term_days));
    setLongDays(String(nextClocks.long_term_days));
    setFeeds(nextFeeds);
    setScanners(catalogue);
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
        }),
      });
      setFyers(saved);
      setFyersAppId("");
      setFyersSecret("");
      setFyersPin("");
      setFyersEdit(false);
      setFyersError(false);
      setFyersNote("Saved. Sign in on Fyers once. This screen asks again after 15 days.");
    } catch (caught) {
      setFyersError(true);
      setFyersNote(caught instanceof ApiRequestError ? caught.message : "The Fyers app could not be saved.");
    } finally {
      setFyersSaving(false);
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
      setFyersNote("Fyers is open. Sign in there once. Come back here when it says connected. This lasts 15 days.");
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
      const saved = await api<FyersConfigOut>("/api/v1/admin/fyers", { method: "DELETE" });
      setFyers(saved);
      setFyersAppId("");
      setFyersSecret("");
      setFyersPin("");
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
                    placeholder="Fyers app id"
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
                    placeholder="Fyers app secret"
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
                    placeholder="4-digit PIN"
                    placeholderTextColor={colors.muted}
                  />
                  <Text style={ui.meta}>The PIN stays on the server so the morning token can refresh. It is not your Fyers password.</Text>
                  <Pressable
                    style={ui.primary}
                    disabled={
                      fyersSaving
                      || fyersAppId.trim().length === 0
                      || fyersSecret.trim().length === 0
                      || fyersPin.length !== 4
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
              {fyers?.app_saved && !fyers.connected ? (
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
          <Text style={[ui.label, { marginTop: 12 }]}>Display name</Text>
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
      <Text style={[ui.label, { marginTop: 12 }]}>Display name</Text>
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
      <Text style={ui.label}>Channel name</Text>
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
