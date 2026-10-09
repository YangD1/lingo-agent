"use client";

import { AiBadge } from "@/components/ai-badge";
import { useServerSpeech, useSpeechSettings } from "@/lib/speech";

/**
 * The AI mark beside a read-aloud button (ADR 0014): only while the server reads English
 * for this learner, as the browser's own voices call no model.
 */
export function ReadAloudBadge({ className }: { className?: string }) {
  const server = useServerSpeech();
  const [settings] = useSpeechSettings();
  const lang = settings.accent;
  const serverReads =
    settings.server &&
    !server.down &&
    !server.noVoice.has(lang) &&
    (server.languages?.has(lang) ?? false);
  return serverReads ? <AiBadge feature="read_aloud" className={className} /> : null;
}
