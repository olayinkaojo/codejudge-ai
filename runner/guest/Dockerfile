# Pin the resulting image ID in RUNNER_IMAGE after building and auditing this image.
FROM python:3.12-slim
COPY --chmod=0444 bootstrap.py /opt/bootstrap.py
USER 65532:65532
WORKDIR /tmp
LABEL org.codejudge.sandbox="python-stdio-v1"
ENTRYPOINT ["/usr/local/bin/python", "-I", "-S", "-B", "/opt/bootstrap.py"]
