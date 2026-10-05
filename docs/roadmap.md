# Roadmap

What is done, what is next, and what is still undecided.

A plan, not a promise. Order matters more than dates.

## Done

- The data model, its schemas and a validator.
- The Archive's PS2 tab and the 517 inherited packs imported once. The repository is the master copy from here on; nothing is re-imported.
- A compiler that builds the catalog and the overlay file from the data.
- A decision for each unhosted listing on where its real download is (`data/resolution/`).
- The pack list and creator pages as a static site, public on GitHub Pages.
- MIT license for the repository, data included.
- A creator form and a pack form on the site. Submitting files an issue and a workflow turns it into a pull request, so
  no git, fork or write access is needed to add or edit either. A new pack starts hosted.

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
   step in front of it. The static files stay what the app reads. (A sign-in relay with an in-page commit is the
   alternative to the issue-based forms if those prove too clumsy.)
6. **Signed metadata**, so a compromised host cannot redirect everyone's links.

## Undecided

- How the Archive is credited.
- What to do about packs already hosted that their creators sell.
- Whether a new pack's approval, as stated on the form, needs more than a review of the pull request.
- Whether packs that are only listed, because they are paid, appear in the app as link-outs.
