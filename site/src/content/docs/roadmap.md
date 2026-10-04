---
title: Roadmap
description: What is done, what is next, and what is still undecided.
---

A plan, not a promise. Order matters more than dates.

## Done

- The data model, its schemas and a validator.
- The Archive's PS2 tab imported as listings and creators.
- The 517 inherited packs imported, with the old catalog's text kept for the record.
- A compiler that rebuilds today's published catalog byte for byte.
- A tool that follows each listing's source page to the real download.

## Next

1. **Review.** People clear the credit flags: creators assigned from a listing, unconfirmed
   co-credits, unknown creators. Settle the packs that are listed as paid but already hosted.
2. **Publish the cleaned catalog.** Same file, same shape, correct names and links. Every installed
   build improves with no app update. The overlay file for newer builds is generated from the same data.
3. **App release reads creators from the catalog itself**, so the overlay file can retire.
4. **Bring in more packs.** A bulk handoff from the Archive's maintainer, converted to ASTC by a
   container image that can run anywhere (a Cloudflare container, a rented machine, or a desktop).
   Free packs only.
5. **Creator web service.** Accounts, uploads and edits, with D1 as the store and the same compile
   step in front of it. The static files stay what the app reads.
6. **Signed metadata**, so a compromised host cannot redirect everyone's links.

## Undecided

- The license for the data, and how the Archive is credited.
- What to do about packs already hosted that their creators sell.
- Whether packs that are only listed, because they are paid, appear in the app as link-outs.
