import { Redirect, router } from "expo-router";
import { useState } from "react";
import { Pressable, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { ApiRequestError } from "@/api";
import { useAuth } from "@/auth";
import { ui } from "@/ui";

export default function CodeScreen() {
  const { pending, userId, verifyCode } = useAuth();
  const [otp, setOtp] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (userId) {
    return <Redirect href="/signals" />;
  }
  if (!pending) {
    return <Redirect href="/" />;
  }

  async function continueWithCode() {
    setBusy(true);
    setError(null);
    try {
      await verifyCode(otp.trim());
      router.replace("/signals");
    } catch (caught) {
      setError(caught instanceof ApiRequestError ? caught.message : "That code was not accepted.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <SafeAreaView style={ui.screen}>
      <Text style={ui.title}>Enter the code</Text>
      <Text style={ui.lead}>Sent to {pending.phone}.</Text>
      {pending.devOtp ? (
        <View style={ui.card}>
          <Text style={ui.meta}>
            Development shows this code because SMS is not connected: {pending.devOtp}. Production
            does not display it.
          </Text>
        </View>
      ) : null}
      <Text style={ui.label}>One-time code</Text>
      <TextInput
        style={ui.input}
        value={otp}
        onChangeText={setOtp}
        keyboardType="number-pad"
        maxLength={6}
        placeholder="6 digits"
        placeholderTextColor="#8a8478"
      />
      {error ? <Text style={ui.error}>{error}</Text> : null}
      <Pressable style={ui.primary} disabled={busy} onPress={continueWithCode}>
        <Text style={ui.primaryText}>{busy ? "Checking…" : "Continue"}</Text>
      </Pressable>
      <Pressable style={ui.ghost} onPress={() => router.replace("/")}>
        <Text style={ui.ghostText}>Change number</Text>
      </Pressable>
    </SafeAreaView>
  );
}
