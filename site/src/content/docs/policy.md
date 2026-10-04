---
title: Hosting policy
description: What is hosted, what is not, and what happens on a request to stop.
---

{/* TODO: draft of the project's rules. The owner and Sad Origami should agree it before the site is public. */}

## Hosted packs

A pack is hosted only if **both** are true:

1. It is **free to the public** where its creator distributes it. A pack sold by its creator, or locked
   behind a paid membership, is not hosted.
2. **Permission** to host a copy exists: the creator uploaded it, or approved it, or (for the packs
   inherited from the earlier catalog) permission is recorded as unknown and pending.

Cost and permission are separate. A free download is not permission to redistribute it.

A creator can approve a pack that is otherwise paid. The approval and its evidence are written into the
pack's `permission` field; validation allows a paid pack to be hosted only then.

## Removal

On a creator's request a pack, or a whole page, is removed. The pack is marked `withdrawn` rather than
deleted, so installed copies still resolve, and the archive stops being served. That a removal happened is
recorded; the private details of the request are not.

## Credit

Every pack credits its creators as they name themselves. Where no one has named the creator the credit
reads "unknown" rather than a guess, since a wrong guess is worse than a gap.

## Published information

- A creator's name, the links made public by the creator (profile, tip and social pages), and a copy of
  the public profile picture, which is hosted separately and removed on request.
- Email addresses, private messages and the contents of takedown notices are never published.
- The free mirrors and the blacklist of the Texture Packs Archive are not republished.
- Pack and creator files contain no quotations from private conversations.

## Pictures and videos

Example pictures are screenshots by their creators. The address where each is shown is recorded, each is
credited to its creator, and a small resized copy is shown rather than a link to a forum's images, since
linking sends the forum every visitor's traffic. A picture is removed on request. Videos are YouTube
links, shown as a thumbnail; the player loads, and YouTube sees the visitor, only after a click.

## Links

Every link is https. Link shorteners are flagged, because they hide where a link goes.

## License of this data

The repository, data included, is under the MIT license (`LICENSE`). That covers the files in this
repository: the catalog records, schemas, tools and site. It does not cover texture pack files,
pictures or names, which belong to their creators and are neither relicensed nor transferred by it.

{/* TODO: how the Texture Packs Archive is credited, to be decided with Sad Origami. */}
