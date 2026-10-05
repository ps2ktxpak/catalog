// Reads ../data at build time and turns it into the rows the pack and creator pages show.
// Nothing here is fetched at run time: the site is static HTML.
import fs from 'node:fs';
import path from 'node:path';
import YAML from 'yaml';
import { KIND_LABELS } from './kinds.mjs';
import { COMPLETENESS_LABELS, TYPE_LABELS } from './vocab.mjs';

const DATA = process.env.PS2KTXPAK_DATA ?? path.resolve(process.cwd(), '../data');

export interface Link { kind: string; url: string }
export interface Creator {
  id: string;
  name: string;
  aliases: string[];
  links: { page?: string; distribution?: string; tip: Link[]; socials: Link[] };
}
export interface Row {
  /** `hosted`: a pack with a converted copy. `listed`: a line in the Texture Packs Archive, not hosted. */
  kind: 'hosted' | 'listed';
  id: string;
  title: string;
  packName?: string;
  serials: string[];
  regions: string[];
  creators: { id: string; name: string }[];
  /** Why the credit is uncertain, if it is. */
  credit: 'ok' | 'unknown' | 'review';
  /** Creators the Texture Packs Archive names for this pack and the credit here does not. The pack still appears on their page. */
  archiveOnly: { id: string; name: string }[];
  type: string;
  completeness: string;
  sizeBytes?: number;
  /** A converted copy exists. A hosted pack without one is accepted for hosting and waiting to be converted. */
  converted: boolean;
  /** The Archive lists it as sold by its creator. */
  paid: boolean;
  source?: { url: string; label: string };
}

export const typeLabel = (t: string): string => (TYPE_LABELS as Record<string, string>)[t] ?? t;
export const completenessLabel = (c: string): string => (COMPLETENESS_LABELS as Record<string, string>)[c] ?? c;
export const linkLabel = (k: string): string => (KIND_LABELS as Record<string, string>)[k] ?? 'Link';

const nameKey = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, '');

function regionOfSerial(serial: string): string | null {
  const p = serial.slice(0, 4);
  if (['SLUS', 'SCUS', 'SLUD', 'SCUD'].includes(p)) return 'NTSC-U';
  if (['SLES', 'SCES', 'SCED', 'SLED'].includes(p)) return 'PAL';
  if (['SLPS', 'SLPM', 'SCPS', 'SCAJ', 'SLAJ', 'SCPM', 'SLPN'].includes(p)) return 'NTSC-J';
  if (['SLKA', 'SCKA'].includes(p)) return 'NTSC-K';
  return null;
}

/** "GBAtemp thread", "Patreon", "MediaFire": what a reader should expect to find behind a link. */
export function sourceLabel(url: string): string {
  const u = new URL(url);
  const host = u.hostname.replace(/^www\./, '');
  if (host.endsWith('gbatemp.net')) return u.pathname.includes('/threads/') ? 'GBAtemp thread' : 'GBAtemp';
  if (host.endsWith('patreon.com')) return 'Patreon';
  if (host.endsWith('ko-fi.com')) return 'Ko-fi';
  if (host.endsWith('github.com') || host.endsWith('github.io')) return 'GitHub';
  if (host.endsWith('mediafire.com')) return 'MediaFire';
  if (host.endsWith('archive.org')) return 'Internet Archive';
  if (host.endsWith('youtube.com') || host === 'youtu.be') return 'YouTube';
  return host;
}

export function formatSize(bytes: number): string {
  const gb = bytes / 1024 ** 3;
  return gb >= 1 ? `${gb.toFixed(1)} GB` : `${Math.max(1, Math.round(bytes / 1024 ** 2))} MB`;
}

const yamlDir = (dir: string) =>
  fs.readdirSync(path.join(DATA, dir)).filter((f) => f.endsWith('.yaml')).sort()
    .map((f) => YAML.parse(fs.readFileSync(path.join(DATA, dir, f), 'utf8')));

export interface Catalog {
  rows: Row[];
  creators: Map<string, Creator>;
  byCreator: Map<string, Row[]>;
  counts: { hosted: number; awaiting: number; listed: number; creators: number };
  /** The key of every pack file, whatever its state: a new pack's key must not collide with any of them. */
  packKeys: string[];
}

let cached: Catalog | null = null;

export function loadCatalog(): Catalog {
  if (cached) return cached;

  const creators = new Map<string, Creator>();
  for (const c of yamlDir('creators')) {
    const seen = new Set([nameKey(c.name)]);
    const aliases: string[] = [];
    for (const a of c.aliases ?? []) {
      if (!seen.has(nameKey(a))) { seen.add(nameKey(a)); aliases.push(a); }   // "bl4ckh4nd" under "Bl4ckH4nd" is noise
    }
    creators.set(c.id, {
      id: c.id, name: c.name, aliases,
      links: { page: c.links?.page, distribution: c.links?.distribution, tip: c.links?.tip ?? [], socials: c.links?.socials ?? [] },
    });
  }
  const who = (ids: string[]) => ids.filter((i) => creators.has(i)).map((i) => ({ id: i, name: creators.get(i)!.name }));

  const packs = yamlDir('packs');
  const rows: Row[] = [];
  for (const p of packs) {
    const state = p.hosting?.state;
    if (state !== 'published' && state !== 'listed') continue;   // a pack that is held back or withdrawn is not on the list
    const hosted = state === 'published';
    const creds = who((p.credits ?? []).map((c: any) => c.creator));
    const credited = new Set(creds.map((c) => c.id));
    const listedOnly = who((p.listed_credits ?? []).filter((id: string) => !credited.has(id)));
    const primary = (p.sources ?? []).find((s: any) => s.primary) ?? (p.sources ?? [])[0];
    const serials: string[] = p.game.serials ?? [];
    const archive = p.archive;
    const v = archive?.versions.find((x: any) => x.revision === archive.current);
    rows.push({
      kind: hosted ? 'hosted' : 'listed', id: p.key, title: p.game.title,
      packName: p.name && p.name !== p.game.title ? p.name : undefined,
      serials,
      regions: p.game.regions ?? ([...new Set(serials.map(regionOfSerial).filter(Boolean))] as string[]),
      creators: creds,
      archiveOnly: listedOnly,
      credit: creds.length === 0 ? 'unknown' : hosted && (p.needs_review ?? []).length ? 'review' : 'ok',
      type: p.type ?? 'unknown', completeness: p.completeness ?? 'unknown',
      sizeBytes: v?.size_bytes, converted: !!archive, paid: p.access?.cost === 'paid',
      source: primary ? { url: primary.url, label: sourceLabel(primary.url) } : undefined,
    });
  }
  rows.sort((a, b) => a.title.localeCompare(b.title, 'en', { sensitivity: 'base' }) || a.kind.localeCompare(b.kind));

  const byCreator = new Map<string, Row[]>();
  for (const r of rows) for (const c of [...r.creators, ...r.archiveOnly]) byCreator.set(c.id, [...(byCreator.get(c.id) ?? []), r]);

  cached = {
    rows, creators, byCreator, packKeys: packs.map((p) => p.key),
    counts: {
      hosted: rows.filter((r) => r.kind === 'hosted').length,
      awaiting: rows.filter((r) => r.kind === 'hosted' && !r.converted).length,
      listed: rows.filter((r) => r.kind === 'listed').length, creators: byCreator.size },
  };
  return cached;
}
