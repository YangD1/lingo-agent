import { Logo } from "@/components/brand/logo";
import { LocaleSwitcher } from "@/components/locale-switcher";
import { ThemeSwitcher } from "@/components/theme/theme-switcher";
import { getMe } from "@/lib/server-me";

/** Full-screen pages before the app proper: the setup guide and invite links (ADR 0042 §1). */
export default async function SetupLayout({ children }: LayoutProps<"/">) {
  await getMe();
  return (
    <div className="flex h-dvh flex-col">
      <header className="flex h-14 shrink-0 items-center justify-between gap-3 px-4 md:h-[52px] md:px-[18px]">
        <Logo className="text-[15px]" markClassName="size-6" />
        <div className="flex items-center gap-2">
          <LocaleSwitcher className="w-[120px]" />
          <ThemeSwitcher />
        </div>
      </header>
      <main className="flex min-h-0 flex-1">{children}</main>
    </div>
  );
}
