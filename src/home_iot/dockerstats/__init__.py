"""Per-container resource exporter via the Docker API (socket).

cAdvisor cannot read the overlay2 layer DB on Docker Desktop / macOS and drops
every per-container series. The Docker Engine API over ``/var/run/docker.sock``
works fine there, so this small exporter uses it directly — no third-party
image, no SDK dependency.
"""
