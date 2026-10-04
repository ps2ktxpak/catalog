// Internal links go through here so the site works at a root (local preview) and under a
// sub-path (https://<org>.github.io/<repo>/), where BASE_URL is "/<repo>/".
export const href = (path: string): string => import.meta.env.BASE_URL.replace(/\/$/, '') + path;
