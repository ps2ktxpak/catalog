# Resolving sources

How the real download behind a forum thread is found, and who decides what.

A listing's download link is almost always a forum thread, not a file. The real link (Google Drive,
Mega, MediaFire and so on) is inside the thread, or in a YouTube video the thread embeds: the
uploader's description or pinned comment. Resolving a source means following that chain to the link
the creator gives for the pack, and recording what was found.

## Two layers

**Layer 1, a script, no judgement.** `ps2ktxpak resolve-fetch` reads each source page once, politely,
and writes `data/resolution/<hash>.json`:

- the links in the thread starter's opening post and in their own follow-up posts, each with a short
  snippet of the text around it;
- a few links from other people's replies, marked as such, because a mirror posted by a stranger is
  not the creator's link;
- for each embedded YouTube video, the links in the uploader's description and in pinned or own
  comments, read with yt-dlp, which needs no account or key.

It decides only the unambiguous case: a single listing on the page and exactly one file-host link in
the creator's own words. That decision is `resolved` with `medium` confidence, because "the only link"
can still be an add-on or a screenshot folder.

**Layer 2, an agent, judgement only.** What the script leaves goes to an agent that reads the written
evidence, and may open at most three extra public pages per source page to check a link: library threads that cover dozens of games, pages with several candidate
links, pages with none. It returns a decision per listing. `ps2ktxpak resolve-brief` prepares the
evidence and `ps2ktxpak resolve-apply` merges the decisions. The instructions given to the agents are
kept in `tools/prompts/resolve-sources.md`, so a re-run asks the same questions.

## Statuses

| Status | Meaning |
|---|---|
| `resolved` | The base link for the pack, with host, kind (`file`, `folder`, `shop`, `page`) and confidence. |
| `ambiguous` | Several links could be the pack and the evidence does not say which. |
| `gated` | Behind a login or an account the public does not have, or behind a link shortener or advert wall. |
| `paid` | The creator charges for it. That is recorded and nothing further is done. |
| `dead` | The page or the link no longer works. |
| `not_found` | The page loaded and gives no download. |

## Rules

- Public pages only. No logins, no downloads, no bypassing a paywall or a captcha.
- Pages are requested about once every 1.5 seconds, with a user agent that names this project.
  GBAtemp's robots.txt allows thread pages; the script requests nothing it disallows.
- Pages and video data are cached under `cache/`, which is not committed, so a re-run costs nothing.
- The files in `data/resolution/` hold links and short snippets only, never page text.
- A decision an agent made is never overwritten by a re-fetch. A decision a person made is never
  overwritten by an agent.
