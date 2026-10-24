import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { api, forgetSession, rememberSession } from "@/api";
import { readRefreshToken, writeRefreshToken } from "@/session";
import type { OtpRequestOut, TokenOut } from "@/types";

type PendingCode = {
  phone: string;
  challengeId: string;
  devOtp: string | null;
};

type AuthValue = {
  ready: boolean;
  userId: string | null;
  pending: PendingCode | null;
  requestCode: (phone: string) => Promise<void>;
  verifyCode: (otp: string) => Promise<void>;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [userId, setUserId] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingCode | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const stored = await readRefreshToken();
      if (!stored) {
        if (!cancelled) {
          setReady(true);
        }
        return;
      }
      try {
        const tokens = await api<TokenOut>("/api/v1/auth/refresh", {
          method: "POST",
          body: JSON.stringify({ refresh_token: stored }),
        });
        rememberSession(tokens.access_token, tokens.refresh_token);
        await writeRefreshToken(tokens.refresh_token);
        if (!cancelled) {
          setUserId(tokens.user_id);
        }
      } catch {
        await forgetSession();
      } finally {
        if (!cancelled) {
          setReady(true);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const requestCode = useCallback(async (phone: string) => {
    const body = await api<OtpRequestOut>("/api/v1/auth/otp/request", {
      method: "POST",
      body: JSON.stringify({ phone }),
    });
    setPending({ phone, challengeId: body.challenge_id, devOtp: body.dev_otp });
  }, []);

  const verifyCode = useCallback(
    async (otp: string) => {
      if (!pending) {
        throw new Error("Request a code first.");
      }
      const tokens = await api<TokenOut>("/api/v1/auth/otp/verify", {
        method: "POST",
        body: JSON.stringify({
          phone: pending.phone,
          challenge_id: pending.challengeId,
          otp,
          device_label: "quantivo-mobile",
        }),
      });
      rememberSession(tokens.access_token, tokens.refresh_token);
      await writeRefreshToken(tokens.refresh_token);
      setUserId(tokens.user_id);
      setPending(null);
    },
    [pending],
  );

  const signOut = useCallback(async () => {
    try {
      await api<void>("/api/v1/auth/logout", { method: "POST" });
    } catch {
      // The local session still ends if the server is already done with it.
    }
    await forgetSession();
    setUserId(null);
  }, []);

  const value = useMemo(
    () => ({ ready, userId, pending, requestCode, verifyCode, signOut }),
    [ready, userId, pending, requestCode, verifyCode, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) {
    throw new Error("AuthProvider is missing.");
  }
  return value;
}
