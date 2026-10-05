// The vocabularies of a pack, shared by the pack list, the pack form and the tests. Plain .mjs so Node can
// import it. Every value here must be in schema/pack.schema.json.

export const TYPE_LABELS = {
  ai_upscale: 'AI upscale', handcrafted: 'Handcrafted', mixed: 'Mixed', port: 'Port',
  button_replacement: 'Button replacement', unknown: 'Type not stated',
};
export const COMPLETENESS_LABELS = {
  complete: 'Complete', in_progress: 'In progress', incomplete: 'Incomplete', partial: 'Partial', unknown: 'Status not stated',
};
export const COST_LABELS = { free: 'Free', free_with_ads: 'Free, with ads', paid: 'Paid', unknown: 'Not known' };
export const ROLE_LABELS = { author: 'Author', converter: 'Converter', contributor: 'Contributor', port: 'Port' };
export const SOURCE_KIND_LABELS = {
  forum_thread: 'Forum thread', creator_page: 'Creator page', repository: 'Repository', mirror: 'Download link',
  video: 'Video', shop: 'Shop', other: 'Other',
};

const MIRROR_HOSTS = [
  'drive.google.com', 'mega.nz', 'mega.io', 'mediafire.com', 'dropbox.com', '1drv.ms', 'onedrive.live.com',
  'archive.org', 'pixeldrain.com', 'gofile.io', 'terabox.com', 'sendspace.com', 'workupload.com',
];
const REPO_HOSTS = ['github.com', 'gitlab.com', 'codeberg.org', 'bitbucket.org'];
const CREATOR_PAGE_HOSTS = ['patreon.com', 'ko-fi.com', 'itch.io', 'gumroad.com', 'payhip.com', 'github.io'];

const onHost = (host, list) => list.some((h) => host === h || host.endsWith(`.${h}`));

/** The kind a source link most likely is, from its address. */
export function detectSourceKind(url) {
  let u;
  try {
    u = new URL(url);
  } catch {
    return null;
  }
  const host = u.hostname.toLowerCase();
  if (onHost(host, ['gbatemp.net'])) return u.pathname.includes('/threads/') ? 'forum_thread' : 'creator_page';
  if (onHost(host, ['youtube.com', 'youtu.be'])) return 'video';
  if (onHost(host, REPO_HOSTS)) return 'repository';
  if (onHost(host, MIRROR_HOSTS)) return 'mirror';
  if (onHost(host, CREATOR_PAGE_HOSTS)) return 'creator_page';
  return 'other';
}

/** { serials, bad }: every serial in the text as SLUS-20964, and the pieces that are not one. */
export function parseSerials(text) {
  const re = /([A-Za-z]{4})[\s_-]?(\d{3})\.?(\d{2})(?!\d)/g;
  const src = String(text ?? '');
  const serials = [];
  for (const m of src.matchAll(re)) {
    const s = `${m[1].toUpperCase()}-${m[2]}${m[3]}`;
    if (!serials.includes(s)) serials.push(s);
  }
  const rest = src.replace(re, ' ').replace(/[\s,;]+/g, ' ').trim();
  return { serials, bad: rest ? rest.split(' ') : [] };
}

/** The 11-character id of a YouTube video from a link or the bare id, or null. */
export function parseYoutubeId(input) {
  const s = String(input ?? '').trim();
  if (/^[A-Za-z0-9_-]{11}$/.test(s)) return s;
  let u;
  try {
    u = new URL(/^[a-z]+:\/\//i.test(s) ? s : `https://${s}`);
  } catch {
    return null;
  }
  const host = u.hostname.toLowerCase().replace(/^www\.|^m\./, '');
  let id = null;
  if (host === 'youtu.be') id = u.pathname.split('/')[1];
  else if (host === 'youtube.com' || host === 'music.youtube.com') {
    id = u.searchParams.get('v');
    const m = /^\/(?:embed|shorts|live|v)\/([^/?#]+)/.exec(u.pathname);
    if (!id && m) id = m[1];
  }
  return id && /^[A-Za-z0-9_-]{11}$/.test(id) ? id : null;
}
