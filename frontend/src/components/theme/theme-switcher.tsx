"use client";

import { MonitorIcon, MoonIcon, SunIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import { useTheme } from "next-themes";
import { useSyncExternalStore } from "react";

import { Segmented } from "@/components/ui/segmented";

type ThemeChoice = "system" | "light" | "dark";

const noop = () => () => {};

/**
 * System / light / dark. next-themes keeps the choice in this browser's localStorage.
 * The selection is only known after hydration, so nothing is marked checked on the server.
 */
export function ThemeSwitcher({ variant = "icons" }: { variant?: "icons" | "labels" }) {
  const t = useTranslations("themeSwitcher");
  const { theme, setTheme } = useTheme();
  const mounted = useSyncExternalStore(
    noop,
    () => true,
    () => false,
  );
  const icons = { system: <MonitorIcon />, light: <SunIcon />, dark: <MoonIcon /> };
  const choices: ThemeChoice[] = ["system", "light", "dark"];
  return (
    <Segmented<ThemeChoice>
      label={t("label")}
      size="sm"
      value={mounted ? (theme as ThemeChoice | undefined) : undefined}
      onChange={setTheme}
      options={choices.map((value) => ({
        value,
        label: t(value),
        icon: variant === "icons" ? icons[value] : undefined,
      }))}
    />
  );
}
