"use client";

import { Trash2Icon } from "lucide-react";
import { useTranslations } from "next-intl";
import { type FormEvent, useState } from "react";

import { useDescribeError } from "@/components/settings/use-describe-error";
import { Button } from "@/components/ui/button";
import { ErrorText } from "@/components/ui/error-text";
import { InlineConfirm } from "@/components/ui/inline-confirm";
import { Input } from "@/components/ui/input";
import { Sheet } from "@/components/ui/sheet";
import { Switch } from "@/components/ui/switch";
import { Tag } from "@/components/ui/tag";
import { ApiError } from "@/lib/api";
import { addFeed, deleteFeed, type Feed, fetchFeeds, ownCount, setSubscribed } from "@/lib/reading";

/**
 * "Manage feeds" (Q43f): turn built-in feeds on or off for me, add an RSS feed of my own
 * (fetched once before it is saved), delete own feeds (whoever added it, or an admin).
 */
export function FeedsSheet({
  open,
  onOpenChange,
  feeds,
  maxOwn,
  onChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  feeds: Feed[];
  maxOwn: number;
  onChange: (feeds: Feed[]) => void;
}) {
  const t = useTranslations("reading.feeds");
  const describe = useDescribeError();
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(key: string, action: () => Promise<Feed[]>) {
    setBusy(key);
    setError(null);
    try {
      onChange(await action());
      return true;
    } catch (e) {
      const reason = e instanceof ApiError && e.code === "feed_unreachable" ? feedReason(e) : null;
      setError(reason ? `${describe(e)} (${reason})` : describe(e));
      return false;
    } finally {
      setBusy(null);
    }
  }

  async function add(event: FormEvent) {
    event.preventDefault();
    const address = url.trim();
    if (!address || busy) return;
    if (await run("add", async () => (await addFeed(address)).feeds)) setUrl("");
  }

  const own = ownCount(feeds);

  return (
    <Sheet
      open={open}
      onOpenChange={onOpenChange}
      title={t("title")}
      className="md:mx-auto md:max-w-xl"
      data-testid="feeds-sheet"
    >
      <div className="flex min-h-0 flex-col gap-4 overflow-y-auto pt-2 text-sm">
        <ul className="flex flex-col gap-3">
          {feeds.map((f) => (
            <li key={f.id} className="flex items-start gap-3" data-testid="feed-row">
              <Switch
                className="mt-0.5"
                aria-label={t("follow", { feed: f.title })}
                checked={f.subscribed}
                disabled={busy !== null}
                onCheckedChange={(on) =>
                  void run(f.id, async () => (await setSubscribed(f.id, on)).feeds)
                }
              />
              <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                <p className="flex flex-wrap items-center gap-1.5 font-medium">
                  <span className="truncate">{f.title}</span>
                  <Tag variant="outline">{f.builtin ? t("builtin") : t("own")}</Tag>
                </p>
                <p className="text-xs text-muted-foreground">{licenseText(t, f.license)}</p>
                {f.last_error && (
                  <p className="text-xs text-warning">{t("lastError", { code: f.last_error })}</p>
                )}
              </div>
              {f.can_delete && (
                <InlineConfirm
                  compact
                  question={t("confirmDelete")}
                  onConfirm={() =>
                    void run(f.id, async () => {
                      await deleteFeed(f.id);
                      return (await fetchFeeds()).feeds;
                    })
                  }
                >
                  {(ask) => (
                    <Button
                      size="icon-sm"
                      variant="ghost"
                      aria-label={t("delete", { feed: f.title })}
                      disabled={busy !== null}
                      onClick={ask}
                    >
                      <Trash2Icon />
                    </Button>
                  )}
                </InlineConfirm>
              )}
            </li>
          ))}
        </ul>

        <form onSubmit={(e) => void add(e)} className="flex flex-col gap-2 border-t pt-4">
          <label htmlFor="feed-url" className="font-semibold">
            {t("addLabel")}
          </label>
          <div className="flex gap-2">
            <Input
              id="feed-url"
              type="url"
              inputMode="url"
              placeholder="https://example.com/feed.xml"
              value={url}
              maxLength={2000}
              onChange={(e) => setUrl(e.target.value)}
              data-testid="feed-url"
            />
            <Button type="submit" disabled={busy !== null || !url.trim() || own >= maxOwn}>
              {busy === "add" ? t("adding") : t("add")}
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">{t("addHint", { n: own, max: maxOwn })}</p>
        </form>
        {error && <ErrorText>{error}</ErrorText>}
      </div>
    </Sheet>
  );
}

function feedReason(e: ApiError): string | null {
  const match = /: (.+)$/.exec(e.message);
  return match ? match[1] : null;
}

function licenseText(t: ReturnType<typeof useTranslations<"reading.feeds">>, license: string): string {
  const key = `license.${license}` as Parameters<typeof t>[0];
  return t.has(key) ? t(key) : license;
}
