"use client";

import React, { useEffect, useState } from "react";
import {
  resolveApiBase,
  useMissionControlStream,
} from "@/hooks/useMissionControlStream";
import { useRunDetails } from "@/hooks/useRunDetails";
import { LiveTrace } from "@/components/LiveTrace";
import { PRRunSidebar } from "@/components/mission-control/PRRunSidebar";
import { FSMOrchestratorBar } from "@/components/mission-control/FSMOrchestratorBar";
import { ThreeStrikeLoop } from "@/components/mission-control/ThreeStrikeLoop";
import { DualViewportStage } from "@/components/mission-control/DualViewportStage";
import { MathTrapScorecard } from "@/components/mission-control/MathTrapScorecard";
import { LCATriageTree } from "@/components/mission-control/LCATriageTree";
import { ArchitectCoderInspector } from "@/components/mission-control/ArchitectCoderInspector";
import { getAttemptState, isHistoricalRun } from "@/lib/fsmSelectors";
import { adaptRunToStage } from "@/lib/viewportArtifacts";
import { getInspector, getScorecard, getTriage } from "@/lib/telemetryDrawer";
import {
  attemptOptions,
  inspectorForAttempt,
  latestAttemptNumber,
  scorecardForAttempt,
  stageForAttempt,
  triageForRun,
} from "@/lib/runDetails";

/**
 * Mission Control workspace. The active run is focused automatically when a
 * GitHub webhook PR run arrives over the telemetry socket — no manual trigger.
 * All children below share this single `useMissionControlStream` subscription;
 * no second WebSocket is opened.
 */
export default function MissionControlPage() {
  const {
    runs,
    activeRun,
    activeRunId,
    status,
    loading,
    error,
    reconnectAttempt,
    focusLatencyMs,
    lastEventAt,
    selectRun,
  } = useMissionControlStream();

  // Workstream 2: hydrate rich details for the selection. liveKey changes
  // on WS status/strike transitions (incl. terminal) -> immediate refetch;
  // the hook's generation guard drops stale in-flight responses.
  const liveKey = `${activeRun?.status ?? ""}:${activeRun?.strikes ?? 0}:${lastEventAt ?? ""}`;
  const { details } = useRunDetails(activeRunId, { liveKey });
  const apiBase = resolveApiBase();

  const [selectedAttempt, setSelectedAttempt] = useState<number | null>(null);
  useEffect(() => {
    setSelectedAttempt(null);
  }, [activeRunId]);
  const effectiveAttempt = selectedAttempt ?? latestAttemptNumber(details);

  const stage = adaptRunToStage(activeRun);
  const liveStage = details ? stageForAttempt(details, effectiveAttempt, apiBase) : null;
  const liveScorecard = details ? scorecardForAttempt(details, effectiveAttempt) : null;
  const scorecard = getScorecard(activeRun);
  const triage = details ? triageForRun(details) : getTriage(activeRun);
  const inspector = details
    ? inspectorForAttempt(details, effectiveAttempt)
    : getInspector(activeRun);
  const runActive = activeRun !== null && !isHistoricalRun(activeRun);

  return (
    <main className="min-h-screen bg-canvas text-text-primary">
      <div className="mx-auto max-w-[1440px] px-4 py-6">
        <div className="flex items-baseline justify-between gap-4 border-b border-border-subtle pb-4">
          <div className="min-w-0">
            <h1 className="font-display text-2xl font-semibold">
              Mission Control
            </h1>
            <p className="mt-1 truncate text-sm text-text-secondary">
              Live PR telemetry — new webhook runs focus automatically.
            </p>
          </div>
          <div
            data-testid="connection-status"
            className="shrink-0 font-mono text-xs text-text-secondary"
          >
            {status}
            {status === "reconnecting" ? ` (retry ${reconnectAttempt})` : ""}
            {focusLatencyMs !== null
              ? ` · focus ${focusLatencyMs.toFixed(0)}ms`
              : ""}
          </div>
        </div>

        <div className="mt-5 grid min-w-0 gap-4 md:grid-cols-[240px_minmax(0,1fr)] lg:grid-cols-[292px_minmax(0,1fr)] xl:grid-cols-[292px_minmax(0,1fr)_380px]">
          <PRRunSidebar
            runs={runs}
            activeRunId={activeRunId}
            loading={loading}
            error={error}
            connectionStatus={status}
            onSelect={(id) => selectRun(id)}
            className="min-w-0"
          />

          <section aria-label="Active workspace" aria-live="polite" className="min-w-0">
            {activeRun ? (
              <div data-testid="active-run" data-run-id={activeRun.id} className="min-w-0">
                <div className="flex flex-wrap items-baseline justify-between gap-3">
                  <h2 className="min-w-0 truncate text-sm font-semibold text-text-secondary">
                    Active workspace — {activeRun.repo_name} PR #
                    {activeRun.pr_number}
                  </h2>
                  <ThreeStrikeLoop attempt={getAttemptState(activeRun)} />
                </div>
                <div className="mt-3">
                  <FSMOrchestratorBar run={activeRun} />
                </div>
                <div className="mt-4">
                  <DualViewportStage
                    runId={stage.runId}
                    runLabel={stage.runLabel}
                    mobile={liveStage ? liveStage.mobile : stage.mobile}
                    desktop={liveStage ? liveStage.desktop : stage.desktop}
                    hmr={liveStage ? liveStage.hmr : stage.hmr}
                    untaggedCount={stage.untaggedCount}
                    attempts={attemptOptions(details)}
                    selectedAttempt={effectiveAttempt}
                    onAttemptChange={setSelectedAttempt}
                    sandboxProvider={liveStage?.sandboxProvider ?? null}
                    hmrLatencyMs={liveStage?.hmrLatencyMs ?? null}
                  />
                </div>
                <div className="mt-4">
                  <LiveTrace
                    currentStep={activeRun.current_step}
                    strikes={activeRun.strikes}
                  />
                </div>
                <dl className="mt-3 grid grid-cols-2 gap-2 font-mono text-xs text-text-secondary sm:grid-cols-3">
                  <div>
                    <dt>Branch</dt>
                    <dd className="truncate text-text-primary">{activeRun.branch}</dd>
                  </div>
                  <div>
                    <dt>Commit</dt>
                    <dd className="truncate text-text-primary">
                      {activeRun.commit_sha}
                    </dd>
                  </div>
                  <div>
                    <dt>Status</dt>
                    <dd className="text-text-primary">{activeRun.status}</dd>
                  </div>
                  <div>
                    <dt>Anomalies</dt>
                    <dd className="text-text-primary">
                      {activeRun.anomalies_count ?? 0}
                    </dd>
                  </div>
                  <div>
                    <dt>Attempt</dt>
                    <dd className="text-text-primary">
                      {activeRun.strikes}/3
                    </dd>
                  </div>
                  <div>
                    <dt>Updated</dt>
                    <dd className="truncate text-text-primary">
                      {activeRun.updated_at ?? "—"}
                    </dd>
                  </div>
                </dl>
              </div>
            ) : (
              <div className="min-w-0">
                <FSMOrchestratorBar run={null} />
                <p data-testid="no-active-run" className="mt-4 text-sm text-text-secondary">
                  No active run. New PR runs appear here automatically.
                </p>
              </div>
            )}
          </section>

          <aside
            aria-label="Telemetry inspector drawer"
            data-testid="telemetry-drawer"
            data-width="380px"
            className="min-w-0"
          >
            <div className="space-y-5 rounded-md border border-border-subtle bg-surface-subtle p-3">
              <MathTrapScorecard
                current={liveScorecard ? liveScorecard.current : scorecard.current}
                best={liveScorecard ? null : scorecard.best}
                baseline={liveScorecard?.baseline ?? null}
                runActive={runActive}
              />
              <div className="border-t border-border-subtle" />
              <LCATriageTree triage={triage} />
              <div className="border-t border-border-subtle" />
              <ArchitectCoderInspector data={inspector} runId={activeRunId} />
            </div>
          </aside>
        </div>
      </div>
    </main>
  );
}
