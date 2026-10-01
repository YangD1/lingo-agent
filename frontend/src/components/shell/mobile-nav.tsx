"use client";

import { EllipsisIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { LogoMark } from "@/components/brand/logo";
import { LocaleSwitcher } from "@/components/locale-switcher";
import { LogoutButton } from "@/components/logout-button";
import { ThemeSwitcher } from "@/components/theme/theme-switcher";
import { Sheet } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";

import type { ShellUser } from "./app-sidebar";
import { NAV_ITEMS, TAB_KEYS, activeItem, isActive, isFocusRoute } from "./nav-items";
import { UserAvatar } from "./user-avatar";

/** Phone top bar: the mark and the current page's name. */
export function MobileTopBar() {
  const t = useTranslations("nav");
  const pathname = usePathname();
  const item = activeItem(pathname);
  // Chat has its own top bar, with the conversation list drawer and the conversation's title.
  if (isActive(pathname, "/chat") || isFocusRoute(pathname)) return null;
  return (
    <header className="flex h-14 shrink-0 items-center gap-2.5 border-b px-4 md:hidden">
      <Link href="/dashboard" aria-label="Lingo Agent">
        <LogoMark />
      </Link>
      <span className="truncate text-base font-semibold">{item ? t(item.key) : "Lingo Agent"}</span>
    </header>
  );
}

/**
 * Phone tab bar: the four most used pages plus "More", a bottom panel with the remaining
 * pages, the account, language and theme. Chat hides it to give the composer the room.
 */
export function MobileTabBar({ user }: { user: ShellUser }) {
  const t = useTranslations("nav");
  const pathname = usePathname();
  const [moreOpen, setMoreOpen] = useState(false);
  if (isActive(pathname, "/chat") || isFocusRoute(pathname)) return null;

  const tabs = NAV_ITEMS.filter((item) => TAB_KEYS.includes(item.key));
  const rest = NAV_ITEMS.filter((item) => !TAB_KEYS.includes(item.key));
  const restActive = rest.some((item) => isActive(pathname, item.href));
  const tabClass =
    "flex flex-1 flex-col items-center justify-center gap-1 text-[11px] text-muted-foreground outline-none focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring";

  return (
    <nav
      aria-label={t("main")}
      data-testid="mobile-tab-bar"
      className="flex h-16 shrink-0 border-t bg-sidebar pb-[env(safe-area-inset-bottom)] md:hidden"
    >
      {tabs.map(({ key, href, icon: Icon }) => {
        const active = isActive(pathname, href);
        return (
          <Link
            key={key}
            href={href}
            aria-current={active ? "page" : undefined}
            className={cn(tabClass, active && "font-semibold text-primary")}
          >
            <Icon aria-hidden className="size-[22px]" />
            {key === "learner" ? t("progress") : t(key)}
          </Link>
        );
      })}
      <button
        type="button"
        onClick={() => setMoreOpen(true)}
        aria-haspopup="dialog"
        className={cn(tabClass, restActive && "font-semibold text-primary")}
      >
        <EllipsisIcon aria-hidden className="size-[22px]" />
        {t("more")}
      </button>

      <Sheet open={moreOpen} onOpenChange={setMoreOpen} title={t("more")} data-testid="more-panel">
        <ul className="mt-3 grid grid-cols-4 gap-2">
          {rest.map(({ key, href, icon: Icon }) => (
            <li key={key}>
              <Link
                href={href}
                onClick={() => setMoreOpen(false)}
                aria-current={isActive(pathname, href) ? "page" : undefined}
                className="flex flex-col items-center gap-1.5 rounded-lg py-2 text-xs outline-none hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring aria-[current=page]:font-semibold aria-[current=page]:text-primary"
              >
                <span className="flex size-10 items-center justify-center rounded-lg border bg-card">
                  <Icon aria-hidden className="size-5" />
                </span>
                {t(key)}
              </Link>
            </li>
          ))}
        </ul>
        <div className="mt-4 flex items-center gap-2.5 border-t pt-4">
          <UserAvatar name={user.name} />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{user.name}</p>
            <p className="truncate text-xs text-muted-foreground">{user.email}</p>
          </div>
          <LogoutButton />
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <LocaleSwitcher className="min-w-32 flex-1" />
          <ThemeSwitcher variant="labels" />
        </div>
      </Sheet>
    </nav>
  );
}
