import { router, useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { ActivityIndicator, Linking, Pressable, ScrollView, Text, TextInput, View } from "react-native";

import { api, ApiRequestError } from "@/api";
import { useAuth } from "@/auth";
import { AppShell } from "@/shell";
import type { KiteAccountOut, KiteConnectOut, MeOut } from "@/types";
import { colors, ui } from "@/ui";

type RiskProfile = {
  capital_allocation_inr: string;
  max_risk_inr: string;
  max_quantity: number | null;
  max_exposure_inr: string | null;
  allowed_products: string[];
};

export default function AccountScreen() {
  const { userId, ready, signOut } = useAuth();
  const [me, setMe] = useState<MeOut | null>(null);
  const [name, setName] = useState("");
  const [capital, setCapital] = useState("");
  const [maxRisk, setMaxRisk] = useState("");
  const [maxQty, setMaxQty] = useState("");
  const [exposure, setExposure] = useState("");
  const [mis, setMis] = useState(true);
  const [cnc, setCnc] = useState(true);
  const [zerodha, setZerodha] = useState<KiteAccountOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const [profile, risk, kite] = await Promise.all([
      api<MeOut>("/api/v1/me"),
      api<RiskProfile>("/api/v1/me/risk-profile"),
      api<KiteAccountOut>("/api/v1/broker/zerodha"),
    ]);
    setMe(profile);
    setName(profile.display_name ?? "");
    setCapital(risk.capital_allocation_inr);
    setMaxRisk(risk.max_risk_inr);
    setMaxQty(risk.max_quantity == null ? "" : String(risk.max_quantity));
    setExposure(risk.max_exposure_inr ?? "");
    setMis(risk.allowed_products.includes("MIS"));
    setCnc(risk.allowed_products.includes("CNC"));
    setZerodha(kite);
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
          setError(caught instanceof ApiRequestError ? caught.message : "The account could not be loaded.");
        }
      });
      return () => {
        cancelled = true;
      };
    }, [load, ready, userId]),
  );

  async function saveRisk() {
    const products = [mis ? "MIS" : null, cnc ? "CNC" : null].filter((item): item is string => item != null);
    setBusy(true);
    setError(null);
    setSaved(null);
    try {
      if (name.trim()) {
        await api("/api/v1/me", { method: "PUT", body: JSON.stringify({ display_name: name.trim() }) });
      }
      await api("/api/v1/me/risk-profile", {
        method: "PUT",
        body: JSON.stringify({
          capital_allocation_inr: capital,
          max_risk_inr: maxRisk,
          max_quantity: maxQty.trim() ? Number(maxQty) : null,
          max_exposure_inr: exposure.trim() ? exposure : null,
          allowed_products: products,
        }),
      });
      setSaved("Saved.");
    } catch (caught) {
      setError(caught instanceof ApiRequestError ? caught.message : "The account could not be saved.");
    } finally {
      setBusy(false);
    }
  }

  async function signInZerodha() {
    setBusy(true);
    setError(null);
    try {
      const started = await api<KiteConnectOut>("/api/v1/broker/zerodha/connect", { method: "POST" });
      await Linking.openURL(started.url);
    } catch (caught) {
      setError(caught instanceof ApiRequestError ? caught.message : "Zerodha did not open.");
    } finally {
      setBusy(false);
    }
  }

  async function disconnectZerodha() {
    setBusy(true);
    setError(null);
    try {
      setZerodha(await api<KiteAccountOut>("/api/v1/broker/zerodha/disconnect", { method: "POST" }));
    } catch (caught) {
      setError(caught instanceof ApiRequestError ? caught.message : "Zerodha could not be disconnected.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell title="Account">
      <ScrollView contentContainerStyle={{ paddingHorizontal: 16, paddingBottom: 28 }}>
        {!me && !error ? <ActivityIndicator style={{ marginTop: 24 }} /> : null}
        {error ? <Text style={ui.error}>{error}</Text> : null}
        {me ? (
          <>
            <Text style={ui.label}>Display name</Text>
            <TextInput style={ui.input} value={name} onChangeText={setName} placeholder="Optional" placeholderTextColor={colors.muted} />
            <Text style={ui.meta}>Mobile {me.phone_e164}</Text>
            <Text style={[ui.section, { marginTop: 16 }]}>Risk</Text>
            <Text style={ui.label}>Capital set aside (₹)</Text>
            <TextInput style={ui.input} value={capital} onChangeText={setCapital} keyboardType="decimal-pad" />
            <Text style={ui.label}>Maximum loss per trade (₹)</Text>
            <TextInput style={ui.input} value={maxRisk} onChangeText={setMaxRisk} keyboardType="decimal-pad" />
            <Text style={ui.label}>Quantity cap</Text>
            <TextInput style={ui.input} value={maxQty} onChangeText={setMaxQty} keyboardType="number-pad" />
            <Text style={ui.label}>Exposure cap (₹)</Text>
            <TextInput style={ui.input} value={exposure} onChangeText={setExposure} keyboardType="decimal-pad" />
            <View style={{ flexDirection: "row", gap: 8, marginBottom: 12 }}>
              <Pressable style={[ui.chip, mis ? ui.chipOn : null]} onPress={() => setMis((current) => !current)}>
                <Text style={mis ? ui.chipTextOn : ui.chipText}>MIS</Text>
              </Pressable>
              <Pressable style={[ui.chip, cnc ? ui.chipOn : null]} onPress={() => setCnc((current) => !current)}>
                <Text style={cnc ? ui.chipTextOn : ui.chipText}>CNC</Text>
              </Pressable>
            </View>
            <Text style={ui.meta}>
              Capital set aside is not the amount at risk. Quantity uses the maximum loss.
            </Text>
            <Pressable style={[ui.primary, { marginTop: 12 }]} disabled={busy} onPress={saveRisk}>
              <Text style={ui.primaryText}>{busy ? "Saving…" : "Save account"}</Text>
            </Pressable>
            {saved ? <Text style={[ui.meta, { color: colors.accent }]}>{saved}</Text> : null}
            <Text style={[ui.section, { marginTop: 16 }]}>Zerodha</Text>
            <Text style={ui.meta}>{zerodha?.detail ?? "Zerodha is not loaded."}</Text>
            {zerodha?.app_saved && zerodha.status !== "connected" ? (
              <Pressable style={[ui.primary, { marginTop: 8 }]} disabled={busy} onPress={() => void signInZerodha()}>
                <Text style={ui.primaryText}>{busy ? "Opening…" : "Sign in on Zerodha"}</Text>
              </Pressable>
            ) : null}
            {zerodha?.status === "connected" ? (
              <Pressable style={[ui.ghost, { marginTop: 8 }]} disabled={busy} onPress={() => void disconnectZerodha()}>
                <Text style={ui.ghostText}>Disconnect Zerodha</Text>
              </Pressable>
            ) : null}
            <Pressable
              style={ui.ghost}
              onPress={async () => {
                await signOut();
                router.replace("/");
              }}
            >
              <Text style={[ui.ghostText, { color: colors.danger, fontSize: 18, fontWeight: "800" }]}>Sign out</Text>
            </Pressable>
          </>
        ) : null}
      </ScrollView>
    </AppShell>
  );
}
