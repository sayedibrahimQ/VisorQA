import pytest
import numpy as np
from backend.adapters.github_client import GitHubClient
from backend.adapters.muse_clients import SAM31Client, MuseSparkClient, MuseWonderClient, MuseCodeClient
from backend.adapters.sandbox_runner import ModalSandboxRunner

@pytest.mark.asyncio
async def test_sam31_client():
    client = SAM31Client(api_key="mock_key")
    boxes = [{"x": 0, "y": 0, "width": 100, "height": 100}]
    masks = await client.generate_component_masks(b"fake_image", boxes)
    assert len(masks) == 1
    assert isinstance(masks[0], np.ndarray)

@pytest.mark.asyncio
async def test_muse_spark_client():
    client = MuseSparkClient(api_key="mock_key")
    res = await client.triage_anomalies([], {})
    assert "lca_element_id" in res
    assert "candidate_source_file" in res

@pytest.mark.asyncio
async def test_muse_wonder_client():
    client = MuseWonderClient(api_key="mock_key")
    res = await client.diagnose_defect(b"crop", {"z-index": "50"}, {"lca": "banner"})
    assert "diagnosis" in res
    assert "recommended_fix" in res

@pytest.mark.asyncio
async def test_muse_code_client():
    client = MuseCodeClient(api_key="mock_key")
    diff = await client.generate_patch("<div className='fixed z-50'>", {}, "src/components/PromoBanner.tsx")
    assert isinstance(diff, str)
    assert "---" in diff

@pytest.mark.asyncio
async def test_modal_sandbox_runner():
    runner = ModalSandboxRunner(token="mock_token")
    url = await runner.boot_branch("VisorQA", "fix/test")
    assert "modal-sandbox-fix/test" in url
    assert await runner.apply_hmr_patch("test.tsx", "code") is True
