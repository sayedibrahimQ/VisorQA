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
import { useAuth } from "@/context/AuthContext";
import { LoginGate } from "@/components/auth/LoginGate";
import { RepoSelector } from "@/components/auth/RepoSelector";
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
interface GitHubPull {
  number: number;
  title: string;
  state: string;
  head_ref: string;
  head_sha: string;
  base_ref: string;
  user_login: string;
  updated_at: string;
  html_url: string;
}

export default function MissionControlPage() {
  const { user, loading: authLoading, logout } = useAuth();
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

  // --- Repository scoping (strict: everything below filters by repo) ---
  const [selectedRepo, setSelectedRepo] = useState<string | null>(null);
  useEffect(() => {
    const param = new URLSearchParams(window.location.search).get("repo");
    if (param) setSelectedRepo(param);
  }, []);
  const selectRepo = (repoFullName: string) => {
    setSelectedRepo(repoFullName);
    const url = new URL(window.location.href);
    url.searchParams.set("repo", repoFullName);
    window.history.replaceState(null, "", url.toString());
  };
  const scopedRuns = selectedRepo
    ? runs.filter((r) => r.repo_name === selectedRepo)
    : runs;

  const [pulls, setPulls] = useState<GitHubPull[]>([]);
  const [branches, setBranches] = useState<{ name: string; sha: string }[]>([]);
  const [pullsError, setPullsError] = useState<string | null>(null);
  const [scanBranch, setScanBranch] = useState("");
  const [actionMsg, setActionMsg] = useState<{ text: string; href?: string } | null>(null);

  useEffect(() => {
    if (!user || !selectedRepo) {
      setPulls([]);
      setBranches([]);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const [owner, repo] = selectedRepo.split("/");
        const [pr, br] = await Promise.all([
          fetch(`${apiBase}/api/github/repos/${owner}/${repo}/pulls`, { credentials: "include" }),
          fetch(`${apiBase}/api/github/repos/${owner}/${repo}/branches`, { credentials: "include" }),
        ]);
        if (!pr.ok) throw new Error(`Pull requests failed (${pr.status})`);
        const prBody: unknown = await pr.json();
        if (!cancelled && Array.isArray(prBody)) setPulls(prBody as GitHubPull[]);
        if (br.ok) {
          const brBody: unknown = await br.json();
          if (!cancelled && Array.isArray(brBody)) {
            setBranches(brBody as { name: string; sha: string }[]);
          }
        }
        if (!cancelled) setPullsError(null);
      } catch (err) {
        if (!cancelled) {
          setPullsError(err instanceof Error ? err.message : "Pull requests failed");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user, selectedRepo, apiBase]);

  const dispatchScan = async (prNumber: number, branch: string, sha: string) => {
    if (!selectedRepo) return;
    setActionMsg(null);
    try {
      const res = await fetch(`${apiBase}/api/runs`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          pr_number: prNumber,
          repo_full_name: selectedRepo,
          branch,
          commit_sha: sha,
          dispatch: true,
        }),
      });
      const body: unknown = await res.json().catch(() => null);
      if (!res.ok) throw new Error(`Scan dispatch failed (${res.status})`);
      const id =
        body && typeof body === "object" && "id" in body
          ? String((body as Record<string, unknown>).id)
          : "";
      setActionMsg({ text: `Optical QA scan dispatched for ${selectedRepo}${prNumber ? ` PR #${prNumber}` : ` @ ${branch}`} (run ${id}). Live progress streams in automatically.` });
    } catch (err) {
      setActionMsg({ text: err instanceof Error ? err.message : "Scan dispatch failed" });
    }
  };

  const postGitHubAction = async (kind: "comment" | "commit") => {
    if (!activeRun) return;
    setActionMsg(null);
    try {
      const res = await fetch(`${apiBase}/api/runs/${activeRun.id}/github/${kind}`, {
        method: "POST",
        credentials: "include",
      });
      const body: unknown = await res.json().catch(() => null);
      if (!res.ok) {
        const detail =
          body && typeof body === "object" && "detail" in body
            ? String((body as Record<string, unknown>).detail)
            : `${kind} failed (${res.status})`;
        throw new Error(detail);
      }
      const record = body as Record<string, unknown>;
      if (kind === "comment") {
        setActionMsg({ text: "Telemetry report posted to the GitHub PR.", href: String(record.html_url ?? "") });
      } else {
        setActionMsg({
          text: `Fix committed: ${String(record.sha ?? "").slice(0, 7)} on ${String(record.branch ?? "")}.`,
          href: String(record.html_url ?? ""),
        });
      }
    } catch (err) {
      setActionMsg({ text: err instanceof Error ? err.message : `${kind} failed` });
    }
  };

  if (authLoading) {
    return (
      <main className="min-h-screen bg-canvas text-text-primary">
        <p data-testid="auth-loading" className="px-4 py-10 text-sm text-text-secondary">
          Checking GitHub session…
        </p>
      </main>
    );
  }

  if (!user) {
    return (
      <main className="min-h-screen bg-canvas text-text-primary">
        <div className="mx-auto max-w-[1440px] px-4 py-6">
          <h1 className="font-display text-2xl font-semibold">Mission Control</h1>
          <LoginGate />
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-canvas text-text-primary">
      <div className="mx-auto max-w-[1440px] px-4 py-6">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border-subtle pb-4">
          <div className="min-w-0">
            <h1 className="font-display text-2xl font-semibold">
              Mission Control
            </h1>
            <p className="mt-1 truncate text-sm text-text-secondary">
              Live PR telemetry — new webhook runs focus automatically.
            </p>
            <div
              data-testid="connection-status"
              className="mt-1 font-mono text-xs text-text-secondary"
            >
              {status}
              {status === "reconnecting" ? ` (retry ${reconnectAttempt})` : ""}
              {focusLatencyMs !== null
                ? ` · focus ${focusLatencyMs.toFixed(0)}ms`
                : ""}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <RepoSelector selectedRepo={selectedRepo} onSelect={selectRepo} />
            <div data-testid="user-chip" className="flex items-center gap-2 rounded-md border border-border-subtle bg-surface px-2 py-1.5">
              {user.avatar_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={user.avatar_url} alt="" className="h-5 w-5 rounded-full" />
              ) : null}
              <span className="font-mono text-xs text-text-primary">{user.login}</span>
              <span className="font-mono text-[10px] text-text-muted">{user.auth_mode}</span>
              <button
                type="button"
                data-testid="logout-button"
                onClick={() => void logout()}
                className="font-mono text-[11px] text-text-secondary hover:text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-border-focus"
              >
                Sign Out
              </button>
            </div>
          </div>
        </div>

        {!selectedRepo ? (
          <p data-testid="repo-onboarding" className="mt-4 rounded-md border border-border-subtle bg-surface px-3 py-2.5 text-sm text-text-secondary">
            Select one of your GitHub repositories (top right) to scope pull
            requests, runs, telemetry, and actions to it.
          </p>
        ) : null}

        <div className="mt-5 grid min-w-0 gap-4 md:grid-cols-[240px_minmax(0,1fr)] lg:grid-cols-[292px_minmax(0,1fr)] xl:grid-cols-[292px_minmax(0,1fr)_380px]">
          <div className="min-w-0 space-y-4">
            {selectedRepo ? (
              <section
                aria-label="Repository pull requests"
                data-testid="repo-pulls"
                className="rounded-md border border-border-subtle bg-surface-subtle p-3"
              >
                <h2 className="font-display text-sm font-semibold text-text-primary">
                  {selectedRepo} Pull Requests
                </h2>
                {pullsError ? (
                  <p role="alert" className="mt-2 text-xs text-defect-crimson">{pullsError}</p>
                ) : pulls.length === 0 ? (
                  <p data-testid="repo-pulls-empty" className="mt-2 text-xs text-text-secondary">
                    No pull requests found for this repository yet. Scan a branch below to start a run.
                  </p>
                ) : (
                  <ul className="mt-2 space-y-2">
                    {pulls.map((pr) => {
                      const match = scopedRuns.find((r) => r.pr_number === pr.number);
                      return (
                        <li key={pr.number} data-testid={`pr-row-${pr.number}`} className="rounded-md border border-border-subtle bg-surface px-2.5 py-2">
                          <div className="flex items-baseline justify-between gap-2">
                            <span className="font-mono text-xs text-text-primary">#{pr.number}</span>
                            <span className="font-mono text-[10px] text-text-muted">{pr.state}</span>
                          </div>
                          <p className="mt-0.5 truncate text-xs text-text-secondary">{pr.title}</p>
                          <p className="mt-0.5 truncate font-mono text-[10px] text-text-muted">
                            {pr.head_ref} · {pr.head_sha.slice(0, 7)} · by {pr.user_login}
                          </p>
                          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                            {match ? (
                              <button
                                type="button"
                                onClick={() => selectRun(match.id)}
                                className="rounded-sm border border-neural-pulse/50 px-1.5 py-0.5 font-mono text-[10px] text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-border-focus"
                              >
                                Run: {match.status}
                              </button>
                            ) : null}
                            <button
                              type="button"
                              data-testid={`scan-pr-${pr.number}`}
                              onClick={() => void dispatchScan(pr.number, pr.head_ref, pr.head_sha)}
                              className="rounded-sm border border-border-subtle px-1.5 py-0.5 font-mono text-[10px] text-text-secondary hover:text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-border-focus"
                            >
                              Run Optical QA Scan
                            </button>
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                )}
                {branches.length > 0 ? (
                  <div className="mt-3 flex items-center gap-1.5">
                    <select
                      data-testid="branch-select"
                      aria-label="Branch to scan"
                      value={scanBranch}
                      onChange={(e) => setScanBranch(e.target.value)}
                      className="min-w-0 flex-1 rounded-sm border border-border-subtle bg-canvas px-1.5 py-1 font-mono text-[11px] text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-border-focus"
                    >
                      <option value="">Scan a branch…</option>
                      {branches.map((b) => (
                        <option key={b.name} value={b.name}>
                          {b.name} · {b.sha.slice(0, 7)}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      data-testid="scan-branch"
                      disabled={!scanBranch}
                      onClick={() => {
                        const b = branches.find((x) => x.name === scanBranch);
                        if (b) void dispatchScan(0, b.name, b.sha);
                      }}
                      className="shrink-0 rounded-sm border border-border-subtle px-1.5 py-1 font-mono text-[10px] text-text-secondary hover:text-text-primary disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-border-focus"
                    >
                      Scan
                    </button>
                  </div>
                ) : null}
              </section>
            ) : null}
            <PRRunSidebar
              runs={scopedRuns}
              activeRunId={activeRunId}
              loading={loading}
              error={error}
              connectionStatus={status}
              onSelect={(id) => selectRun(id)}
              className="min-w-0"
            />
          </div>

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
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  <button
                    type="button"
                    data-testid="action-comment"
                    onClick={() => void postGitHubAction("comment")}
                    className="rounded-sm border border-border-subtle px-2 py-1 font-mono text-[11px] text-text-secondary hover:text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-border-focus"
                  >
                    Post Telemetry Report to GitHub PR
                  </button>
                  <button
                    type="button"
                    data-testid="action-commit"
                    onClick={() => void postGitHubAction("commit")}
                    className="rounded-sm border border-border-subtle px-2 py-1 font-mono text-[11px] text-text-secondary hover:text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-border-focus"
                  >
                    Commit &amp; Push Fix to PR Branch
                  </button>
                  {actionMsg ? (
                    <span data-testid="action-result" className="font-mono text-[11px] text-text-secondary">
                      {actionMsg.text}{" "}
                      {actionMsg.href ? (
                        <a
                          href={actionMsg.href}
                          target="_blank"
                          rel="noreferrer"
                          className="text-neural-pulse hover:text-text-primary"
                        >
                          View on GitHub
                        </a>
                      ) : null}
                    </span>
                  ) : null}
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
