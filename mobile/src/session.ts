import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";

const REFRESH_KEY = "quantivo.refresh";

export async function readRefreshToken(): Promise<string | null> {
  if (Platform.OS === "web") {
    return globalThis.localStorage?.getItem(REFRESH_KEY) ?? null;
  }
  return SecureStore.getItemAsync(REFRESH_KEY);
}

export async function writeRefreshToken(token: string): Promise<void> {
  if (Platform.OS === "web") {
    globalThis.localStorage?.setItem(REFRESH_KEY, token);
    return;
  }
  await SecureStore.setItemAsync(REFRESH_KEY, token);
}

export async function clearRefreshToken(): Promise<void> {
  if (Platform.OS === "web") {
    globalThis.localStorage?.removeItem(REFRESH_KEY);
    return;
  }
  await SecureStore.deleteItemAsync(REFRESH_KEY);
}
