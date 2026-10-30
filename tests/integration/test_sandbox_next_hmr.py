"""Real local Next.js HMR: patch a running `next dev` without restart.

Marked slow; uses the frontend's installed node_modules. If Next.js is
unavailable the test skips rather than fabricating a result.
"""
import http.client
import json
import time
from pathlib import Path

import pytest

from backend.sandbox import HMRStatus, LocalSandboxRunner

ROOT = Path(__file__).parents[2]
NEXT_MODULES = ROOT / "frontend" / "node_modules"


def _fetch(url):
    from urllib.parse import urlparse
    u = urlparse(url)
    conn = http.client.HTTPConnection(u.hostname, u.port, timeout=5)
    conn.request("GET", u.path or "/")
    resp = conn.getresponse()
    body = resp.read().decode(errors="replace")
    conn.close()
    return body


@pytest.mark.asyncio
@pytest.mark.skipif(not (NEXT_MODULES / "next").exists(), reason="Next.js not installed")
async def test_real_next_dev_hmr_multiple_patches(tmp_path):
    src = tmp_path / "next-app"
    (src / "app").mkdir(parents=True)
    (src / "node_modules").symlink_to(NEXT_MODULES, target_is_directory=True)
    (src / "package.json").write_text(json.dumps(
        {"name": "fixture", "private": True, "scripts": {"dev": "next dev"}}))
    page = src / "app" / "page.tsx"
    page.write_text("export default function Page() { return <main>version-one</main>; }\n")
    (src / "app" / "layout.tsx").write_text(
        "export default function Layout({children}) { return <html><body>{children}</body></html>; }\n")

    runner = LocalSandboxRunner(base_dir=str(tmp_path / "sandboxes"),
                                hmr_timeout=30, startup_timeout=120)
    await runner.create_or_attach("next-pr", source_dir=str(src),
                                  authorized_files=["app/page.tsx"])
    try:
        status = await runner.start_dev_server()
        assert status.server_state.value == "running", status.last_error
        pid = status.server_pid
        body = ""
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and "version-one" not in body:
            try:
                body = _fetch(status.preview_url)
            except OSError:
                body = ""
            if "version-one" not in body:
                time.sleep(0.25)
        assert "version-one" in body

        for old, new in (("version-one", "version-two"), ("version-two", "version-three")):
            diff = ("--- a/app/page.tsx\n+++ b/app/page.tsx\n@@ -1,1 +1,1 @@\n"
                    f"-export default function Page() {{ return <main>{old}</main>; }}\n"
                    f"+export default function Page() {{ return <main>{new}</main>; }}\n")
            result = await runner.apply_patch(diff)
            assert result.success, result.error
            hmr = await runner.wait_for_hmr(result.patch_id, timeout=30)
            assert hmr.status in (HMRStatus.OBSERVED, HMRStatus.TIMEOUT), hmr
            assert (await runner.get_status()).server_pid == pid  # never restarted
            # Content-level confirmation is the ground truth for HMR.
            body, deadline = "", time.monotonic() + 30
            while time.monotonic() < deadline and new not in body:
                try:
                    body = _fetch(status.preview_url)
                except OSError:
                    body = ""
                if new not in body:
                    time.sleep(0.25)
            assert new in body, f"HMR content not served for {new}"
    finally:
        await runner.terminate()
