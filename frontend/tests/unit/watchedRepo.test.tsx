/**
 * Single watched repository binding (Task 1): boot hydration from
 * GET /api/settings/watched-repo, WATCHING pill, picker modal, persist
 * on select via POST. Mocked fetch/WebSocket only.
 * Run: cd frontend && npx vitest run tests/unit/watchedRepo.test.tsx
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import React from "react";

import { AuthProvider } from "@/context/AuthContext";
import MissionControlPage from "@/app/mission-control/page";
import { __resetMissionControlHubsForTests } from "@/hooks/useMissionControlStream";
import { MockWebSocket } from "./scrum28-helpers";

const USER = {
  login: "octocat", name: "Octo", avatar_url: "", html_url: "", auth_mode: "pat",
};
const REPOS = [
  { full_name: "octo/visor", name: "visor", owner: "octo", private: false, default_branch: "main", open_issues_count: 1, updated_at: "", html_url: "" },
  { full_name: "octo/other", name: "other", owner: "octo", private: false, default_branch: "main", open_issues_count: 0, updated_at: "", html_url: "" },
];
const WATCHED = {
  id: 1, repo_full_name: "octo/visor", default_branch: "main",
  installation_id: null, webhook_active: true, auto_heal_enabled: true,
  updated_at: "2026-06-01T00:00:00Z",
};

let watched: typeof WATCHED | null;
let requestedUrls: string[];
let postBodies: string[];

beforeEach(() => {
  MockWebSocket.instances = [];
  watched = null;
  requestedUrls = [];
  postBodies = [];
  vi.stubGlobal("WebSocket", MockWebSocket);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: { method?: string; body?: string }) => {
      requestedUrls.push(url);
      const reply = (body: unknown, ok = true) => ({ ok, status: ok ? 200 : 500, json: async () => body });
      if (url.includes("/api/auth/me")) return reply(USER);
      if (url.includes("/api/settings/watched-repo")) {
        if (init?.method === "POST") {
          postBodies.push(String(init.body ?? ""));
          watched = { ...WATCHED, repo_full_name: JSON.parse(String(init.body)).repo_full_name };
          return reply({ watched_repo: watched, webhook: { webhook_active: true } });
        }
        return reply(watched);
      }
      if (url.includes("/api/github/repos/")) return reply([]);
      if (url.includes("/api/github/repos")) return reply(REPOS);
      return reply([]);
    }),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  __resetMissionControlHubsForTests();
});

function renderPage() {
  return render(
    <AuthProvider>
      <MissionControlPage />
    </AuthProvider>,
  );
}

describe("watched repository binding", () => {
  it("hydrates the persisted watched repo and scopes pulls to it", async () => {
    watched = WATCHED;
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("watching-pill").textContent).toContain("WATCHING: octo/visor"));
    expect(screen.getByTestId("watching-pill").textContent).toContain("WEBHOOK ARMED");
    expect(screen.queryByTestId("watched-repo-picker")).toBeNull();
    await waitFor(() =>
      expect(
        requestedUrls.some((u) => u.includes("/api/github/repos/octo/visor/pulls")),
      ).toBe(true));
  });

  it("shows the picker when nothing is watched and persists the selection", async () => {
    renderPage();
    const picker = await screen.findByTestId("watched-repo-picker");
    fireEvent.click(within(picker).getByTestId("repo-selector-toggle"));
    await within(picker).findByTestId("repo-option-octo/other");
    fireEvent.click(within(picker).getByTestId("repo-option-octo/other"));
    await waitFor(() => expect(postBodies).toHaveLength(1));
    expect(JSON.parse(postBodies[0]).repo_full_name).toBe("octo/other");
    await waitFor(() =>
      expect(screen.getByTestId("watching-pill").textContent).toContain("WATCHING: octo/other"));
    expect(screen.queryByTestId("watched-repo-picker")).toBeNull();
  });
});
