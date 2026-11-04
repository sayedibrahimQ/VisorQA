"use client";

import React, { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/context/AuthContext";
import { Loader2 } from "lucide-react";

export default function DemoLandingRoute() {
  const router = useRouter();
  const { user, loading, loginWithConfigured } = useAuth();
  const loginTriggered = useRef(false);

  useEffect(() => {
    if (loading) return;

    if (user) {
      router.replace("/mission-control?demo=1");
      return;
    }

    if (!loginTriggered.current) {
      loginTriggered.current = true;
      loginWithConfigured()
        .then(() => {
          router.replace("/mission-control?demo=1");
        })
        .catch((err) => {
          console.error("Auto demo authentication failed:", err);
          router.replace("/mission-control?demo=1");
        });
    }
  }, [loading, user, loginWithConfigured, router]);

  return (
    <main className="min-h-screen bg-canvas text-text-primary flex flex-col items-center justify-center p-6">
      <div className="flex flex-col items-center gap-3">
        <Loader2 className="h-5 w-5 animate-spin text-text-secondary" />
        <p className="font-mono text-xs text-text-secondary">
          Initializing demo session…
        </p>
      </div>
    </main>
  );
}

