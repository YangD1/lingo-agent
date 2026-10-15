import {
  BookOpenIcon,
  CalendarClockIcon,
  CatIcon,
  ChartColumnIcon,
  ClipboardCheckIcon,
  CompassIcon,
  FilePenLineIcon,
  FilterIcon,
  LayersIcon,
  LayoutGridIcon,
  LibraryIcon,
  ListChecksIcon,
  ListOrderedIcon,
  type LucideIcon,
  MicIcon,
  NewspaperIcon,
  NotebookPenIcon,
  PencilLineIcon,
  PhoneIcon,
  PlugIcon,
  SparklesIcon,
  UserRoundPlusIcon,
  UsersIcon,
  Volume2Icon,
  AudioLinesIcon,
} from "lucide-react";

/**
 * What the desk pet can open (ADR 0039 §1): flashcards over the page, a page, or a card of
 * the settings page. All are plain links: the flashcards' host takes `/vocab/review` links
 * and opens the overlay in place (ADR 0038), and the settings page flashes the card its
 * hash names. Nothing here changes a setting; those go through the tutor's cards.
 */
export type PetActionOpens = "overlay" | "page" | "setup";

export type PetActionId =
  | "vocab_review"
  | "vocab_learn"
  | "practice"
  | "speaking"
  | "speaking_call"
  | "writing"
  | "reading"
  | "placement"
  | "word_books"
  | "vocab_screen"
  | "vocab_mine"
  | "learner"
  | "memory"
  | "plan"
  | "tutor"
  | "setup_models"
  | "setup_routes"
  | "setup_read_aloud"
  | "setup_word_audio"
  | "setup_realtime"
  | "setup_background"
  | "setup_members"
  | "setup_membership"
  | "setup_usage"
  | "setup_guide";

export type PetAction = {
  id: PetActionId;
  opens: PetActionOpens;
  href: string;
  icon: LucideIcon;
  /** Phrases that ask for it, lower case; Chinese ones without spaces or punctuation. */
  triggers: { zh: string[]; en: string[] };
};

function action(
  id: PetActionId,
  opens: PetActionOpens,
  href: string,
  icon: LucideIcon,
  zh: string[],
  en: string[],
): PetAction {
  return { id, opens, href, icon, triggers: { zh, en } };
}

export const PET_ACTIONS: readonly PetAction[] = [
  // Over the page.
  action("vocab_review", "overlay", "/vocab/review", LayersIcon,
    ["背单词", "背词", "复习单词", "单词复习", "复习生词", "记单词", "闪卡"],
    ["flashcards", "review words", "review vocab", "vocab review", "study words", "memorize words"]),
  action("vocab_learn", "overlay", "/vocab/review?mode=new", SparklesIcon,
    ["学新词", "学新单词", "背新词", "背新单词", "新单词", "学单词"],
    ["new words", "learn words", "learn new words"]),
  // Pages.
  action("practice", "page", "/practice", PencilLineIcon,
    ["练语法", "语法练习", "练习语法", "做练习", "刷题"],
    ["grammar practice", "practice grammar", "practise grammar", "grammar drill"]),
  action("speaking", "page", "/speaking", MicIcon,
    ["练口语", "口语练习", "说英语", "口语"],
    ["speaking practice", "practice speaking", "practise speaking", "speaking"]),
  action("speaking_call", "page", "/speaking/call", PhoneIcon,
    ["打电话", "通话", "语音通话", "实时通话"],
    ["voice call", "live call", "phone call", "start a call", "call you"]),
  action("writing", "page", "/writing", FilePenLineIcon,
    ["写作", "写作文", "作文", "批改作文", "写文章"],
    ["writing", "essay", "write an essay", "check my essay"]),
  action("reading", "page", "/reading", NewspaperIcon,
    ["阅读", "读新闻", "看新闻", "读文章", "分级阅读"],
    ["reading", "read news", "read the news", "read an article", "news"]),
  action("placement", "page", "/placement", ClipboardCheckIcon,
    ["入学测", "水平测试", "测试水平", "测水平", "测一下水平", "复测", "摸底"],
    ["placement", "placement test", "level test", "test my level"]),
  action("word_books", "page", "/vocab", LibraryIcon,
    ["选词书", "换词书", "词书"],
    ["word book", "word books", "choose a book", "change book"]),
  action("vocab_screen", "page", "/vocab/screen", FilterIcon,
    ["筛词", "筛选单词", "单词筛选", "标熟词"],
    ["screen words", "mark known words"]),
  action("vocab_mine", "page", "/vocab/mine", BookOpenIcon,
    ["生词本", "我的生词"],
    ["my words", "word list", "my word list"]),
  action("learner", "page", "/learner", ListChecksIcon,
    ["我的水平", "学习者模型", "掌握度", "学习报告", "我的进度"],
    ["my level", "my progress", "learner model", "mastery"]),
  action("memory", "page", "/memory", NotebookPenIcon,
    ["我的记忆", "查看记忆", "记忆管理", "记忆"],
    ["memory", "memories", "my memories"]),
  action("plan", "page", "/dashboard", LayoutGridIcon,
    ["今日计划", "今天计划", "今天的计划", "学习计划", "看板"],
    ["today's plan", "daily plan", "plan for today", "dashboard"]),
  action("tutor", "page", "/tutor", CatIcon,
    ["换装", "换衣服", "换形象", "换声音", "换音色", "私教设置", "助手设置", "改名字"],
    ["outfit", "change voice", "change your voice", "tutor settings", "assistant settings", "rename you"]),
  // Settings (setup).
  action("setup_models", "setup", "/settings#connections", PlugIcon,
    ["配置模型", "设置模型", "模型设置", "配模型", "接入模型", "连接模型", "模型连接", "apikey", "填key", "密钥"],
    ["set up models", "model settings", "api key", "connect a model", "add a model"]),
  action("setup_routes", "setup", "/settings#routes", ListOrderedIcon,
    ["模型顺序", "任务路由", "模型路由", "换模型"],
    ["model order", "routes", "model routes", "change model"]),
  action("setup_read_aloud", "setup", "/settings#read-aloud", Volume2Icon,
    ["朗读设置", "朗读声音", "声音设置", "朗读"],
    ["read aloud", "read-aloud", "voice settings"]),
  action("setup_word_audio", "setup", "/settings#word-audio", AudioLinesIcon,
    ["单词发音", "发音预生成", "生成发音"],
    ["word audio", "word pronunciation"]),
  action("setup_realtime", "setup", "/settings#realtime", PhoneIcon,
    ["通话设置", "实时通话设置", "通话模型", "实时语音"],
    ["call settings", "realtime settings"]),
  action("setup_background", "setup", "/settings#background", CalendarClockIcon,
    ["后台任务", "定时任务", "每日反思"],
    ["background jobs", "scheduled jobs"]),
  action("setup_members", "setup", "/settings#members", UsersIcon,
    ["邀请成员", "成员", "子账号", "邀请家人"],
    ["invite", "members", "invite someone"]),
  action("setup_membership", "setup", "/settings#membership", UserRoundPlusIcon,
    ["主账号", "加入组织", "邀请码", "加入主账号"],
    ["join an organization", "invite code", "main account"]),
  action("setup_usage", "setup", "/settings#usage", ChartColumnIcon,
    ["用量", "额度", "token用量", "花了多少"],
    ["usage", "quota", "tokens used"]),
  // The setup guide, all steps again (ADR 0042 §4).
  action("setup_guide", "page", "/setup", CompassIcon,
    ["配置引导", "新手引导", "设置引导", "重新配置", "初始设置"],
    ["setup guide", "onboarding", "set up again", "getting started"]),
];

const BY_ID = new Map(PET_ACTIONS.map((a) => [a.id, a]));

export function petAction(id: PetActionId): PetAction {
  const found = BY_ID.get(id);
  if (!found) throw new Error(`no pet action ${id}`);
  return found;
}

/** The shortcuts on top of the chat window. */
export const QUICK_ACTIONS: readonly PetActionId[] = [
  "vocab_review",
  "vocab_learn",
  "practice",
  "speaking",
  "reading",
  "writing",
];

/** Longer than this is a sentence for the tutor, not a command for the pet (Q76a). */
export const MAX_COMMAND_CHARS = 16;
export const MAX_COMMAND_WORDS = 6;

// Questions go to the tutor: "what's a good way to remember words" is not "flashcards".
const QUESTION = /[?？]|怎么|为什么|什么|如何|吗|\b(how|why|what|which|when|should)\b/i;
const CJK = /[㐀-鿿]/;
const NOT_WORD = /[\s\p{P}\p{S}]+/gu;

/**
 * The action a short message asks for (ADR 0039 §2), or null for the tutor to answer: a
 * question, a longer message, or nothing known. The longest phrase found wins, so "实时通话设置"
 * is the call settings, not a call.
 */
export function matchAction(text: string): PetAction | null {
  const said = text.normalize("NFKC").toLowerCase().trim();
  if (!said || QUESTION.test(said)) return null;
  const compact = said.replace(NOT_WORD, "");
  if (CJK.test(said)) {
    if (compact.length > MAX_COMMAND_CHARS) return null;
  } else if (said.split(/\s+/).length > MAX_COMMAND_WORDS) {
    return null;
  }
  const words = ` ${said.replace(NOT_WORD, " ").trim()} `;
  let best: PetAction | null = null;
  let bestLength = 0;
  for (const candidate of PET_ACTIONS) {
    for (const phrase of candidate.triggers.zh) {
      if (phrase.length > bestLength && compact.includes(phrase)) {
        best = candidate;
        bestLength = phrase.length;
      }
    }
    for (const phrase of candidate.triggers.en) {
      if (phrase.length > bestLength && words.includes(` ${phrase.replace(NOT_WORD, " ")} `)) {
        best = candidate;
        bestLength = phrase.length;
      }
    }
  }
  return best;
}
