import { Redirect, router } from "expo-router";
import { useState } from "react";
import { ActivityIndicator, Pressable, Text, TextInput } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { ApiRequestError } from "@/api";
import { useAuth } from "@/auth";
import { ui } from "@/ui";

export default function SignInScreen() {
  const { ready, userId, requestCode } = useAuth();
  const [phone, setPhone] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (!ready) {
    return (
      <SafeAreaView style={ui.screen}>
        <ActivityIndicator />
      </SafeAreaView>
    );
  }
  if (userId) {
    return <Redirect href="/signals" />;
  }

  async function sendCode() {
    setBusy(true);
    setError(null);
    try {
      await requestCode(phone.trim());
      router.push("/code");
    } catch (caught) {
      setError(caught instanceof ApiRequestError ? caught.message : "The code could not be sent.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <SafeAreaView style={ui.screen}>
      <Text style={ui.title}>Sign in</Text>
      <Text style={ui.lead}>Use your Indian mobile number. A one-time code opens the session.</Text>
      <Text style={ui.label}>Mobile number</Text>
      <TextInput
        style={ui.input}
        value={phone}
        onChangeText={setPhone}
        keyboardType="phone-pad"
        autoComplete="tel"
        placeholder="9845011220"
        placeholderTextColor="#8a8478"
      />
      {error ? <Text style={ui.error}>{error}</Text> : null}
      <Pressable style={ui.primary} disabled={busy} onPress={sendCode}>
        <Text style={ui.primaryText}>{busy ? "Sending…" : "Send code"}</Text>
      </Pressable>
    </SafeAreaView>
  );
}
