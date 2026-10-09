// Where the live forge finds the engine API. The static copy on GitHub Pages
// has no server of its own, so it calls the Vercel deployment named below.
// Only the published host fabio-rovai.github.io does this, the same single
// origin the API's CORS allow-list names; a fork on another github.io host
// would be refused by CORS anyway, so it is not sent there at all. Every other
// host (python3 local.py, the Vercel deployment itself) serves the API next to
// the page and uses a relative path.
//
// VERCEL_API is the production URL exactly as Vercel assigned it, with no
// trailing slash. While it is empty, the GitHub Pages copy keeps the forge off.
(function () {
  "use strict";
  const VERCEL_API = "";
  const PAGES_HOST = "fabio-rovai.github.io";
  const onPages = location.hostname === PAGES_HOST;
  window.ASSET_PASSPORT_API_BASE = onPages && VERCEL_API ? VERCEL_API + "/" : "";
})();
