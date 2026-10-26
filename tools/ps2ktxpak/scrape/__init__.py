"""Scraper for the Texture Packs Archive spreadsheet: read it, download its free packs, convert them.

The download and conversion half (`job`) runs in a container and writes its results to a private
R2 bucket. The other half (`apply`) runs on a maintainer's machine: it reads those results and the
spreadsheet and writes pack and creator files, which the maintainer commits."""
