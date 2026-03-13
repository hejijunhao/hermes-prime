"""Tests for hunter.backends.fly_config — Fly.io configuration."""

import os
import pytest
from unittest.mock import patch

from hunter.backends.fly_config import FlyConfig


# All required env vars for a valid config
_FULL_ENV = {
    "FLY_API_TOKEN": "fly-tok-123",
    "HUNTER_FLY_APP": "hermes-prime-hunter",
    "GITHUB_PAT": "ghp_abc123",
    "HUNTER_REPO": "user/hermes-prime-hunter",
    "HUNTER_FLY_IMAGE": "registry.fly.io/hermes-hunter:latest",
    "ELEPHANTASM_API_KEY": "elk-key-456",
    "OPENROUTER_API_KEY": "or-key-789",
}


class TestFromEnv:

    def test_loads_all_required_vars(self):
        with patch.dict(os.environ, _FULL_ENV, clear=False):
            config = FlyConfig.from_env()
            assert config.fly_api_token == "fly-tok-123"
            assert config.hunter_app_name == "hermes-prime-hunter"
            assert config.github_pat == "ghp_abc123"
            assert config.hunter_repo == "user/hermes-prime-hunter"
            assert config.machine_image == "registry.fly.io/hermes-hunter:latest"
            assert config.elephantasm_api_key == "elk-key-456"
            assert config.openrouter_api_key == "or-key-789"

    def test_raises_on_missing_required_var(self):
        # Missing FLY_API_TOKEN and HUNTER_FLY_APP
        partial_env = {k: v for k, v in _FULL_ENV.items() if k not in ("FLY_API_TOKEN", "HUNTER_FLY_APP")}
        with patch.dict(os.environ, partial_env, clear=True):
            with pytest.raises(ValueError, match="FLY_API_TOKEN"):
                FlyConfig.from_env()

    def test_uses_defaults_for_optional_vars(self):
        with patch.dict(os.environ, _FULL_ENV, clear=False):
            config = FlyConfig.from_env()
            assert config.machine_cpu_kind == "shared"
            assert config.machine_cpus == 2
            assert config.machine_memory_mb == 2048
            assert config.machine_region == ""

    def test_overrides_optional_vars(self):
        env = {
            **_FULL_ENV,
            "HUNTER_FLY_CPU_KIND": "performance",
            "HUNTER_FLY_CPUS": "4",
            "HUNTER_FLY_MEMORY_MB": "4096",
            "HUNTER_FLY_REGION": "lax",
        }
        with patch.dict(os.environ, env, clear=False):
            config = FlyConfig.from_env()
            assert config.machine_cpu_kind == "performance"
            assert config.machine_cpus == 4
            assert config.machine_memory_mb == 4096
            assert config.machine_region == "lax"


class TestToMachineConfig:

    @pytest.fixture
    def config(self):
        return FlyConfig(
            fly_api_token="tok",
            hunter_app_name="app",
            github_pat="pat",
            hunter_repo="user/repo",
            machine_image="img:latest",
            elephantasm_api_key="elk",
            openrouter_api_key="or",
        )

    def test_basic_config_structure(self, config):
        result = config.to_machine_config(model="qwen/qwen3.5-72b", session_id="s-001")
        assert "config" in result
        c = result["config"]
        assert c["image"] == "img:latest"
        assert c["auto_destroy"] is True
        assert c["restart"] == {"policy": "no"}
        assert c["guest"]["cpu_kind"] == "shared"
        assert c["guest"]["cpus"] == 2
        assert c["guest"]["memory_mb"] == 2048

    def test_env_vars_set(self, config):
        result = config.to_machine_config(model="qwen/qwen3.5-72b", session_id="s-001")
        env = result["config"]["env"]
        assert env["HUNTER_MODEL"] == "qwen/qwen3.5-72b"
        assert env["SESSION_ID"] == "s-001"
        assert env["ELEPHANTASM_API_KEY"] == "elk"
        assert env["OPENROUTER_API_KEY"] == "or"
        assert env["GITHUB_PAT"] == "pat"
        assert env["HUNTER_REPO"] == "user/repo"

    def test_instruction_included_when_provided(self, config):
        result = config.to_machine_config(
            model="m", session_id="s", instruction="Hunt IDOR bugs",
        )
        assert result["config"]["env"]["HUNTER_INSTRUCTION"] == "Hunt IDOR bugs"

    def test_resume_flag(self, config):
        result = config.to_machine_config(model="m", session_id="s", resume=True)
        assert result["config"]["env"]["HUNTER_RESUME"] == "1"

    def test_no_resume_by_default(self, config):
        result = config.to_machine_config(model="m", session_id="s")
        assert "HUNTER_RESUME" not in result["config"]["env"]

    def test_region_included_when_set(self):
        config = FlyConfig(
            fly_api_token="tok", hunter_app_name="app",
            github_pat="pat", hunter_repo="r", machine_image="img",
            machine_region="lax",
        )
        result = config.to_machine_config(model="m", session_id="s")
        assert result["region"] == "lax"

    def test_no_region_when_empty(self, config):
        result = config.to_machine_config(model="m", session_id="s")
        assert "region" not in result
