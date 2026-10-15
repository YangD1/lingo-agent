"use client";

import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";

import { DEFAULT_FUR, FUR_SWATCHES, OUTFITS, type Outfit } from "./avatar-draw";
import { TutorAvatar } from "./tutor-avatar";

// Names of FUR_SWATCHES, in order.
const FUR_NAMES = ["orange", "gold", "beige", "grey", "blue", "black", "white", "pink"] as const;

/** The assistant's outfits, each drawn in the chosen fur; on "My assistant" and in the setup guide. */
export function OutfitPicker({
  value,
  fur,
  onChange,
}: {
  value: Outfit;
  fur: string;
  onChange: (outfit: Outfit) => void;
}) {
  const t = useTranslations("tutor.looks");
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-2 text-sm leading-none font-medium">{t("outfit")}</legend>
      <div className="flex flex-wrap gap-2">
        {OUTFITS.map((outfit) => (
          <button
            key={outfit}
            type="button"
            aria-pressed={value === outfit}
            aria-label={t(`outfits.${outfit}`)}
            title={t(`outfits.${outfit}`)}
            onClick={() => onChange(outfit)}
            data-testid={`tutor-outfit-${outfit}`}
            className={cn(
              "rounded-lg border p-1 outline-none hover:bg-accent focus-visible:ring-3 focus-visible:ring-ring/50",
              value === outfit && "border-primary ring-1 ring-primary",
            )}
          >
            <TutorAvatar outfit={outfit} fur={fur} animate={false} size={56} label="" />
          </button>
        ))}
      </div>
    </fieldset>
  );
}

/** Fur swatches plus a custom color; "" is the default fur. */
export function FurPicker({ value, onChange }: { value: string; onChange: (color: string) => void }) {
  const t = useTranslations("tutor.looks");
  const fur = value || DEFAULT_FUR;
  const custom = !(FUR_SWATCHES as readonly string[]).includes(fur);
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-2 text-sm leading-none font-medium">{t("fur")}</legend>
      <div className="flex flex-wrap items-center gap-2">
        {FUR_SWATCHES.map((swatch, i) => (
          <button
            key={swatch}
            type="button"
            aria-pressed={fur === swatch}
            aria-label={t(`furs.${FUR_NAMES[i]}`)}
            title={t(`furs.${FUR_NAMES[i]}`)}
            onClick={() => onChange(swatch === DEFAULT_FUR ? "" : swatch)}
            className={cn(
              "size-8 rounded-full border-2 border-[#563f39]/40 outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
              fur === swatch && "ring-2 ring-primary ring-offset-2 ring-offset-card",
            )}
            style={{ backgroundColor: swatch }}
          />
        ))}
        <label
          className={cn(
            "relative flex h-8 cursor-pointer items-center gap-1.5 rounded-full border px-2.5 text-xs text-muted-foreground hover:bg-accent",
            custom && "ring-2 ring-primary ring-offset-2 ring-offset-card",
          )}
        >
          <span aria-hidden className="size-4 rounded-full border" style={{ backgroundColor: fur }} />
          {t("furCustom")}
          <input
            type="color"
            value={fur}
            onChange={(e) => onChange(e.target.value.toLowerCase())}
            className="absolute inset-0 cursor-pointer opacity-0"
          />
        </label>
      </div>
    </fieldset>
  );
}
