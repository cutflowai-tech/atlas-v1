FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c

ARG ATLAS_UID=10001
ARG ATLAS_GID=10001

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/waset-atlas/src \
    ATLAS_DATA_DIR=/var/lib/waset-atlas

WORKDIR /opt/waset-atlas

COPY deploy/production/runtime-requirements.txt /tmp/runtime-requirements.txt
RUN python -m pip install --no-cache-dir --disable-pip-version-check -r /tmp/runtime-requirements.txt \
    && rm /tmp/runtime-requirements.txt \
    && groupadd --gid "${ATLAS_GID}" atlas \
    && useradd --uid "${ATLAS_UID}" --gid "${ATLAS_GID}" --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin atlas \
    && install -d -o "${ATLAS_UID}" -g "${ATLAS_GID}" -m 0755 /var/lib/waset-atlas

COPY src/ src/
COPY config/ config/
COPY contracts/ contracts/

RUN chown -R root:root /opt/waset-atlas \
    && chmod -R a-w /opt/waset-atlas \
    && find /opt/waset-atlas -type d -exec chmod 0555 {} + \
    && find /opt/waset-atlas -type f -exec chmod 0444 {} +

USER ${ATLAS_UID}:${ATLAS_GID}

VOLUME ["/var/lib/waset-atlas"]
ENTRYPOINT ["python", "-m", "atlas_sync"]
# Safe image startup: prints command help and performs no sync, publish, scheduling, or Monday request.
CMD ["--help"]
