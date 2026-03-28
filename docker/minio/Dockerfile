# Custom MinIO image with mc CLI included for auto bucket creation.
# Eliminates the need for a separate minio-init container.

FROM minio/minio:RELEASE.2025-09-07T16-13-09Z

# Install mc CLI from official release (must be compatible with server version)
ADD --chmod=755 \
    https://dl.min.io/client/mc/release/linux-amd64/archive/mc.RELEASE.2025-08-13T08-35-41Z \
    /usr/local/bin/mc

COPY docker/minio/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
