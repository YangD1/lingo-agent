import Link from "next/link";

import { Logo } from "@/components/brand/logo";
import { LocaleSwitcher } from "@/components/locale-switcher";

export default function AuthLayout({ children }: LayoutProps<"/">) {
  return (
    <div className="flex min-h-svh flex-col">
      <header className="flex h-14 items-center justify-between px-4 md:h-[52px] md:px-[18px]">
        <Link href="/" className="rounded-sm">
          <Logo className="text-[15px]" markClassName="size-6" />
        </Link>
        <LocaleSwitcher className="w-[120px]" />
      </header>
      <main className="flex flex-1 items-start justify-center px-4 pt-10 pb-16 md:items-center md:pt-0 md:pb-[10vh]">
        {children}
      </main>
    </div>
  );
}
