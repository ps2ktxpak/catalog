// Reads ../data at build time and turns it into the rows the pack and creator pages show.
// Nothing here is fetched at run time: the site is static HTML.
import fs from 'node:fs';
import path from 'node:path';
import YAML from 'yaml';

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
  /** The Archive lists it as sold by its creator. */
  paid: boolean;
  source?: { url: string; label: string };
}

const TYPE_LABEL: Record<string, string> = {
  ai_upscale: 'AI upscale', handcrafted: 'Handcrafted', mixed: 'Mixed', port: 'Port',
  button_replacement: 'Button replacement', unknown: 'Type not stated',
};
const COMPLETENESS_LABEL: Record<string, string> = {
  complete: 'Complete', in_progress: 'In progress', incomplete: 'Incomplete', partial: 'Partial', unknown: 'Status not stated',
};
const LINK_LABEL: Record<string, string> = {
  gbatemp: 'GBAtemp profile', youtube: 'YouTube', patreon: 'Patreon', kofi: 'Ko-fi', github: 'GitHub',
  discord: 'Discord', x: 'X', bluesky: 'Bluesky', facebook: 'Facebook', twitch: 'Twitch', paypal: 'PayPal',
  buymeacoffee: 'Buy Me a Coffee', mediafire: 'MediaFire', website: 'Website', other: 'Link',
};

export const typeLabel = (t: string) => TYPE_LABEL[t] ?? t;
export const completenessLabel = (c: string) => COMPLETENESS_LABEL[c] ?? c;
export const linkLabel = (k: string) => LINK_LABEL[k] ?? 'Link';

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
const jsonDir = (dir: string) =>
  fs.readdirSync(path.join(DATA, dir)).filter((f) => f.endsWith('.json')).sort()
    .map((f) => JSON.parse(fs.readFileSync(path.join(DATA, dir, f), 'utf8')));
const jsonl = (file: string) =>
  fs.readFileSync(path.join(DATA, file), 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l));

export interface Catalog {
  rows: Row[];
  creators: Map<string, Creator>;
  byCreator: Map<string, Row[]>;
  counts: { hosted: number; listed: number; creators: number };
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

  const listings = jsonl('listings/sad-origami-ps2.jsonl');
  const listingById = new Map(listings.map((l) => [l.id, l]));
  const matches = jsonl('links/listing-pack.jsonl');
  const matchedListings = new Set(matches.map((m) => m.listing));
  const archiveNames = new Map<string, Set<string>>();
  const costsByPack = new Map<string, string[]>();
  for (const m of matches) {
    const l = listingById.get(m.listing);
    if (l) costsByPack.set(m.pack, [...(costsByPack.get(m.pack) ?? []), l.access.cost]);
    if (l) archiveNames.set(m.pack, new Set([...(archiveNames.get(m.pack) ?? []), ...(l.creators ?? [])]));
  }
  const archives = new Map(jsonDir('archives').map((a) => [a.key, a]));

  const rows: Row[] = [];
  for (const p of yamlDir('packs')) {
    if (p.hosting?.state !== 'published') continue;
    const a = archives.get(p.key);
    const v = a?.versions.find((x: any) => x.revision === a.current);
    const costs = costsByPack.get(p.key) ?? [];
    const cost = p.access?.cost ?? (costs.includes('paid') ? 'paid' : 'other');
    const creds = who((p.credits ?? []).map((c: any) => c.creator));
    const credited = new Set(creds.map((c) => c.id));
    const archiveOnly = who([...(archiveNames.get(p.key) ?? [])].filter((id) => !credited.has(id)));
    const primary = (p.sources ?? []).find((s: any) => s.primary) ?? (p.sources ?? [])[0];
    const regions = [...new Set((p.game.serials as string[]).map(regionOfSerial).filter(Boolean))] as string[];
    rows.push({
      kind: 'hosted', id: p.key, title: p.game.title,
      packName: p.name && p.name !== p.game.title ? p.name : undefined,
      serials: p.game.serials, regions, creators: creds,
      archiveOnly,
      credit: creds.length === 0 ? 'unknown' : (p.needs_review ?? []).length ? 'review' : 'ok',
      type: p.type ?? 'unknown', completeness: p.completeness ?? 'unknown',
      sizeBytes: v?.size_bytes, paid: cost === 'paid',
      source: primary ? { url: primary.url, label: sourceLabel(primary.url) } : undefined,
    });
  }
  for (const l of listings) {
    if (matchedListings.has(l.id)) continue;       // already shown as the hosted pack
    const creds = who(l.creators ?? []);
    rows.push({
      kind: 'listed', id: l.id, title: l.title, serials: l.serials ?? [], regions: l.regions ?? [], creators: creds,
      archiveOnly: [],
      credit: creds.length === 0 ? 'unknown' : 'ok',
      type: l.type ?? 'unknown', completeness: l.completeness ?? 'unknown',
      paid: l.access.cost === 'paid',
      source: l.source_page ? { url: l.source_page, label: sourceLabel(l.source_page) } : undefined,
    });
  }
  rows.sort((a, b) => a.title.localeCompare(b.title, 'en', { sensitivity: 'base' }) || a.kind.localeCompare(b.kind));

  const byCreator = new Map<string, Row[]>();
  for (const r of rows) for (const c of [...r.creators, ...r.archiveOnly]) byCreator.set(c.id, [...(byCreator.get(c.id) ?? []), r]);

  cached = {
    rows, creators, byCreator,
    counts: { hosted: rows.filter((r) => r.kind === 'hosted').length, listed: rows.filter((r) => r.kind === 'listed').length, creators: byCreator.size },
  };
  return cached;
}
