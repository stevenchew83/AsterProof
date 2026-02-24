# Part A Rollout and Migration Safeguards

## Rollout stages

1. **Internal seed stage**
   - Enable all `FEATURE_FLAGS` in local and staging.
   - Seed baseline contests/problems/tags via admin.
2. **Registered beta**
   - Keep public leaderboards low-visibility.
   - Open progress, notes, and community to authenticated users.
3. **Public launch**
   - Enable profile discovery, trending, and feedback board.
   - Keep contest ratings to selected events only.
4. **Rated contests**
   - Enable `contests_rating` in production.
   - Run `apply_simple_elo` only after frozen scoreboards.

## Migration safeguards

- Run schema migrations in this order:
  1. `catalog`
  2. `progress` + `notes`
  3. `community` + `organization`
  4. `profiles` + `feedback`
  5. `contests` + `analytics`
- Verify no dynamic route overlap after URL namespace updates.
- Keep profile visibility defaults as `public` and `show_in_leaderboards=True` for backwards compatibility.

## Backfill checks

- Create a dry-run script/command for contest/problem imports before production writes.
- Backfill rating snapshots from existing user `rating` values before first rated contest.
- Record all backfill runs in deployment notes with timestamp and affected rows.
