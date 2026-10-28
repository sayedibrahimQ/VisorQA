"""Deterministic Unit Tests: SRS Constraints & Security Guardrails

TC-1: Zero-framework architecture constraint (No LangChain, CrewAI, AutoGen).
BR-4: Anti-Hack CSS Policy (Rejecting !important, z-index: 9999, etc.).
"""
import ast
import os
import pathlib

from backend.core.orchestrator import BANNED_PATCH_PATTERNS


def test_tc1_zero_agent_framework_imports():
    """SRS Constraint TC-1: VisorQA must NOT use third-party agent frameworks.
    Assert zero imports of langchain, crewai, or autogen across all backend code.
    """
    backend_dir = pathlib.Path(__file__).resolve().parents[1]
    banned_modules = {"langchain", "crewai", "autogen"}

    found_violations = []

    for root, _, files in os.walk(backend_dir):
        # Ignore tests directory itself
        if "tests" in root or "__pycache__" in root:
            continue
        for file in files:
            if not file.endswith(".py"):
                continue
            path = pathlib.Path(root) / file
            source = path.read_text(encoding="utf-8")

            # 1. AST check for imports
            try:
                tree = ast.parse(source, filename=str(path))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for name in node.names:
                            root_pkg = name.name.split(".")[0].lower()
                            if root_pkg in banned_modules:
                                found_violations.append((str(path), node.lineno, root_pkg))
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            root_pkg = node.module.split(".")[0].lower()
                            if root_pkg in banned_modules:
                                found_violations.append((str(path), node.lineno, root_pkg))
            except SyntaxError:
                pass

            # 2. String check for references
            lower_source = source.lower()
            for banned in banned_modules:
                if f"import {banned}" in lower_source or f"from {banned}" in lower_source:
                    found_violations.append((str(path), "raw", banned))

    assert not found_violations, f"Found unauthorized agent framework imports: {found_violations}"


def test_br4_anti_hack_css_policy():
    """Business Rule BR-4: Anti-Hack CSS policy.
    Diff patches containing !important or abusive z-index values must be rejected.
    """
    # 1. Verify banned patterns list includes all malicious hacks
    assert "!important" in BANNED_PATCH_PATTERNS
    assert any("9999" in p for p in BANNED_PATCH_PATTERNS)

    def is_anti_hack_valid(patch_diff: str) -> bool:
        """Mirroring orchestrator validation logic."""
        return not any(pat.lower() in patch_diff.lower() for pat in BANNED_PATCH_PATTERNS)

    # Valid CSS patches
    valid_patch_1 = """
    --- a/styles.css
    +++ b/styles.css
    @@ -10,3 +10,3 @@
    -  position: absolute;
    +  position: sticky;
    +  top: 0;
    """
    assert is_anti_hack_valid(valid_patch_1) is True

    valid_patch_2 = """
    --- a/Navbar.tsx
    +++ b/Navbar.tsx
    @@ -5,2 +5,2 @@
    -  <div className="z-10">
    +  <div className="z-50 relative">
    """
    assert is_anti_hack_valid(valid_patch_2) is True

    # Malicious hack patches (!important)
    hack_patch_important = """
    --- a/styles.css
    +++ b/styles.css
    @@ -10,2 +10,2 @@
    -  display: block;
    +  display: block !important;
    """
    assert is_anti_hack_valid(hack_patch_important) is False

    # Malicious hack patches (z-index: 9999)
    hack_patch_zindex_space = """
    --- a/styles.css
    +++ b/styles.css
    @@ -10,2 +10,2 @@
    -  z-index: 1;
    +  z-index: 9999;
    """
    assert is_anti_hack_valid(hack_patch_zindex_space) is False

    # Malicious hack patches (z-index:9999 no space)
    hack_patch_zindex_nospace = """
    --- a/styles.css
    +++ b/styles.css
    @@ -10,2 +10,2 @@
    +  z-index:9999;
    """
    assert is_anti_hack_valid(hack_patch_zindex_nospace) is False

    # Malicious Tailwind arbitrary z-index (z-[9999])
    hack_patch_tailwind = """
    --- a/Banner.tsx
    +++ b/Banner.tsx
    @@ -3,2 +3,2 @@
    -  <div className="z-10">
    +  <div className="z-[9999]">
    """
    assert is_anti_hack_valid(hack_patch_tailwind) is False
