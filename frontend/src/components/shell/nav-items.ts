import {
  BookOpenIcon,
  ClipboardCheckIcon,
  FilePenLineIcon,
  LayoutGridIcon,
  type LucideIcon,
  ListChecksIcon,
  MessageCircleIcon,
  NotebookPenIcon,
  PencilLineIcon,
  SettingsIcon,
} from "lucide-react";

export type NavKey =
  | "dashboard"
  | "chat"
  | "vocab"
  | "practice"
  | "writing"
  | "learner"
  | "placement"
  | "memory"
  | "settings";

export type NavItem = { key: NavKey; href: `/${string}`; icon: LucideIcon };

/** Sidebar groups (Q26d): only pages that exist; new pages join a group when they ship. */
export const NAV_GROUPS: { key: "groupLearn" | "groupProgress" | "groupMine"; items: NavItem[] }[] = [
  {
    key: "groupLearn",
    items: [
      { key: "dashboard", href: "/dashboard", icon: LayoutGridIcon },
      { key: "chat", href: "/chat", icon: MessageCircleIcon },
      { key: "vocab", href: "/vocab", icon: BookOpenIcon },
      { key: "practice", href: "/practice", icon: PencilLineIcon },
      { key: "writing", href: "/writing", icon: FilePenLineIcon },
    ],
  },
  {
    key: "groupProgress",
    items: [
      { key: "learner", href: "/learner", icon: ListChecksIcon },
      { key: "placement", href: "/placement", icon: ClipboardCheckIcon },
    ],
  },
  {
    key: "groupMine",
    items: [
      { key: "memory", href: "/memory", icon: NotebookPenIcon },
      { key: "settings", href: "/settings", icon: SettingsIcon },
    ],
  },
];

export const NAV_ITEMS: NavItem[] = NAV_GROUPS.flatMap((g) => g.items);

/** The phone tab bar holds the four most used pages; the rest live under "More". */
export const TAB_KEYS: NavKey[] = ["dashboard", "chat", "vocab", "learner"];

export function isActive(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function activeItem(pathname: string): NavItem | undefined {
  return NAV_ITEMS.find((item) => isActive(pathname, item.href));
}

/** Pages that take the whole screen, without the sidebar or the phone bars: flashcards. */
export function isFocusRoute(pathname: string): boolean {
  return isActive(pathname, "/vocab/review");
}
