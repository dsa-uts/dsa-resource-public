FROM debian:trixie-slim@sha256:d7e12182ce18b85b93007c1dedf31f2d29e01ccf3182cc4017c709b6259bc132
LABEL org.opencontainers.image.source="https://github.com/dsa-uts/dsa-resource-public"
RUN groupadd --gid 10001 sandbox \
    && useradd --uid 10001 --gid 10001 --no-create-home sandbox \
    && mkdir /workspace && chown 10001:10001 /workspace
USER 10001:10001
WORKDIR /workspace
ENV LC_ALL=C
