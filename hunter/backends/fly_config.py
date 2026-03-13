"""Fly.io backend configuration.

All values come from environment variables (set as Fly secrets in production).
This module keeps environment-reading logic out of the API client and controller.
"""

import os
from dataclasses import dataclass, field


_REQUIRED_VARS = {
    "FLY_API_TOKEN": "Fly Machines API authentication token",
    "HUNTER_FLY_APP": "Fly app name for the Hunter machine (e.g. 'hermes-prime-hunter')",
    "GITHUB_PAT": "GitHub personal access token with repo scope",
    "HUNTER_REPO": "GitHub repo for the Hunter (e.g. 'user/hermes-prime-hunter')",
    "HUNTER_FLY_IMAGE": "Docker image reference for the Hunter machine",
    "ELEPHANTASM_API_KEY": "Elephantasm API key for cross-machine memory",
    "OPENROUTER_API_KEY": "OpenRouter API key for the Hunter's LLM calls",
}


@dataclass
class FlyConfig:
    """Configuration for the Fly.io remote backend.

    All values come from environment variables (set as Fly secrets).
    """

    # Fly API
    fly_api_token: str
    hunter_app_name: str

    # GitHub
    github_pat: str
    hunter_repo: str

    # Hunter machine spec
    machine_image: str
    machine_cpu_kind: str = "shared"
    machine_cpus: int = 2
    machine_memory_mb: int = 2048
    machine_region: str = ""

    # Hunter environment (passed to the Hunter machine as env vars)
    elephantasm_api_key: str = ""
    openrouter_api_key: str = ""

    @classmethod
    def from_env(cls) -> "FlyConfig":
        """Load configuration from environment variables.

        Raises:
            ValueError: If any required environment variables are missing.
        """
        missing = [
            f"  {var} — {desc}"
            for var, desc in _REQUIRED_VARS.items()
            if not os.environ.get(var)
        ]
        if missing:
            raise ValueError(
                "Missing required environment variables for Fly.io backend:\n"
                + "\n".join(missing)
            )

        return cls(
            fly_api_token=os.environ["FLY_API_TOKEN"],
            hunter_app_name=os.environ["HUNTER_FLY_APP"],
            github_pat=os.environ["GITHUB_PAT"],
            hunter_repo=os.environ["HUNTER_REPO"],
            machine_image=os.environ["HUNTER_FLY_IMAGE"],
            machine_cpu_kind=os.environ.get("HUNTER_FLY_CPU_KIND", "shared"),
            machine_cpus=int(os.environ.get("HUNTER_FLY_CPUS", "2")),
            machine_memory_mb=int(os.environ.get("HUNTER_FLY_MEMORY_MB", "2048")),
            machine_region=os.environ.get("HUNTER_FLY_REGION", ""),
            elephantasm_api_key=os.environ["ELEPHANTASM_API_KEY"],
            openrouter_api_key=os.environ["OPENROUTER_API_KEY"],
        )

    def to_machine_config(
        self,
        model: str,
        session_id: str,
        instruction: str = None,
        resume: bool = False,
    ) -> dict:
        """Build the Fly Machines API config dict for creating a Hunter machine.

        Args:
            model: LLM model for the Hunter.
            session_id: Unique session identifier.
            instruction: Optional initial instruction for the Hunter.
            resume: If True, the Hunter resumes a previous session.

        Returns:
            Config dict suitable for ``FlyMachinesClient.create_machine()``.
        """
        env = {
            "HUNTER_MODEL": model,
            "SESSION_ID": session_id,
            "ELEPHANTASM_API_KEY": self.elephantasm_api_key,
            "OPENROUTER_API_KEY": self.openrouter_api_key,
            "HUNTER_REPO": self.hunter_repo,
            "GITHUB_PAT": self.github_pat,
        }
        if instruction:
            env["HUNTER_INSTRUCTION"] = instruction
        if resume:
            env["HUNTER_RESUME"] = "1"

        config: dict = {
            "config": {
                "image": self.machine_image,
                "env": env,
                "guest": {
                    "cpu_kind": self.machine_cpu_kind,
                    "cpus": self.machine_cpus,
                    "memory_mb": self.machine_memory_mb,
                },
                "auto_destroy": True,
                "restart": {"policy": "no"},
            },
        }

        if self.machine_region:
            config["region"] = self.machine_region

        return config
