// The kinds of link a creator can carry, shared by the creator pages and the creator form.
// Plain .mjs so the tests can import it in Node. Every kind here must be in schema/creator.schema.json.

export const KIND_LABELS = {
  gbatemp: 'GBAtemp profile', youtube: 'YouTube', patreon: 'Patreon', kofi: 'Ko-fi', github: 'GitHub',
  discord: 'Discord', x: 'X', bluesky: 'Bluesky', facebook: 'Facebook', twitch: 'Twitch', paypal: 'PayPal',
  buymeacoffee: 'Buy Me a Coffee', mediafire: 'MediaFire', website: 'Website', other: 'Link',
};

export const TIP_KINDS = ['patreon', 'kofi', 'paypal', 'buymeacoffee', 'github', 'website', 'other'];
export const SOCIAL_KINDS = ['gbatemp', 'youtube', 'github', 'discord', 'x', 'bluesky', 'facebook', 'twitch', 'mediafire', 'website', 'other'];

const HOSTS = [
  ['gbatemp.net', 'gbatemp'], ['youtube.com', 'youtube'], ['youtu.be', 'youtube'], ['patreon.com', 'patreon'],
  ['ko-fi.com', 'kofi'], ['github.com', 'github'], ['github.io', 'github'], ['discord.gg', 'discord'],
  ['discord.com', 'discord'], ['x.com', 'x'], ['twitter.com', 'x'], ['bsky.app', 'bluesky'],
  ['facebook.com', 'facebook'], ['fb.com', 'facebook'], ['twitch.tv', 'twitch'], ['paypal.com', 'paypal'],
  ['paypal.me', 'paypal'], ['buymeacoffee.com', 'buymeacoffee'], ['mediafire.com', 'mediafire'],
];

/** The kind a link most likely is, from its host; 'website' when the host is not a known one. */
export function detectKind(url) {
  let host;
  try {
    host = new URL(url).hostname.toLowerCase();
  } catch {
    return null;
  }
  for (const [suffix, kind] of HOSTS) {
    if (host === suffix || host.endsWith(`.${suffix}`)) return kind;
  }
  return 'website';
}
