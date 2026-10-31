import { NextRequest, NextResponse } from "next/server";

export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams;
  const code = searchParams.get("code") || "";
  const state = searchParams.get("state") || "";
  const error = searchParams.get("error");
  const errorDescription = searchParams.get("error_description");

  const frontendOrigin = request.nextUrl.origin;

  if (error) {
    const detail = encodeURIComponent(errorDescription || error);
    return NextResponse.redirect(`${frontendOrigin}/mission-control?auth_error=${detail}`);
  }

  if (!code) {
    return NextResponse.redirect(`${frontendOrigin}/mission-control?auth_error=missing_code`);
  }

  const backendUrl = (
    process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
  ).replace(/\/$/, "");

  const callbackUrl = new URL(`${backendUrl}/api/auth/github/callback`);
  callbackUrl.searchParams.set("code", code);
  if (state) {
    callbackUrl.searchParams.set("state", state);
  }

  return NextResponse.redirect(callbackUrl.toString());
}

