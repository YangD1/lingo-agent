"use client";

import { PanelLeftCloseIcon, PanelLeftOpenIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { Logo, LogoMark } from "@/components/brand/logo";
import { LocaleSwitcher } from "@/components/locale-switcher";
import { LogoutButton } from "@/components/logout-button";
import { ThemeSwitcher } from "@/components/theme/theme-switcher";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

import { NAV_GROUPS, isActive, isFocusRoute } from "./nav-items";
import { UserAvatar } from "./user-avatar";

export type ShellUser = { name: string; email: string };

/**
 * Desktop sidebar (component-spec "应用外壳"). The chat page starts as a 64px icon rail to
 * leave room for reading; elsewhere it starts expanded. A toggle overrides that until the
 * learner moves between chat and the other pages.
 */
export function AppSidebar({ user }: { user: ShellUser }) {
  const t = useTranslations("nav");
  const pathname = usePathname();
  const onChat = isActive(pathname, "/chat");
  const [override, setOverride] = useState<{ onChat: boolean; collapsed: boolean } | null>(null);
  const collapsed = override?.onChat === onChat ? override.collapsed : onChat;
  const toggle = () => setOverride({ onChat, collapsed: !collapsed });
  if (isFocusRoute(pathname)) return null;

  return (
    <aside
      data-testid="app-sidebar"
      data-collapsed={collapsed}
      className={cn(
        "hidden shrink-0 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground md:flex",
        collapsed ? "w-16" : "w-62",
      )}
    >
      <div className={cn("flex h-14 items-center", collapsed ? "justify-center" : "justify-between pr-2 pl-4")}>
        {collapsed ? (
          <Link href="/dashboard" aria-label="Lingo Agent">
            <LogoMark />
          </Link>
        ) : (
          <Link href="/dashboard">
            <Logo className="text-[15px]" />
          </Link>
        )}
        {!collapsed && (
          <Button variant="ghost" size="icon-sm" onClick={toggle} aria-label={t("collapse")} title={t("collapse")}>
            <PanelLeftCloseIcon className="size-[18px]" />
          </Button>
        )}
      </div>

      <nav aria-label={t("main")} className={cn("flex-1 overflow-y-auto pb-3", collapsed ? "px-3" : "px-3")}>
        {NAV_GROUPS.map((group) => (
          <div key={group.key} className="mt-3 first:mt-1">
            {!collapsed && (
              <p className="px-2.5 pb-1 text-[11.5px] font-semibold text-muted-foreground">{t(group.key)}</p>
            )}
            <ul className="flex flex-col gap-0.5">
              {group.items.map(({ key, href, icon: Icon }) => {
                const active = isActive(pathname, href);
                return (
                  <li key={key}>
                    <Link
                      href={href}
                      aria-current={active ? "page" : undefined}
                      aria-label={collapsed ? t(key) : undefined}
                      title={collapsed ? t(key) : undefined}
                      className={cn(
                        "flex h-[38px] items-center gap-2.5 rounded-md text-sm transition-colors outline-none hover:bg-sidebar-accent/60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sidebar-ring",
                        collapsed ? "justify-center" : "px-2.5",
                        active && "bg-sidebar-accent font-semibold text-sidebar-accent-foreground hover:bg-sidebar-accent",
                      )}
                    >
                      <Icon aria-hidden className="size-[18px] shrink-0" />
                      {!collapsed && t(key)}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      <div className={cn("flex flex-col gap-2 border-t border-sidebar-border p-3", collapsed && "items-center")}>
        {collapsed ? (
          <>
            <Button variant="ghost" size="icon-sm" onClick={toggle} aria-label={t("expand")} title={t("expand")}>
              <PanelLeftOpenIcon className="size-[18px]" />
            </Button>
            <Popover>
              <PopoverTrigger
                aria-label={t("account")}
                title={t("account")}
                className="rounded-full outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
              >
                <UserAvatar name={user.name} />
              </PopoverTrigger>
              <PopoverContent side="right" align="end" sideOffset={24} className="flex w-64 flex-col gap-2 p-3">
                <AccountPanel user={user} />
              </PopoverContent>
            </Popover>
          </>
        ) : (
          <AccountPanel user={user} />
        )}
      </div>
    </aside>
  );
}

/** Who is signed in, language, theme and log out: the sidebar footer, or the rail's avatar menu. */
function AccountPanel({ user }: { user: ShellUser }) {
  return (
    <>
      <div className="flex items-center gap-2.5 px-1">
        <UserAvatar name={user.name} />
        <div className="min-w-0">
          <p className="truncate text-sm font-medium" data-testid="current-user">
            {user.name}
          </p>
          <p className="truncate text-xs text-muted-foreground">{user.email}</p>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <LocaleSwitcher className="min-w-0 flex-1" />
        <ThemeSwitcher />
      </div>
      <LogoutButton />
    </>
  );
}
