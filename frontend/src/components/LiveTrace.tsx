"use client";

import React from "react";
import { Activity, CheckCircle2, AlertTriangle, Loader2 } from "lucide-react";
import { FSMStep } from "@/types";

interface LiveTraceProps {
  currentStep?: FSMStep;
  strikes?: number;
  events?: Array<{ timestamp: string; step: string; message: string }>;
}

const STEPS: { key: FSMStep; label: string; model: string }[] = [
  { key: "1.SENSE", label: "SENSE", model: "Playwright + SAM 3.1" },
  { key: "2.TRIAGE", label: "TRIAGE", model: "Muse Spark" },
  { key: "3.DIAGNOSE", label: "DIAGNOSE", model: "Muse Wonder" },
  { key: "4.PATCH", label: "PATCH", model: "Muse Code" },
  { key: "5.VERIFY", label: "VERIFY", model: "Modal HMR (Strike Loop)" },
];

export function LiveTrace({
  currentStep = "1.SENSE",
  strikes = 0,
  events = [
    { timestamp: "00:01.2", step: "SENSE", message: "DOM bounding boxes extracted (Playwright 375x812)" },
    { timestamp: "00:02.4", step: "SENSE", message: "SAM 3.1 segmented M_SAM for visor-el-04 (V_r = 0.62 < 0.85)" },
  ],
}: LiveTraceProps) {
  const currentIndex = STEPS.findIndex((s) => s.key === currentStep);

  return (
    <div className="flex flex-col bg-surface border border-border-subtle rounded-lg p-4 gap-4">
      {/* FSM Top Stepper */}
      <div className="flex items-center justify-between pb-3 border-b border-border-subtle">
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-cyan-400 animate-pulse" />
          <span className="font-display font-semibold text-sm">Autonomous FSM Pipeline</span>
        </div>
        <div className="text-xs font-mono text-text-muted">
          Self-Healing Strike: <span className="text-triage-amber font-semibold">{strikes}/3</span>
        </div>
      </div>

      {/* 5-Node Visual Stepper */}
      <div className="grid grid-cols-5 gap-2">
        {STEPS.map((step, index) => {
          const isActive = index === currentIndex;
          const isDone = index < currentIndex;
          return (
            <div
              key={step.key}
              className={`p-2.5 rounded-md border text-center transition-all ${
                isActive
                  ? "bg-elevated border-text-primary shadow-[0_0_12px_rgba(56,189,248,0.2)]"
                  : isDone
                  ? "bg-surface border-border-subtle text-text-secondary"
                  : "bg-canvas/50 border-border-subtle/50 text-text-muted"
              }`}
            >
              <div className="flex items-center justify-center gap-1 mb-1">
                {isActive ? (
                  <Loader2 className="w-3 h-3 animate-spin text-cyan-400" />
                ) : isDone ? (
                  <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                ) : (
                  <span className="w-2 h-2 rounded-full bg-text-muted/40" />
                )}
                <span className="text-xs font-mono font-medium">{step.label}</span>
              </div>
              <div className="text-[10px] text-text-muted truncate">{step.model}</div>
            </div>
          );
        })}
      </div>

      {/* Real-Time Trace Log Stream */}
      <div className="mt-2 bg-canvas/80 border border-border-subtle rounded-md p-3 font-mono text-xs max-h-48 overflow-y-auto space-y-1.5">
        {events.map((evt, i) => (
          <div key={i} className="flex items-start gap-2 text-text-secondary">
            <span className="text-text-muted">[{evt.timestamp}]</span>
            <span className="text-cyan-400">[{evt.step}]</span>
            <span className="text-text-primary">{evt.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
