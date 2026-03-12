"""Tests for Overseer system prompt loading (Task 11).

Verifies that the prompt files exist, load correctly, contain the expected
sections, and handle edge cases (missing references dir, missing main file).
"""

import shutil
from pathlib import Path

import pytest


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def prompts_dir():
    """Path to the real prompts directory in the hunter package."""
    return Path(__file__).resolve().parent.parent / "hunter" / "prompts"


@pytest.fixture
def temp_prompts(tmp_path):
    """Temporary prompts directory for isolation tests."""
    d = tmp_path / "prompts"
    d.mkdir()
    refs = d / "references"
    refs.mkdir()

    (d / "overseer_system.md").write_text(
        "You are the Overseer, a meta-agent.\n\nSOFT HARD MODEL\n\n"
        "NEVER modify your own code\n\nDecision Framework\n",
        encoding="utf-8",
    )
    (refs / "budget-management.md").write_text(
        "# Budget Management\nModel tier selection.\n",
        encoding="utf-8",
    )
    (refs / "intervention-strategy.md").write_text(
        "# Intervention Strategy\nWhen to intervene.\n",
        encoding="utf-8",
    )
    return d


# =============================================================================
# Helpers
# =============================================================================

def _load_from(prompts_dir: Path) -> str:
    """Load overseer prompt from a specific directory (for testing)."""
    main_path = prompts_dir / "overseer_system.md"
    main = main_path.read_text(encoding="utf-8")
    refs_dir = prompts_dir / "references"
    if refs_dir.exists():
        for ref_path in sorted(refs_dir.glob("*.md")):
            ref_content = ref_path.read_text(encoding="utf-8")
            main += f"\n\n---\n\n{ref_content}"
    return main


# =============================================================================
# Tests — Real prompt files
# =============================================================================

class TestRealPromptFiles:
    """Test against the actual prompt files shipped in hunter/prompts/."""

    def test_main_prompt_file_exists(self, prompts_dir):
        assert (prompts_dir / "overseer_system.md").exists()

    def test_references_dir_exists(self, prompts_dir):
        assert (prompts_dir / "references").is_dir()

    def test_budget_reference_exists(self, prompts_dir):
        assert (prompts_dir / "references" / "budget-management.md").exists()

    def test_intervention_reference_exists(self, prompts_dir):
        assert (prompts_dir / "references" / "intervention-strategy.md").exists()


class TestPromptContent:
    """Test that the real prompts contain expected sections."""

    def test_prompt_loads(self, prompts_dir):
        result = _load_from(prompts_dir)
        assert len(result) > 500

    def test_prompt_contains_role(self, prompts_dir):
        result = _load_from(prompts_dir)
        assert "Overseer" in result
        assert "meta-agent" in result

    def test_prompt_contains_intervention_modes(self, prompts_dir):
        result = _load_from(prompts_dir)
        assert "SOFT" in result
        assert "HARD" in result
        assert "MODEL" in result

    def test_prompt_contains_rules(self, prompts_dir):
        result = _load_from(prompts_dir)
        assert "NEVER modify your own code" in result

    def test_prompt_contains_decision_framework(self, prompts_dir):
        result = _load_from(prompts_dir)
        assert "Decision Framework" in result

    def test_prompt_contains_tool_reference(self, prompts_dir):
        result = _load_from(prompts_dir)
        assert "hunter_spawn" in result
        assert "hunter_inject" in result
        assert "hunter_code_edit" in result
        assert "budget_status" in result

    def test_references_appended(self, prompts_dir):
        result = _load_from(prompts_dir)
        assert "Budget Management" in result
        assert "Intervention Strategy" in result

    def test_references_separated_by_dividers(self, prompts_dir):
        result = _load_from(prompts_dir)
        # References are separated from main prompt by ---
        assert "\n\n---\n\n" in result


# =============================================================================
# Tests — _load_overseer_system_prompt() function
# =============================================================================

class TestLoadFunction:
    """Test the actual _load_overseer_system_prompt() function."""

    def test_load_returns_nonempty_string(self):
        from hunter.overseer import _load_overseer_system_prompt
        result = _load_overseer_system_prompt()
        assert isinstance(result, str)
        assert len(result) > 500

    def test_load_includes_references(self):
        from hunter.overseer import _load_overseer_system_prompt
        result = _load_overseer_system_prompt()
        assert "Budget Management" in result
        assert "Intervention Strategy" in result


# =============================================================================
# Tests — Edge cases
# =============================================================================

class TestEdgeCases:
    """Test edge cases in prompt loading logic."""

    def test_missing_references_dir_ok(self, tmp_path):
        """If references/ doesn't exist, still returns main prompt."""
        d = tmp_path / "prompts"
        d.mkdir()
        (d / "overseer_system.md").write_text("Main prompt content.", encoding="utf-8")
        result = _load_from(d)
        assert result == "Main prompt content."

    def test_main_prompt_missing_raises(self, tmp_path):
        """FileNotFoundError if overseer_system.md is missing."""
        d = tmp_path / "prompts"
        d.mkdir()
        with pytest.raises(FileNotFoundError):
            _load_from(d)

    def test_references_sorted_deterministically(self, temp_prompts):
        """References are appended in alphabetical order by filename."""
        result = _load_from(temp_prompts)
        budget_pos = result.index("Budget Management")
        intervention_pos = result.index("Intervention Strategy")
        assert budget_pos < intervention_pos

    def test_empty_references_dir(self, tmp_path):
        """Empty references/ dir is handled gracefully."""
        d = tmp_path / "prompts"
        d.mkdir()
        (d / "references").mkdir()
        (d / "overseer_system.md").write_text("Main only.", encoding="utf-8")
        result = _load_from(d)
        assert result == "Main only."
