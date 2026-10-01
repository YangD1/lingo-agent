// LingoCat.tsx — 猫咪 L 的六种情绪动画。样式：lingo-cat.css（替换之前的 loader.css）。
//   <LingoCat />                  加载（默认，循环）
//   <LingoCat mood="hop" />       长等待：出结果、生成计划、批改（循环）
//   <LingoCat mood="ai" />        AI 生成中 / 私教在想（循环）
//   <LingoCat mood="done" />      完成（一次性，结束停在静态 logo）
//   <LingoCat mood="idle" />      待机 / 空状态（循环，很安静）
//   <LingoCat mood="oops" />      出错（一次性，停在耳朵耷拉的姿势）
// 一次性动画想重播：换 key 重新挂载，例如 <LingoCat key={doneCount} mood="done" />
// size ≤ 24 时自动用小号（只动尾巴和星星）。
import { cn } from "@/lib/utils";

export type LingoCatMood = "loader" | "hop" | "ai" | "done" | "idle" | "oops";

const LABEL: Record<LingoCatMood, string> = {
  loader: "加载中", hop: "处理中", ai: "AI 正在生成", done: "完成", idle: "", oops: "出错了",
};

export function LingoCat({ mood = "loader", size = 96, small, label, className }: {
  mood?: LingoCatMood; size?: number; small?: boolean; label?: string; className?: string;
}) {
  const text = label ?? LABEL[mood];
  return (
    <svg viewBox="0 0 64 64" width={size} height={size}
      role={text ? "img" : undefined} aria-label={text || undefined} aria-hidden={text ? undefined : true}
      className={cn("lcat", mood !== "loader" && `v-${mood}`, (small ?? size <= 24) && "sm", className)}>
      <ellipse className="shadow" cx="30" cy="55.6" rx="22" ry="1.6"/><g className="catg"><path className="tail" d="M31 51.2H42"/><g className="tailg"><path className="tail" d="M42 51.2C49 51.2 52.5 46.4 51.5 41.2"/><g className="tipg"><path className="tail" d="M51.5 41.2C50.6 36.8 45.6 35.8 43 38.8"/></g></g><g className="bodyg"><path className="body" stroke="none" d="M15 23C8.8 30 8.2 43.6 9.6 50.2Q10.4 54 14.6 54H29.4Q33.6 54 34.4 50.2C35.8 43.6 35.2 30 29 23Z"/><g className="headg"><g className="earL"><path className="head" strokeWidth="3.4" d="M14.4 14.4L12.8 5.4L18 10.8Z"/></g><g className="earR"><path className="head" strokeWidth="3.4" d="M29.6 14.4L31.2 5.4L26 10.8Z"/></g><ellipse className="head" stroke="none" cx="22" cy="19.2" rx="10.8" ry="10.4"/></g></g></g><path className="spark s2" d="M43 12.5Q43 19 49.5 19Q43 19 43 25.5Q43 19 36.5 19Q43 19 43 12.5Z"/><path className="spark s3" d="M43 12.5Q43 19 49.5 19Q43 19 43 25.5Q43 19 36.5 19Q43 19 43 12.5Z"/><path className="spark s1" d="M43 12.5Q43 19 49.5 19Q43 19 43 25.5Q43 19 36.5 19Q43 19 43 12.5Z"/>
    </svg>
  );
}

/** 兼容之前的 LingoLoader */
export const LingoLoader = (p: { size?: number; small?: boolean; label?: string; className?: string }) => <LingoCat {...p} />;
