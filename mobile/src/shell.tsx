import { router, usePathname } from "expo-router";
import { useEffect, useState, type ReactNode } from "react";
import { Pressable, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { api } from "@/api";
import { useAuth } from "@/auth";
import type { MeOut } from "@/types";
import { colors, ui } from "@/ui";

type Item = {
  href: string;
  label: string;
  current: (path: string) => boolean;
};

const places: Item[] = [
  { href: "/signals", label: "Home", current: (path) => path === "/signals" },
  { href: "/scanners", label: "Scanners", current: (path) => path.startsWith("/scanners") },
  { href: "/account", label: "Account", current: (path) => path.startsWith("/account") },
];

export function AppShell({
  title,
  heading,
  children,
  onBack,
}: {
  title: string;
  heading?: ReactNode;
  children: ReactNode;
  onBack?: () => void;
}) {
  const { userId, signOut } = useAuth();
  const path = usePathname();
  const [open, setOpen] = useState(false);
  const [admin, setAdmin] = useState(false);

  useEffect(() => {
    if (!userId) {
      return;
    }
    let cancelled = false;
    api<MeOut>("/api/v1/me")
      .then((me) => {
        if (!cancelled) {
          setAdmin(me.roles.includes("admin"));
        }
      })
      .catch(() => {
        if (!cancelled) {
          setAdmin(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [userId]);

  const items = admin
    ? [...places, { href: "/admin", label: "Admin", current: (value: string) => value.startsWith("/admin") }]
    : places;

  function go(href: string) {
    setOpen(false);
    if (path !== href) {
      router.replace(href);
    }
  }

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.paper }} edges={["top", "left", "right"]}>
      <View style={ui.bar}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={onBack && !open ? "Back" : open ? "Close navigation" : "Open navigation"}
          accessibilityState={onBack && !open ? undefined : { expanded: open }}
          style={ui.menuButton}
          onPress={() => {
            if (onBack && !open) {
              onBack();
              return;
            }
            setOpen((current) => !current);
          }}
        >
          {onBack && !open ? <BackMark /> : <MenuMark />}
        </Pressable>
        {heading ? (
          <View style={ui.barHeading}>{heading}</View>
        ) : (
          <Text style={ui.barTitle} numberOfLines={1}>
            {title}
          </Text>
        )}
      </View>
      {open ? (
        <View style={ui.menuList}>
          {items.map((item) => {
            const current = item.current(path);
            return (
              <Pressable
                key={item.href}
                accessibilityRole="button"
                accessibilityState={{ selected: current }}
                style={[ui.menuItem, current ? ui.menuItemOn : null]}
                onPress={() => go(item.href)}
              >
                <Text style={ui.menuItemText}>{item.label}</Text>
              </Pressable>
            );
          })}
          <Pressable
            accessibilityRole="button"
            style={[ui.menuItem, ui.menuSignOut]}
            onPress={async () => {
              setOpen(false);
              await signOut();
              router.replace("/");
            }}
          >
            <Text style={[ui.menuItemText, { color: colors.sell }]}>Sign out</Text>
          </Pressable>
        </View>
      ) : (
        <View style={{ flex: 1 }}>{children}</View>
      )}
    </SafeAreaView>
  );
}

function MenuMark() {
  return (
    <View style={{ width: 24, height: 24, justifyContent: "center", gap: 5 }}>
      <View style={stroke} />
      <View style={stroke} />
      <View style={stroke} />
    </View>
  );
}

function BackMark() {
  return (
    <View style={{ width: 24, height: 24, justifyContent: "center" }}>
      <View style={[stroke, { position: "absolute", width: 16, left: 4 }]} />
      <View
        style={{
          width: 10,
          height: 10,
          borderLeftWidth: 2,
          borderBottomWidth: 2,
          borderColor: colors.ink,
          transform: [{ rotate: "45deg" }],
          marginLeft: 2,
        }}
      />
    </View>
  );
}

const stroke = {
  height: 2,
  borderRadius: 1,
  backgroundColor: colors.ink,
};
