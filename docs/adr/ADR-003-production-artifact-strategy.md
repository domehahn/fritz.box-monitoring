# ADR-003: Immutable Production Artifact Strategy

## Status

Accepted

## Context

Development compose files frequently rely on local source bind mounts, `:latest` image tags, and local compilation, introducing environmental non-reproducibility in production deployments.

## Decision

Production deployments (`compose.prod.yml`) must consume strictly versioned, immutable container images published to Container Registries (GHCR). `compose.prod.yml` must contain zero `build:` directives and zero source code bind mounts.

## Consequences

- Completely reproducible production deployments.
- Clean separation of CI build pipelines and CD deployment orchestration.
- Image integrity verified via digest references and SBOM attestations.
