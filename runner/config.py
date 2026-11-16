from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class RunnerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RUNNER_", extra="ignore")
    token: SecretStr
    image: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    state_dir: Path = Path("/var/lib/codejudge-runner")
    docker_socket: str = "unix:///var/run/docker.sock"

    def validate_secrets(self):
        if len(self.token.get_secret_value()) < 32:
            raise ValueError("runner token must have at least 32 characters")
        if not self.docker_socket.startswith("unix:///"):
            raise ValueError("runner requires a local dedicated Docker daemon")
