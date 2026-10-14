# Build only in a trusted provisioning environment. Pass a digest-pinned Python base.
ARG PYTHON_BASE
FROM ${PYTHON_BASE}
COPY wheels /tmp/wheels
RUN python -m pip install --no-cache-dir --no-index --find-links=/tmp/wheels pytest==9.1.1
USER 65534:65534
WORKDIR /tmp
