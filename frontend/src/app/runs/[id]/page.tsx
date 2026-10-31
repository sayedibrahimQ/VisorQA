"use client";

/**
 * Run Inspector permalink (/runs/[runId]).
 *
 * 100% live data: hydrates GET /api/runs/{id} and renders the shared
 * DualViewportStage + telemetry drawer components. No demo catalog, no
 * fabricated runs — unknown or unloaded runs show explicit states.
 */

import React, { use, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Loader2 } from "lucide-react";
import { useRunDetails } from "@/hooks/useRunDetails";
import { resolveApiBase } from "@/hooks/useMissionControlStream";
import { DualViewportStage } from "@/components/mission-control/DualViewportStage";
import { MathTrapScorecard } from "@/components/mission-control/MathTrapScorecard";
import { LCATriageTree } from "@/components/mission-control/LCATriageTree";
import { ArchitectCoderInspector } from "@/components/mission-control/ArchitectCoderInspector";
import { adaptRunToStage } from "@/lib/viewportArtifacts";
import {
  attemptOptions,
  inspectorForAttempt,
  latestAttemptNumber,
  scorecardForAttempt,
  stageForAttempt,
  triageForRun,
} from "@/lib/runDetails";

export default function RunInspectorPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const apiBase = resolveApiBase();
  const { details, loading, error } = useRunDetails(id);
  const [selectedAttempt, setSelectedAttempt] = useState<number | null>(null);

  useEffect(() => {
    setSelectedAttempt(null);
  }, [id]);

  const effectiveAttempt = selectedAttempt ?? latestAttemptNumber(details);
  const liveStage = details ? stageForAttempt(details, effectiveAttempt, apiBase) : null;
  const fallbackStage = adaptRunToStage(null);
  const liveScorecard = details ? scorecardForAttempt(details, effectiveAttempt) : null;

  return (
    <main className="min-h-screen bg-canvas text-text-primary">
      <div className="mx-auto max-w-[1440px] px-4 py-6">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border-subtle pb-4">
          <div className="flex min-w-0 items-center gap-3">
            <Link
              href="/mission-control"
              className="flex items-center gap-1.5 font-mono text-xs text-text-secondary hover:text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-border-focus"
            >
              <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
              Mission Control
            </Link>
            <h1 className="truncate font-display text-xl font-semibold">
              Run Inspector
            </h1>
          </div>
          {details ? (
            <span data-testid="inspector-run-meta" className="font-mono text-xs text-text-secondary">
              {details.repo_name} PR #{details.pr_number} · {details.status} · strike{" "}
              {details.strikes}/3
            </span>
          ) : null}
        </div>

        {loading && !details ? (
          <p data-testid="inspector-loading" className="flex items-center gap-2 py-10 text-sm text-text-secondary">
            <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" />
            Loading run {id}…
          </p>
        ) : null}
        {error ? (
          <p data-testid="inspector-error" role="alert" className="py-10 text-sm text-defect-crimson">
            Could not load run {id}: {error}
          </p>
        ) : null}
        {!loading && !error && !details ? (
          <p data-testid="inspector-empty" className="py-10 text-sm text-text-secondary">
            Run {id} has no hydrated telemetry yet. If the run is live, its
            details appear here as soon as the backend persists them.
          </p>
        ) : null}

        {details ? (
          <div className="mt-5 grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
            <DualViewportStage
              runId={details.id}
              runLabel={`${details.repo_name} PR #${details.pr_number}`}
              mobile={liveStage ? liveStage.mobile : fallbackStage.mobile}
              desktop={liveStage ? liveStage.desktop : fallbackStage.desktop}
              hmr={liveStage ? liveStage.hmr : null}
              attempts={attemptOptions(details)}
              selectedAttempt={effectiveAttempt}
              onAttemptChange={setSelectedAttempt}
              sandboxProvider={liveStage?.sandboxProvider ?? null}
              hmrLatencyMs={liveStage?.hmrLatencyMs ?? null}
            />
            <aside
              aria-label="Run telemetry drawer"
              className="min-w-0 space-y-5 rounded-md border border-border-subtle bg-surface-subtle p-3"
            >
              <MathTrapScorecard
                current={liveScorecard ? liveScorecard.current : null}
                best={null}
                baseline={liveScorecard?.baseline ?? null}
                runActive={details.status === "RUNNING"}
              />
              <div className="border-t border-border-subtle" />
              <LCATriageTree triage={triageForRun(details)} />
              <div className="border-t border-border-subtle" />
              <ArchitectCoderInspector
                data={inspectorForAttempt(details, effectiveAttempt)}
                runId={details.id}
              />
            </aside>
          </div>
        ) : null}
      </div>
    </main>
  );
}
