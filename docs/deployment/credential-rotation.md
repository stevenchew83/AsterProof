# Production credential and host-key rotation

Rotate without creating a second deployment authority. Never paste private keys, tokens, environment contents, or an unredacted `known_hosts` inventory into Git, issues, workflow logs, or chat.

## Scheduled deploy-key rotation

1. Schedule a staffed release window and confirm no deployment or rollback operation is running.
2. Generate a new dedicated key in an approved secret-management environment. It must not be shared with another project or user.
3. Add the new public key to the dedicated server account with the exact existing forced-command and forwarding restrictions. Keep the old key temporarily so rotation can be tested safely.
4. Independently verify the target marker and host key. Do not obtain trust by running `ssh-keyscan` inside the deployment workflow.
5. Replace only `PRODUCTION_SSH_PRIVATE_KEY` in the GitHub `production` environment.
6. Dispatch a non-mutating protected preflight and prove the new key reaches the correct forced-command gateway; shell, forwarding, SCP, and SFTP must remain unavailable.
7. Remove the old public key from the server and revoke/delete the old private key at its source.
8. Repeat the protected preflight. Record old/new public-key fingerprints, actors, timestamps, target marker, test run URLs, and revocation evidence. Never record private material.

If the new-key test fails, restore the environment secret to the old key while it is still authorized, diagnose without widening server access, and do not revoke the old key until the tested path succeeds.

## SSH host-key rotation

Host-key change is an identity event, not a warning to bypass.

1. Stop normal deployments.
2. Confirm the change through an independently authorized provider/server channel and record hostname, host marker, algorithm, and old/new fingerprints.
3. Replace `PRODUCTION_SSH_KNOWN_HOSTS` with exactly one reviewed line for the configured host/port. Never use `StrictHostKeyChecking=no` or dynamic key discovery.
4. Run the protected non-mutating preflight and verify the marker, repository ID, service identity, filesystem boundaries, and drift hashes.
5. Revoke the old host identity where applicable and record the completed change.

An unexplained host-key change is a possible compromise. Follow [disaster recovery](disaster-recovery.md), rotate the deploy key and GitHub recovery credentials, and do not resume normal deployment until the target is re-inventoried.

## Account or GitHub compromise

Immediately suspend routine deployment, revoke the deploy public key and GitHub environment secret, rotate account recovery methods and tokens, inspect environment approvals/workflow runs/ruleset changes, and re-bootstrap authority files if their hashes cannot be proven. Resume only after a clean governance read-back, target drift audit, and reconciliation record.
