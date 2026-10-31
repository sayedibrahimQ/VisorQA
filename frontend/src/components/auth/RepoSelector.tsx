"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, ExternalLink, Loader2, Search } from "lucide-react";
import { resolveApiBase } from "@/hooks/useMissionControlStream";
import { cn } from "@/lib/utils";

export interface GitHubRepo {
  full_name: string;
  name: string;
  owner: string;
  private: boolean;
  default_branch: string;
  open_issues_count: number;
  updated_at: string;
  html_url: string;
}

interface RepoSelectorProps {
  selectedRepo: string | null;
  onSelect: (repoFullName: string) => void;
}

/** Persistent repository switcher backed by the live GitHub API. */
export function RepoSelector({ selectedRepo, onSelect }: RepoSelectorProps) {
  const apiBase = resolveApiBase();
  const [open, setOpen] = useState(false);
  const [repos, setRepos] = useState<GitHubRepo[] | null>(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open || repos !== null) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${apiBase}/api/github/repos`, { credentials: "include" });
        if (!res.ok) throw new Error(`Repository list failed (${res.status})`);
        const body: unknown = await res.json();
        if (!cancelled && Array.isArray(body)) setRepos(body as GitHubRepo[]);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Repository list failed");
          setRepos([]);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, repos, apiBase]);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const filtered = useMemo(() => {
    const all = repos ?? [];
    const q = query.trim().toLowerCase();
    return q ? all.filter((r) => r.full_name.toLowerCase().includes(q)) : all;
  }, [repos, query]);

  return (
    <div ref={rootRef} className="relative min-w-0" data-testid="repo-selector">
      <button
        type="button"
        data-testid="repo-selector-toggle"
        aria-expanded={open}
        aria-haspopup="listbox"
        onClick={() => setOpen((v) => !v)}
        className="flex max-w-full items-center gap-1.5 rounded-md border border-border-subtle bg-surface px-2.5 py-1.5 font-mono text-xs text-text-primary transition-colors hover:border-border-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-border-focus"
      >
        <span className="truncate">{selectedRepo ?? "Select repository"}</span>
        <ChevronDown className={cn("h-3.5 w-3.5 shrink-0 transition-transform", open && "rotate-180")} />
      </button>

      {open ? (
        <div className="absolute right-0 z-40 mt-2 w-80 max-w-[90vw] rounded-md border border-border-strong bg-elevated shadow-2xl">
          <div className="flex items-center gap-2 border-b border-border-subtle px-3 py-2">
            <Search className="h-3.5 w-3.5 text-text-muted" aria-hidden="true" />
            <input
              data-testid="repo-search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search repositories…"
              aria-label="Search repositories"
              className="w-full bg-transparent font-mono text-xs text-text-primary placeholder:text-text-muted focus:outline-none"
            />
          </div>
          {repos === null ? (
            <p className="flex items-center gap-2 px-3 py-4 text-xs text-text-secondary">
              <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" />
              Loading your repositories…
            </p>
          ) : error ? (
            <p data-testid="repo-error" role="alert" className="px-3 py-4 text-xs text-defect-crimson">
              {error}
            </p>
          ) : filtered.length === 0 ? (
            <p className="px-3 py-4 text-xs text-text-secondary">No repositories match.</p>
          ) : (
            <ul role="listbox" aria-label="Your GitHub repositories" className="max-h-72 overflow-y-auto py-1">
              {filtered.map((repo) => (
                <li key={repo.full_name}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={repo.full_name === selectedRepo}
                    data-testid={`repo-option-${repo.full_name}`}
                    onClick={() => {
                      onSelect(repo.full_name);
                      setOpen(false);
                    }}
                    className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left transition-colors hover:bg-surface focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-border-focus"
                  >
                    <span className="min-w-0">
                      <span className="block truncate font-mono text-xs text-text-primary">
                        {repo.full_name}
                      </span>
                      <span className="block font-mono text-[10px] text-text-muted">
                        {repo.private ? "private" : "public"} · {repo.default_branch} ·{" "}
                        {repo.open_issues_count} open issues
                      </span>
                    </span>
                    {repo.full_name === selectedRepo ? (
                      <Check className="h-3.5 w-3.5 shrink-0 text-verified-emerald" aria-hidden="true" />
                    ) : null}
                  </button>
                </li>
              ))}
            </ul>
          )}
          {selectedRepo ? (
            <div className="border-t border-border-subtle px-3 py-2">
              <a
                data-testid="repo-github-link"
                href={`https://github.com/${selectedRepo}`}
                target="_blank"
                rel="noreferrer"
                className="flex items-center gap-1 font-mono text-[11px] text-neural-pulse hover:text-text-primary"
              >
                Open {selectedRepo} on GitHub
                <ExternalLink className="h-3 w-3" aria-hidden="true" />
              </a>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
