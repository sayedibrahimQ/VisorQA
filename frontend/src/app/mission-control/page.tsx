"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import Image from "next/image";
import { ScanEye, CheckCircle2, ExternalLink, Loader2, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
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
  const apiBase = resolveApiBase();

  // --- Watched repository (Task 1: DB-persisted singleton, strict scope) ---
  const [selectedRepo, setSelectedRepo] = useState<string | null>(null);
  const [watchedRepo, setWatchedRepo] = useState<{
    repo_full_name: string;
    default_branch: string;
    webhook_active: boolean;
    auto_heal_enabled: boolean;
  } | null>(null);
  const [watchedLoaded, setWatchedLoaded] = useState(false);
  const [pickerDismissed, setPickerDismissed] = useState(false);
  const [watchError, setWatchError] = useState<string | null>(null);
  useEffect(() => {
    const param = new URLSearchParams(window.location.search).get("repo");
    if (param) setSelectedRepo(param);
  }, []);

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
    rehydrate,
    clearRuns,
    applyRunUpdate,
  } = useMissionControlStream({ repo: selectedRepo ?? undefined });
  // Boot: the DB-persisted watched repo is the source of truth and wins
  // over any stale ?repo= param.
  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${apiBase}/api/settings/watched-repo`, {
          credentials: "include",
        });
        const body: unknown = res.ok ? await res.json().catch(() => null) : null;
        if (cancelled) return;
        if (
          body &&
          typeof body === "object" &&
          typeof (body as Record<string, unknown>).repo_full_name === "string"
        ) {
          const record = body as {
            repo_full_name: string;
            default_branch: string;
            webhook_active: boolean;
            auto_heal_enabled: boolean;
          };
          setWatchedRepo(record);
          setSelectedRepo(record.repo_full_name);
          const url = new URL(window.location.href);
          url.searchParams.set("repo", record.repo_full_name);
          window.history.replaceState(null, "", url.toString());
        }
      } catch {
        /* watched state unknown; picker stays available via RepoSelector */
      } finally {
        if (!cancelled) setWatchedLoaded(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user, apiBase]);
  const selectRepo = (repoFullName: string) => {
    const previousWatched = watchedRepo;
    setSelectedRepo(repoFullName);
    selectRun(null);
    // Auto-confirm: lock the header badge onto the selection immediately;
    // the server record below replaces this optimistic entry, and a
    // failed POST rolls it back and surfaces the error in the picker.
    setWatchedRepo({
      repo_full_name: repoFullName,
      default_branch:
        previousWatched?.repo_full_name === repoFullName
          ? previousWatched.default_branch
          : "main",
      webhook_active:
        previousWatched?.repo_full_name === repoFullName
          ? previousWatched.webhook_active
          : false,
      auto_heal_enabled: true,
    });
    const url = new URL(window.location.href);
    url.searchParams.set("repo", repoFullName);
    window.history.replaceState(null, "", url.toString());
    // Persist as THE watched repository (backend validates vs GitHub).
    void (async () => {
      try {
        const res = await fetch(`${apiBase}/api/settings/watched-repo`, {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ repo_full_name: repoFullName }),
        });
        const body: unknown = await res.json().catch(() => null);
        if (!res.ok) {
          const detail =
            body && typeof body === "object" && "detail" in body
              ? String((body as Record<string, unknown>).detail)
              : `Could not persist watched repository (${res.status})`;
          throw new Error(detail);
        }
        const record =
          body && typeof body === "object" && "watched_repo" in body
            ? (body as Record<string, unknown>).watched_repo
            : null;
        if (
          record &&
          typeof record === "object" &&
          typeof (record as Record<string, unknown>).repo_full_name === "string"
        ) {
          setWatchedRepo(
            record as {
              repo_full_name: string;
              default_branch: string;
              webhook_active: boolean;
              auto_heal_enabled: boolean;
            },
          );
          setWatchError(null);
          setPickerDismissed(true);
        }
      } catch (err) {
        setWatchedRepo(previousWatched);
        setPickerDismissed(false);
        setWatchError(err instanceof Error ? err.message : "Could not persist watched repository");
      }
    })();
  };
  const scopedRuns = selectedRepo
    ? runs.filter((r) => r.repo_name === selectedRepo)
    : runs;

  // Active run must belong to the selected repo if one is selected; otherwise null (wait for user PR selection)
  const scopedActiveRun =
    activeRun && selectedRepo && activeRun.repo_name && activeRun.repo_name !== selectedRepo
      ? null
      : activeRun;
  const effectiveActiveRunId = scopedActiveRun ? scopedActiveRun.id : null;

  // Workstream 2: hydrate rich details for the selection. liveKey changes
  // on WS status/strike transitions (incl. terminal) -> immediate refetch;
  // the hook's generation guard drops stale in-flight responses.
  const liveKey = `${scopedActiveRun?.status ?? ""}:${scopedActiveRun?.strikes ?? 0}:${lastEventAt ?? ""}`;
  const { details, loading: detailsLoading } = useRunDetails(effectiveActiveRunId, { liveKey });

  const [selectedAttempt, setSelectedAttempt] = useState<number | null>(null);
  useEffect(() => {
    setSelectedAttempt(null);
  }, [effectiveActiveRunId]);
  const effectiveAttempt = selectedAttempt ?? latestAttemptNumber(details);

  const stage = adaptRunToStage(scopedActiveRun);
  const liveStage = details ? stageForAttempt(details, effectiveAttempt, apiBase) : null;
  const liveScorecard = details ? scorecardForAttempt(details, effectiveAttempt) : null;
  const scorecard = getScorecard(scopedActiveRun);
  const triage = details ? triageForRun(details) : getTriage(scopedActiveRun);
  const inspector = details
    ? inspectorForAttempt(details, effectiveAttempt)
    : getInspector(scopedActiveRun);
  const runActive = scopedActiveRun !== null && !isHistoricalRun(scopedActiveRun);
  // Executing with no real screenshot yet: honest capturing skeleton.
  const stageCapturing =
    runActive &&
    !liveStage?.mobile.beforeUrl &&
    !liveStage?.desktop.beforeUrl &&
    !stage.mobile.beforeUrl &&
    !stage.desktop.beforeUrl;
  // Build/boot failure: surface the real backend error, never a fake shot.
  const stageError = (() => {
    if (!scopedActiveRun || !["FAILED", "ESCALATED", "HALTED"].includes(scopedActiveRun.status)) {
      return null;
    }
    const reasons: string[] = [];
    const rootSpec = (details as Record<string, unknown> | null | undefined)?.repair_spec as Record<string, unknown> | null | undefined;
    for (const key of ["sense_error", "patch_error", "diagnose_error", "triage_error"]) {
      const v = rootSpec?.[key];
      if (typeof v === "string" && v && !reasons.includes(v)) reasons.push(v);
    }
    for (const att of details?.attempts ?? []) {
      const spec = att.repair_spec as Record<string, unknown> | null | undefined;
      for (const key of ["sense_error", "patch_error", "diagnose_error", "triage_error"]) {
        const v = spec?.[key];
        if (typeof v === "string" && v && !reasons.includes(v)) reasons.push(v);
      }
      if (att.attempt_number > 0 || att.verification_feedback?.dual_viewport_passed !== null) {
        for (const r of att.verification_feedback?.failure_reasons ?? []) {
          if (r && !reasons.includes(r)) reasons.push(r);
        }
      }
    }
    return reasons.length > 0
      ? reasons.join(" · ")
      : `Run ${scopedActiveRun.status.toLowerCase()} — see telemetry drawer for the real error log.`;
  })();

  const [clearingRuns, setClearingRuns] = useState(false);
  const handleClearRuns = async () => {
    setClearingRuns(true);
    try {
      const url = selectedRepo
        ? `${apiBase}/api/runs?repo=${encodeURIComponent(selectedRepo)}`
        : `${apiBase}/api/runs`;
      const res = await fetch(url, { method: "DELETE", credentials: "include" });
      if (res.ok) {
        clearRuns();
        selectRun(null);
        rehydrate();
      }
    } catch (err) {
      console.error("Failed to clear runs:", err);
    } finally {
      setClearingRuns(false);
    }
  };

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
      if (id) {
        if (body && typeof body === "object") {
          applyRunUpdate(body as Record<string, unknown>);
        }
        selectRun(id);
        rehydrate();
      }
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

  // --- Judge Demo Journey Handlers ---
  const [demoBusy, setDemoBusy] = useState(false);
  const [demoMessage, setDemoMessage] = useState<string | null>(null);

  const handlePushBuggyBranch = async () => {
    setDemoBusy(true);
    setDemoMessage("Pushing buggy branch & opening GitHub PR…");
    try {
      const res = await fetch(`${apiBase}/api/demo/push-buggy-branch`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          repo: selectedRepo || "sayedibrahimQ/aether-hardware",
        }),
      });
      const body: unknown = await res.json().catch(() => null);
      if (!res.ok) {
        const detail =
          body && typeof body === "object" && "detail" in body
            ? String((body as Record<string, unknown>).detail)
            : `Failed to push buggy branch (${res.status})`;
        throw new Error(detail);
      }
      const data = body as {
        ok: boolean;
        pr_number: number;
        html_url: string;
        run_id: string;
        message: string;
      };
      setDemoMessage(
        `PR #${data.pr_number} open on GitHub! Agent run started (${data.run_id?.slice(0, 8)}…).`
      );
      if (data.run_id) {
        selectRun(data.run_id);
      }
      rehydrate();
    } catch (err) {
      setDemoMessage(err instanceof Error ? err.message : "Failed to push buggy branch");
    } finally {
      setDemoBusy(false);
    }
  };

  const handleResetDemoSlate = async () => {
    setDemoBusy(true);
    setDemoMessage("Resetting demo repository to clean slate (0 PRs)…");
    try {
      const res = await fetch(`${apiBase}/api/demo/reset-slate`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          repo: selectedRepo || "sayedibrahimQ/aether-hardware",
        }),
      });
      const body: unknown = await res.json().catch(() => null);
      if (!res.ok) {
        const detail =
          body && typeof body === "object" && "detail" in body
            ? String((body as Record<string, unknown>).detail)
            : `Failed to reset demo slate (${res.status})`;
        throw new Error(detail);
      }
      const data = body as { message: string };
      setDemoMessage(data.message || "Clean slate restored (0 open PRs).");
      await handleClearRuns();
    } catch (err) {
      setDemoMessage(err instanceof Error ? err.message : "Failed to reset demo slate");
    } finally {
      setDemoBusy(false);
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
          <div className="flex items-center gap-3 mb-6">
            <Link href="/" className="flex items-center gap-2 group">
              <Image
                src="/logo.png"
                alt="VisorQA"
                width={130}
                height={36}
                className="h-8 w-auto object-contain transition-transform duration-200 group-hover:scale-105"
              />
            </Link>
            <span className="text-border-strong select-none">/</span>
            <h1 className="font-display text-xl font-semibold text-zinc-300">Mission Control</h1>
          </div>
          <LoginGate />
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-canvas text-text-primary md:h-screen md:overflow-hidden md:flex md:flex-col">
      <div className="mx-auto w-full max-w-[1680px] p-4 sm:p-6 flex flex-col flex-1 min-h-0">
        <div className="shrink-0 flex flex-wrap items-start justify-between gap-3 border-b border-border-subtle pb-4">
          <div className="min-w-0">
            <div className="flex items-center gap-3">
              <Link href="/" className="flex items-center gap-2 group transition-transform active:scale-95" title="Back to VisorQA Home">
                <Image
                  src="/visor-icon.png"
                  alt="VisorQA"
                  width={28}
                  height={28}
                  className="h-7 w-7 rounded object-contain transition-transform duration-200 group-hover:scale-105"
                />
              </Link>
              <h1 className="font-display text-2xl font-semibold">
                Mission Control
              </h1>
            </div>
            <p className="mt-1 truncate text-sm text-text-secondary">
              Live PR telemetry — new webhook runs focus automatically.
            </p>
            <div
              data-testid="connection-status"
              className="mt-1 flex items-center gap-1.5 font-mono text-xs text-text-secondary"
            >
              <span
                className={cn(
                  "inline-block h-2 w-2 rounded-full",
                  status === "open"
                    ? "bg-emerald-400"
                    : status === "reconnecting" && reconnectAttempt >= 2
                    ? "bg-emerald-400/80 animate-pulse"
                    : status === "reconnecting"
                    ? "bg-amber-400 animate-pulse"
                    : "bg-text-muted/60",
                )}
              />
              <span>
                {status === "open"
                  ? "open"
                  : status === "reconnecting" && reconnectAttempt >= 2
                  ? `live (polling) · ws reconnecting (retry ${reconnectAttempt})`
                  : status === "reconnecting"
                  ? `reconnecting (retry ${reconnectAttempt})`
                  : status}
                {focusLatencyMs !== null
                  ? ` · focus ${focusLatencyMs.toFixed(0)}ms`
                  : ""}
              </span>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {selectedRepo ? (
              <span
                data-testid="watching-pill"
                className="rounded-sm border border-laser-cyan/40 bg-surface px-2 py-1.5 font-mono text-[11px] text-text-primary"
              >
                {watchedRepo?.repo_full_name === selectedRepo
                  ? `WATCHING: ${selectedRepo} • ${watchedRepo.webhook_active ? "WEBHOOK ARMED" : "WEBHOOK PENDING"}`
                  : `NOT WATCHED: ${selectedRepo}`}
              </span>
            ) : null}
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

        {/* --- JUDGE GUIDED DEMO JOURNEY BAR --- */}
        <div
          data-testid="judge-demo-bar"
          className="shrink-0 mt-3 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-laser-cyan/40 bg-surface-subtle p-3 shadow-sm transition-all"
        >
          <div className="flex flex-wrap items-center gap-2.5">
            <div className="flex items-center gap-2">
              <span className="flex h-2 w-2 rounded-full bg-laser-cyan animate-pulse" />
              <span className="font-mono text-xs font-semibold uppercase tracking-wider text-laser-cyan">
                Judge Demo Journey
              </span>
            </div>

            {/* Step 1: Verify GitHub Repo (0 PRs) */}
            <a
              href={`https://github.com/${selectedRepo || "sayedibrahimQ/aether-hardware"}/pulls`}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 font-mono text-[11px] text-text-secondary hover:text-text-primary transition-colors border border-border-subtle rounded px-2.5 py-1 bg-surface"
              title="Verify repo has 0 open PRs on GitHub"
            >
              <span>1. Check GitHub Repo (0 PRs)</span>
              <ExternalLink className="h-3 w-3" />
            </a>

            <button
              type="button"
              onClick={handleResetDemoSlate}
              disabled={demoBusy}
              className="font-mono text-[10px] text-text-muted hover:text-text-secondary underline"
              title="Close open PRs on GitHub to guarantee a clean slate"
            >
              {demoBusy ? "Resetting…" : "Reset Slate (0 PRs)"}
            </button>

            {demoMessage ? (
              <span className="font-mono text-[11px] text-laser-cyan/90 truncate max-w-md">
                {demoMessage}
              </span>
            ) : null}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {/* Step 2: Push Buggy Branch & Trigger Pipeline */}
            <button
              type="button"
              data-testid="push-buggy-branch-btn"
              onClick={handlePushBuggyBranch}
              disabled={demoBusy}
              className="inline-flex items-center gap-1.5 rounded-md bg-laser-cyan px-3.5 py-1.5 font-mono text-xs font-bold text-black transition-all hover:bg-laser-cyan/90 hover:shadow-[0_0_15px_rgba(0,229,255,0.4)] disabled:opacity-60"
            >
              {demoBusy ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Sparkles className="h-3.5 w-3.5" />
              )}
              <span>2. Push Buggy Branch &amp; Open PR</span>
            </button>

            {/* Step 4: When resolved, show prominent Inspect Healed PR button */}
            {scopedActiveRun?.status === "RESOLVED" && scopedActiveRun.pr_number ? (
              <a
                data-testid="inspect-healed-pr-btn"
                href={`https://github.com/${selectedRepo || "sayedibrahimQ/aether-hardware"}/pull/${scopedActiveRun.pr_number}`}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1.5 rounded-md border border-verified-emerald bg-verified-emerald/20 px-3.5 py-1.5 font-mono text-xs font-bold text-verified-emerald hover:bg-verified-emerald/30 transition-all shadow-[0_0_12px_rgba(0,245,155,0.3)] animate-pulse"
              >
                <CheckCircle2 className="h-3.5 w-3.5" />
                <span>✓ 4. Inspect Healed PR #{scopedActiveRun.pr_number} on GitHub</span>
                <ExternalLink className="h-3.5 w-3.5" />
              </a>
            ) : null}
          </div>
        </div>

        {watchedLoaded && !watchedRepo && !pickerDismissed ? (
          <div
            className="fixed inset-0 z-50 flex items-start justify-center bg-black/70 p-4 pt-[10vh]"
            data-testid="watched-repo-picker"
            role="dialog"
            aria-modal="true"
            aria-label="Choose the watched repository"
          >
            <div className="w-full max-w-md rounded-md border border-border-strong bg-elevated p-4 shadow-2xl">
              <h2 className="font-display text-base font-semibold text-text-primary">
                Choose the watched repository
              </h2>
              <p className="mt-1 text-xs text-text-secondary">
                VisorQA monitors exactly one repository. Webhooks for any
                other repository are ignored; the full 5-node pipeline runs
                autonomously for this one.
              </p>
              <div className="mt-3">
                <RepoSelector selectedRepo={selectedRepo} onSelect={selectRepo} />
              </div>
              {watchError ? (
                <p role="alert" className="mt-2 font-mono text-[11px] text-defect-crimson">
                  {watchError}
                </p>
              ) : null}
              <button
                type="button"
                data-testid="watched-picker-dismiss"
                onClick={() => setPickerDismissed(true)}
                className="mt-3 font-mono text-[11px] text-text-secondary hover:text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-border-focus"
              >
                Decide later
              </button>
            </div>
          </div>
        ) : null}

        {!selectedRepo ? (
          <p data-testid="repo-onboarding" className="shrink-0 mt-4 rounded-md border border-border-subtle bg-surface px-3 py-2.5 text-sm text-text-secondary">
            Select one of your GitHub repositories (top right) to scope pull
            requests, runs, telemetry, and actions to it.
          </p>
        ) : null}

        <div className="mt-5 grid min-w-0 flex-1 gap-4 md:grid-cols-[240px_minmax(0,1fr)] lg:grid-cols-[292px_minmax(0,1fr)] xl:grid-cols-[292px_minmax(0,1fr)_380px] md:grid-rows-[minmax(0,1fr)] md:min-h-0 md:h-full overflow-hidden">
          <div className="min-w-0 space-y-4 md:h-full md:min-h-0 flex flex-col overflow-hidden">
            {selectedRepo ? (
              <section
                aria-label="Repository pull requests"
                data-testid="repo-pulls"
                className="shrink-0 flex flex-col rounded-md border border-border-subtle bg-surface-subtle p-3 max-h-[300px] overflow-hidden"
              >
                <div className="shrink-0 flex items-baseline justify-between gap-2">
                  <h2 className="font-display text-sm font-semibold text-text-primary truncate">
                    {selectedRepo} Pull Requests
                  </h2>
                </div>
                {pullsError ? (
                  <p role="alert" className="mt-2 text-xs text-defect-crimson">{pullsError}</p>
                ) : pulls.length === 0 ? (
                  <p data-testid="repo-pulls-empty" className="mt-2 text-xs text-text-secondary">
                    No pull requests found for this repository yet. Scan a branch below to start a run.
                  </p>
                ) : (
                  <ul className="mt-2 space-y-2 flex-1 min-h-0 overflow-y-auto pr-1">
                    {pulls.map((pr) => {
                      const match = scopedRuns.find((r) => r.pr_number === pr.number);
                      const isSelected = match && effectiveActiveRunId === match.id;
                      return (
                        <li
                          key={pr.number}
                          data-testid={`pr-row-${pr.number}`}
                          onClick={() => {
                            if (match) selectRun(match.id);
                          }}
                          className={cn(
                            "rounded-md border border-border-subtle bg-surface px-2.5 py-2 transition-colors cursor-pointer hover:border-border-strong",
                            isSelected && "border-laser-cyan/60 bg-surface-elevated ring-1 ring-laser-cyan/30",
                          )}
                        >
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
                                onClick={(e) => {
                                  e.stopPropagation();
                                  selectRun(match.id);
                                }}
                                className="rounded-sm border border-neural-pulse/50 px-1.5 py-0.5 font-mono text-[10px] text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-border-focus"
                              >
                                Run: {match.status}
                              </button>
                            ) : null}
                            <button
                              type="button"
                              data-testid={`scan-pr-${pr.number}`}
                              onClick={(e) => {
                                e.stopPropagation();
                                void dispatchScan(pr.number, pr.head_ref, pr.head_sha);
                              }}
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
                  <div className="shrink-0 mt-2.5 flex items-center gap-1.5 border-t border-border-subtle/60 pt-2">
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
              activeRunId={effectiveActiveRunId}
              loading={loading}
              error={error}
              connectionStatus={status}
              onSelect={(id) => selectRun(id)}
              onClearRuns={handleClearRuns}
              clearing={clearingRuns}
              className="min-w-0 flex-1 min-h-0 flex flex-col overflow-hidden"
            />
          </div>

          <section aria-label="Active workspace" aria-live="polite" className="min-w-0 md:h-full md:min-h-0 md:overflow-y-auto md:pr-2">
            {scopedActiveRun ? (
              <div data-testid="active-run" data-run-id={scopedActiveRun.id} className="min-w-0">
                <div className="flex flex-wrap items-baseline justify-between gap-3">
                  <h2 className="min-w-0 truncate text-sm font-semibold text-text-secondary">
                    Active workspace — {scopedActiveRun.repo_name} PR #
                    {scopedActiveRun.pr_number}
                  </h2>
                  <ThreeStrikeLoop attempt={getAttemptState(scopedActiveRun)} />
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
                  {scopedActiveRun.status === "RESOLVED" && scopedActiveRun.pr_number ? (
                    <a
                      data-testid="action-inspect-healed-pr"
                      href={`https://github.com/${selectedRepo || "sayedibrahimQ/aether-hardware"}/pull/${scopedActiveRun.pr_number}`}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1.5 rounded-sm border border-verified-emerald/80 bg-verified-emerald/20 px-2.5 py-1 font-mono text-[11px] font-semibold text-verified-emerald hover:bg-verified-emerald/30 transition-all shadow-sm"
                    >
                      <CheckCircle2 className="h-3 w-3" />
                      <span>Inspect Healed PR #{scopedActiveRun.pr_number} on GitHub</span>
                      <ExternalLink className="h-3 w-3" />
                    </a>
                  ) : null}
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
                  <FSMOrchestratorBar run={scopedActiveRun} />
                </div>
                <div className="mt-4">
                  <DualViewportStage
                    runId={stage.runId}
                    runLabel={stage.runLabel}
                    loading={stageCapturing}
                    error={stageError}
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
                    currentStep={scopedActiveRun.current_step}
                    strikes={scopedActiveRun.strikes}
                  />
                </div>
                <dl className="mt-3 grid grid-cols-2 gap-2 font-mono text-xs text-text-secondary sm:grid-cols-3">
                  <div>
                    <dt>Branch</dt>
                    <dd className="truncate text-text-primary">{scopedActiveRun.branch}</dd>
                  </div>
                  <div>
                    <dt>Commit</dt>
                    <dd className="truncate text-text-primary">
                      {scopedActiveRun.commit_sha}
                    </dd>
                  </div>
                  <div>
                    <dt>Status</dt>
                    <dd className="text-text-primary">{scopedActiveRun.status}</dd>
                  </div>
                  <div>
                    <dt>Anomalies</dt>
                    <dd className="text-text-primary">
                      {scopedActiveRun.anomalies_count ?? 0}
                    </dd>
                  </div>
                  <div>
                    <dt>Attempt</dt>
                    <dd className="text-text-primary">
                      {scopedActiveRun.strikes}/3
                    </dd>
                  </div>
                  <div>
                    <dt>Updated</dt>
                    <dd className="truncate text-text-primary">
                      {scopedActiveRun.updated_at ?? "—"}
                    </dd>
                  </div>
                </dl>
              </div>
            ) : (
              <div className="min-w-0">
                <FSMOrchestratorBar run={null} />
                <div
                  data-testid="no-active-run"
                  className="mt-6 rounded-lg border border-border-subtle bg-surface-subtle p-8 text-center"
                >
                  <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full border border-border-subtle bg-surface text-laser-cyan mb-3">
                    <ScanEye className="h-6 w-6" aria-hidden="true" />
                  </div>
                  <h3 className="font-display text-base font-semibold text-text-primary">
                    No Active Inspection
                  </h3>
                  <p className="mt-1 text-xs text-text-secondary max-w-md mx-auto">
                    No Active Inspection — Select an open Pull Request or trigger an Optical QA Scan
                  </p>
                </div>
              </div>
            )}
          </section>

          <aside
            aria-label="Telemetry inspector drawer"
            data-testid="telemetry-drawer"
            data-width="380px"
            className="min-w-0 md:h-full md:min-h-0 md:overflow-y-auto md:pr-1"
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
              <ArchitectCoderInspector data={inspector} runId={effectiveActiveRunId} />
            </div>
          </aside>
        </div>
      </div>
    </main>
  );
}
