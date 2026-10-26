import { router, useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, Text, TextInput, View } from "react-native";

import { api, ApiRequestError } from "@/api";
import { useAuth } from "@/auth";
import { AppShell } from "@/shell";
import type { MeOut, ScannerOut, TraderChannel } from "@/types";
import { colors, ui } from "@/ui";

export default function ScannersScreen() {
  const { userId, ready } = useAuth();
  const [scanners, setScanners] = useState<ScannerOut[]>([]);
  const [channels, setChannels] = useState<TraderChannel[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [operator, setOperator] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [draftName, setDraftName] = useState("");
  const [channelDrafts, setChannelDrafts] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    const me = await api<MeOut>("/api/v1/me");
    setOperator(me.roles.includes("admin"));
    const catalogue = await api<ScannerOut[]>("/api/v1/scanners");
    setScanners(catalogue);
    if (catalogue.some((item) => item.entitlement_status === "active")) {
      setChannels(await api<TraderChannel[]>("/api/v1/source-channels"));
    } else {
      setChannels([]);
    }
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
      load().catch((caught: unknown) => {
        if (!cancelled) {
          setError(caught instanceof ApiRequestError ? caught.message : "The catalogue could not be loaded.");
        }
      });
      return () => {
        cancelled = true;
      };
    }, [load, ready, userId]),
  );

  async function activate(scanner: ScannerOut) {
    setBusy(scanner.id);
    setError(null);
    try {
      await api(`/api/v1/scanners/${scanner.id}/activate`, { method: "POST" });
      await load();
    } catch (caught) {
      setError(caught instanceof ApiRequestError ? caught.message : "Activation failed.");
    } finally {
      setBusy(null);
    }
  }

  function openEdit(scanner: ScannerOut) {
    setEditing(scanner.id);
    setDraftName(scanner.name);
    setChannelDrafts(
      Object.fromEntries(
        channels.filter((channel) => channel.scanner_id === scanner.id).map((channel) => [channel.id, channel.name]),
      ),
    );
    setError(null);
  }

  async function saveEdit(scanner: ScannerOut) {
    const named = draftName.trim();
    if (!named) {
      setError("Enter a scanner name.");
      return;
    }
    setBusy(scanner.id);
    setError(null);
    try {
      if (named !== scanner.name) {
        await api(`/api/v1/admin/scanners/${scanner.id}`, {
          method: "PUT",
          body: JSON.stringify({ name: named }),
        });
      }
      const rows = channels.filter((channel) => channel.scanner_id === scanner.id);
      for (const channel of rows) {
        const next = (channelDrafts[channel.id] ?? channel.name).trim();
        if (next && next !== channel.name) {
          await api(`/api/v1/admin/source-channels/${channel.id}`, {
            method: "PUT",
            body: JSON.stringify({ name: next }),
          });
        }
      }
      setEditing(null);
      await load();
    } catch (caught) {
      setError(caught instanceof ApiRequestError ? caught.message : "The scanner could not be saved.");
    } finally {
      setBusy(null);
    }
  }

  async function setRegistered(channel: TraderChannel, active: boolean) {
    setBusy(channel.id);
    setError(null);
    try {
      await api(`/api/v1/source-channels/${channel.id}/registration`, {
        method: "PUT",
        body: JSON.stringify({ active }),
      });
      await load();
    } catch (caught) {
      setError(caught instanceof ApiRequestError ? caught.message : "The channel registration could not be saved.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <AppShell title="Scanners">
      <ScrollView contentContainerStyle={{ paddingHorizontal: 16, paddingBottom: 28 }}>
        <Text style={ui.lead}>Each provider keeps its own scanner. Open one to read its channels.</Text>
        {error ? <Text style={ui.error}>{error}</Text> : null}
        {scanners.length === 0 && !error ? <ActivityIndicator style={{ marginTop: 24 }} /> : null}
        {scanners.map((scanner) => (
          <View key={scanner.id} style={ui.card}>
            <View style={{ flexDirection: "row", gap: 12, alignItems: "center" }}>
              <View
                style={{
                  width: 48,
                  height: 48,
                  borderRadius: 14,
                  backgroundColor: colors.accent,
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                <Text style={{ color: colors.accentInk, fontSize: 18, fontWeight: "800" }}>{scanner.monogram}</Text>
              </View>
              <View style={{ flex: 1 }}>
                <Text style={ui.rowTitle}>{scanner.name}</Text>
                <Text style={ui.meta}>{scanner.provider_name}</Text>
              </View>
              {operator ? (
                <Pressable
                  onPress={() => (editing === scanner.id ? setEditing(null) : openEdit(scanner))}
                  style={{
                    borderWidth: 2,
                    borderColor: colors.ink,
                    borderRadius: 999,
                    paddingHorizontal: 14,
                    minHeight: 40,
                    alignItems: "center",
                    justifyContent: "center",
                  }}
                >
                  <Text style={{ color: colors.ink, fontSize: 16, fontWeight: "800" }}>
                    {editing === scanner.id ? "Cancel" : "Edit"}
                  </Text>
                </Pressable>
              ) : null}
            </View>
            {editing === scanner.id ? (
              <View>
                <Text style={[ui.label, { marginTop: 12 }]}>Scanner name</Text>
                <TextInput style={ui.input} value={draftName} onChangeText={setDraftName} />
                {channels
                  .filter((channel) => channel.scanner_id === scanner.id)
                  .map((channel) => (
                    <View key={channel.id}>
                      <Text style={ui.label}>Channel name</Text>
                      <TextInput
                        style={ui.input}
                        value={channelDrafts[channel.id] ?? channel.name}
                        onChangeText={(value) =>
                          setChannelDrafts((current) => ({ ...current, [channel.id]: value }))
                        }
                      />
                    </View>
                  ))}
                <Pressable
                  style={ui.primary}
                  disabled={busy === scanner.id}
                  onPress={() => saveEdit(scanner)}
                >
                  <Text style={ui.primaryText}>{busy === scanner.id ? "Saving…" : "Save"}</Text>
                </Pressable>
              </View>
            ) : null}
            <Text style={[ui.meta, { marginTop: 8 }]}>{scanner.description}</Text>
            <Text style={[ui.rowTitle, { marginTop: 8 }]}>
              {scanner.price_inr ? `₹${scanner.price_inr}` : "Price not listed"}
              {scanner.billing_frequency ? ` ${scanner.billing_frequency}` : ""}
            </Text>
            {scanner.entitlement_status === "active" ? (
              <Pressable
                style={[ui.primary, { marginTop: 12 }]}
                onPress={() => router.replace(`/signals?scanner=${scanner.id}`)}
              >
                <Text style={ui.primaryText}>Open feed</Text>
              </Pressable>
            ) : (
              <Pressable
                style={[ui.primary, { marginTop: 12 }]}
                disabled={busy === scanner.id}
                onPress={() => activate(scanner)}
              >
                <Text style={ui.primaryText}>{busy === scanner.id ? "Activating…" : "Activate"}</Text>
              </Pressable>
            )}
            {scanner.entitlement_status === "active"
              ? channels
                  .filter((channel) => channel.scanner_id === scanner.id)
                  .map((channel) => (
                  <View
                    key={channel.id}
                    style={{
                      flexDirection: "row",
                      alignItems: "center",
                      justifyContent: "space-between",
                      gap: 12,
                      marginTop: 12,
                      paddingTop: 12,
                      borderTopWidth: 1,
                      borderTopColor: colors.line,
                    }}
                  >
                    <Text style={ui.rowTitle}>{channel.name}</Text>
                    <Pressable
                      style={[ui.chip, channel.registered ? ui.chipOn : null]}
                      disabled={busy === channel.id}
                      onPress={() => setRegistered(channel, !channel.registered)}
                    >
                      <Text style={channel.registered ? ui.chipTextOn : ui.chipText}>
                        {channel.registered ? "Registered" : "Register"}
                      </Text>
                    </Pressable>
                  </View>
                ))
              : null}
            {scanner.entitlement_status === "active" &&
            channels.filter((channel) => channel.scanner_id === scanner.id).length === 0 ? (
              <Text style={[ui.meta, { marginTop: 8 }]}>No channels yet.</Text>
            ) : null}
          </View>
        ))}
      </ScrollView>
    </AppShell>
  );
}
