# Submissions

How a change made through the creator or pack form reaches the data files.

## Flow

1. The form on the site builds a submission: the fields that changed, as JSON. The page previews the file that
   results, using the same functions the workflow uses (`site/src/lib/creator-form.mjs`, `pack-form.mjs`).
2. Submitting opens `issues/new?template=submission.yml` with the submission and a title filled in. The person adds who
   they are and a link that shows it, and presses *Submit new issue*. A GitHub account is the only requirement.
3. `.github/workflows/submission.yml` runs for issues labelled `submission`. It writes the issue body to a file and
   runs `tools/node/apply-submission.mjs`, then `ps2ktxpak validate`.
4. If both pass, the workflow pushes `submission/issue-<number>`, opens a pull request (authored as the submitter, with
   `Closes #<number>`), comments the link on the issue and starts the site checks on the branch. If not, it comments
   what was wrong and changes nothing.
5. A person reviews and merges. That review is the check on who the submitter is.

## Format

```json
{"v": 1, "kind": "pack", "op": "update", "id": "sces-50885-quicksliver1",
 "set": {"description": "…", "media": null},
 "new": {"cost": "free", "hosting": "hosted"}}
```

- `kind` is `creator` or `pack`, `op` is `create` or `update`, `id` is a creator id or a pack key.
- `set` holds new values by field. `null` clears a field. Only these fields are accepted.
  Creator: `name`, `aliases`, `links.page`, `links.distribution`, `links.tip`, `links.socials`.
  Pack: `name`, `game`, `credits`, `type`, `completeness`, `description`, `sources`, `media`.
- `new` is present only for a new pack: `cost` (`free`, `free_with_ads`, `paid`, `unknown`) and `hosting`
  (`hosted` or `listed`).

Permission and hosting state are never read from a submission. For a new pack the workflow sets them: `published`
and `creator_approved` for hosted, `withheld` and permission unknown for listed only. Who changed what is in git
history, where the pull request credits the submitter.

## What is refused

Unknown fields, any field outside the lists above (so permission, hosting, access, review flags, avatar and
identity cannot be set), an existing id on create, a missing one on update, ids that do not match their pattern,
control characters, addresses that are not https or carry a username, a picture naming a stored copy that the pack
does not already have, a credit for a creator that does not exist, a name or alias that belongs to another creator,
anything the schema rejects, and a body over 64 KB. A refused submission writes nothing.

## Limits

GitHub rejects a prefilled issue address of 8192 bytes or more. When a submission does not fit, the form offers
GitHub's editor instead, with the whole file copied to paste. The checks of a pull request opened by the workflow
wait for a maintainer to approve the run, so the workflow also starts the site checks on the branch itself and their
result shows on the pull request.

## Setup

The repository needs *Allow GitHub Actions to create and approve pull requests* (Settings, Actions, General), and the
`submission` label (created by the issue template when first used).
