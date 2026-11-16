"""Deployment-only tests. No untrusted execution unless every gVisor prerequisite passes."""

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUNNER_LIVE_TESTS") != "1", reason="requires dedicated validated gVisor host"
)


def test_real_gvisor_deployment_security_probes():
    import docker

    from runner.config import RunnerSettings
    from runner.isolation import GVisor
    from runner.validate import validate

    settings = RunnerSettings()
    settings.validate_secrets()
    engine = GVisor(
        docker.DockerClient(base_url=settings.docker_socket, timeout=3), settings, admission_required=False
    )
    engine.verify()  # Fails before any probe source is sent on unsuitable hosts.
    validate(settings, engine)
    GVisor(engine.client, settings).verify()  # Signed evidence must now admit this exact deployment.
