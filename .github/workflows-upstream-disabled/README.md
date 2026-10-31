# Upstream automation (disabled in this fork)

The files in this folder came from the upstream repository
[HumanSignal/label-studio](https://github.com/HumanSignal/label-studio). They are
**disabled here on purpose**.

They were written for HumanSignal's repository, secrets and services, for example
`GIT_PAT`, Docker Hub, PyPI, Helm, Algolia, Zendesk, Slack, LaunchDarkly, and the
release and slash-command bots. In this fork they fail or do things we don't want.

GitHub only runs workflows in `.github/workflows/` and only reads Dependabot config
from `.github/dependabot.yml`. Keeping the files here stops them from running but
leaves them in the repo for reference.

The only active CI in this fork is `.github/workflows/docker-images.yml`. It builds
the app and nginx images and pushes them to GHCR.

## What's here

- Every upstream workflow from `.github/workflows/`, with the same file names.
- `dependabot.yml`, the upstream Dependabot config. It opened weekly
  GitHub Actions update PRs.

Some upstream config that only these workflows read was left where it was, because
the workflows refer to it by path:

- `.github/autolabeler.yml`
- `.github/pr-title-checker-config.json`
- `.github/codeql/`
- `.github/actions/`
- `.github/helpers/`

On its own, none of it does anything.

## Re-enabling one

1. Move it back with history:

   ```bash
   git mv .github/workflows-upstream-disabled/<name>.yml .github/workflows/<name>.yml
   ```

   For Dependabot, use `.github/dependabot.yml` as the destination.

2. Read the workflow before merging. Check:
   - **Secrets and variables:** `secrets.*` and `vars.*`, for example `GIT_PAT`,
     `DOCKERHUB_TOKEN`, `SLACK_*` and `LAUNCHDARKLY_*`. Add them in repo settings, or
     change the workflow to use `GITHUB_TOKEN` or our own values.
   - **Reusable workflows:** any `uses: ./.github/workflows/<other>.yml`. Each of those
     has to be moved back too.
   - **Upstream-only conditions:** for example `if: github.repository_owner == 'HumanSignal'`.
   - **External services:** anything that publishes to them, such as Docker Hub, PyPI,
     Helm repos or docs sites.
3. Open a PR and confirm the workflow passes in this fork.
