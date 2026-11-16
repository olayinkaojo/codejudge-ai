def docker_client(settings):
    import docker

    # Unix socket only. Requests never use ambient proxies; container creation separately
    # disables Docker CLI proxy injection. No registry pull/auth operation is performed.
    client = docker.DockerClient(base_url=settings.docker_socket, timeout=3)
    client.api.trust_env = False
    return client
