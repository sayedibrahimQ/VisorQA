import { describe, expect, it } from "vitest";
import { NextRequest } from "next/server";
import { GET } from "@/app/github/callback/route";

describe("OAuth Callback Route Handler", () => {
  it("redirects with code and state to backend callback endpoint", async () => {
    const req = new NextRequest("http://localhost:3000/github/callback?code=mock_code&state=mock_state");
    const res = await GET(req);

    expect(res.status).toBe(307);
    const location = res.headers.get("location");
    expect(location).toContain("/api/auth/github/callback");
    expect(location).toContain("code=mock_code");
    expect(location).toContain("state=mock_state");
  });

  it("redirects to mission-control with auth_error when error is provided", async () => {
    const req = new NextRequest("http://localhost:3000/github/callback?error=access_denied&error_description=User%20denied");
    const res = await GET(req);

    expect(res.status).toBe(307);
    const location = res.headers.get("location");
    expect(location).toContain("/mission-control?auth_error=User%20denied");
  });

  it("redirects to mission-control with missing_code when code is absent", async () => {
    const req = new NextRequest("http://localhost:3000/github/callback");
    const res = await GET(req);

    expect(res.status).toBe(307);
    const location = res.headers.get("location");
    expect(location).toContain("/mission-control?auth_error=missing_code");
  });
});
