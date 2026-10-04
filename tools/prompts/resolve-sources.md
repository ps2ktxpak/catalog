# Prompt: judge source pages

Given to an agent after `ps2ktxpak resolve-fetch` has written the evidence. Replace `{BRIEF}` with the
path of a file made by `ps2ktxpak resolve-brief`, and `{OUT}` with where the decisions should go; then
merge them with `ps2ktxpak resolve-apply {OUT} --model <model>`. Use a small model for ordinary pages
and a larger one for a library thread that covers dozens of games.

Keep this file in step with what is actually sent: a decision's reliability depends on these rules.

---

You are helping build a catalog of PS2 HD texture packs. Each "source page" is a forum thread (or
similar) where a creator announces a texture pack. For every listing on every source page, decide the
BASE DOWNLOAD LINK: the link the creator gives for the main texture pack for that game.

INPUT: read the evidence file {BRIEF}, a JSON list with one item per source page. Each item has
source_url, thread_title, listings (id, title, regions, creators, size), the thread starter's opening
posts (text trimmed), candidate_links (url, host, kind, where it was found, a short context snippet),
videos (the YouTube uploader's description and comments, read by a script) and already_decided.

OUTPUT: write a JSON list to {OUT} with the Write tool, ONE object per listing id in the input:

    {"source_url": "...", "listing": "l-xxxxxxxxxx", "status": "...", "base_url": "https://..." or null,
     "host": "...", "kind": "...", "confidence": "...", "reason": "..."}

status is one of:
- resolved: you found the link for this listing's pack. base_url is required.
- ambiguous: several links could be the pack and the evidence does not say which.
- gated: reachable only through a login or an account the public does not have, or through a link
  shortener or advert wall (ouo.io, adf.ly, linkvertise and the like). Name which in the reason.
- paid: the creator sells it (a priced shop item, a Patreon-only post, "support to unlock").
- dead: the page or link no longer works, or the creator says the pack was withdrawn.
- not_found: the page loaded, the evidence has no link, and nothing suggests one is hidden.

host is one of gdrive, mega, mediafire, terabox, dropbox, github, archive_org, pixeldrain, gofile,
kofi, patreon, direct, other. kind is one of file, folder, shop, page, unknown. Omit both when base_url
is null. confidence is `high` ONLY when the evidence itself says this link is the pack download,
`medium` when it is the most plausible, `low` when you are guessing. reason: one factual sentence of
at most 200 characters; do not copy passages from the pages.

RULES
- Prefer links the creator gave: the opening post, the creator's own follow-up posts, the uploader's
  description or pinned comment. A link from another user's reply is a mirror, not the creator's
  link: use it only if nothing else exists, with confidence `low`, and say so.
- A page can carry several games or versions: choose per the listing's title and regions. If the
  creator posted an update that replaces an earlier link, prefer the newest.
- Several listings can share one page (a creator's library of many games): give each its own link,
  matched by game title. If a link is for a whole collection, say so and use kind `folder`.
- Screenshots, comparison sites, donation pages and social links are never the base link.
- base_url must be an https URL that appears in the evidence or that you found by following a link.
  Never invent or guess a URL. A link typed without https:// in the opening post counts: add https://.
- If the text says "download" and no link survives in the evidence, say not_found unless the text says
  the link is hidden from guests, in which case say gated.
- You may fetch AT MOST 3 extra public pages per source page with WebFetch when the evidence is not
  enough (for example to see whether a Ko-fi shop item is free or priced). Never download a pack
  file, never log in, never get around a paywall or captcha.

When done, reply in under 120 words: the count per status and anything surprising.
