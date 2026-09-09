# System Deployment

This is the assembly layer, not a component implementation. There are no images,
Compose files, configuration examples, or deployment commands yet.

When services are implemented, add a production `compose.yaml` using pinned
release artifacts and a `compose.dev.yaml` override for local development builds.
Development build contexts may reference sibling component roots; Dockerfiles
and actual build logic must stay inside their owning components.

Keep archive storage, database volumes, models, backups, and local configuration
outside the checkout. Document required paths, permissions, resource limits,
pairing, recovery, and upgrade/migration steps. Commit only sanitized
`.env.example` templates, never generated credentials or actual `.env` files.

Local-only installation must not require publicly exposed API/ADB ports or cloud
credentials. Ordinary users should install APKs and server images, not configure
Git submodules. The same assembly paths should continue working if component
directories later become commit-pinned submodules.
