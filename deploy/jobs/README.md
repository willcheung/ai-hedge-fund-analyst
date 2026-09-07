# Synthetic job examples — nonexecuting tools

`definitions.json` contains one deliberately synthetic paused weekly example. Its ID, schedule, prompt, lifecycle and hashes were created for public schema demonstration. It is not a live-job backup, restoration manifest, source inventory or evidence of deployment coverage.

The stdlib exporter, validator, private reconstruction checker and scratch importer remain available. They never start a scheduler or resolve executable settings. A scratch import clears execution hooks and delivery, disables all jobs, preserves completed state and writes a DO_NOT_START_SCHEDULER marker. Destination must be a new `/tmp/analyst-job-scratch-<unique>` directory. Tests exercise synthetic scheduled, paused and completed lifecycles, tampering and refusal behavior.

From the repository root, use the shared isolation wrapper:

```sh
env -i PATH="$PATH" STAGING_ROOT="$PWD" bash tools/staging/offline.sh python3 -m unittest discover -s deploy/jobs -p 'test_*.py' -v
env -i PATH="$PATH" STAGING_ROOT="$PWD" bash tools/staging/offline.sh python3 deploy/jobs/manage.py validate deploy/jobs/definitions.json
env -i PATH="$PATH" STAGING_ROOT="$PWD" bash tools/staging/offline.sh python3 deploy/jobs/manage.py scratch-import deploy/jobs/definitions.json --destination /tmp/analyst-job-scratch-example123
```

Private exports can expose schedules, prompts, identifiers and configuration fingerprints even after value substitution. Keep export/reconstruction/skill audit outputs outside the public checkout and review independently; pattern substitution alone is not publication approval. Real operational declarations, targets, approvals, credentials, private settings, skills and timezone must be supplied privately. No activation or deployment is authorized by these examples.
