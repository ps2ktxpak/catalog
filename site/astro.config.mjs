import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

// BASE_PATH / SITE_URL are set by the Pages workflow (e.g. /catalog and https://ps2ktxpak.github.io);
// locally they are unset and the site is served from the root.
// Static output: deploy the contents of site/dist to Cloudflare (Pages or Workers static assets).
export default defineConfig({
  site: process.env.SITE_URL || undefined,
  base: process.env.BASE_PATH || '/',
  // The creator form imports schema/ at the repository root.
  vite: { server: { fs: { allow: ['..'] } } },
  integrations: [
    starlight({
      title: 'PS2 Texture Packs',
      description: 'PS2 texture packs.',
      customCss: ['./src/styles/catalog.css'],
      // The header link back to the repository, where the data is edited.
      social: [{ icon: 'github', label: 'GitHub', href: 'https://github.com/ps2ktxpak/catalog' }],
      head: [{ tag: 'meta', attrs: { name: 'robots', content: 'noindex, nofollow' } }],
      sidebar: [
        { label: 'Packs', link: '/' },
        { label: 'Creators', link: '/creators/' },
      ],
    }),
  ],
});
