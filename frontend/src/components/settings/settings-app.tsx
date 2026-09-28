"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { Connection, Presets } from "@/lib/types";

import { ChatRouteSection } from "./chat-route-section";
import { ConnectionsSection } from "./connections-section";
import { UsageSection } from "./usage-section";

export function SettingsApp() {
  const [presets, setPresets] = useState<Presets | null>(null);
  const [connections, setConnections] = useState<Connection[] | null>(null);

  useEffect(() => {
    api<Presets>("/provider-presets").then(setPresets, () => {});
    api<Connection[]>("/tenant/connections").then(setConnections, () => {});
  }, []);

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto flex max-w-4xl flex-col gap-6 p-4 md:p-8">
        {presets && connections && (
          <>
            <ConnectionsSection
              presets={presets}
              connections={connections}
              onChange={setConnections}
            />
            <ChatRouteSection connections={connections} />
          </>
        )}
        <UsageSection />
      </div>
    </div>
  );
}
