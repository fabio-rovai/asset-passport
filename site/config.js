// Where the live forge finds the engine API. The static copy on GitHub Pages
// has no server of its own, so it calls the Vercel deployment named below.
// Every other host (python3 local.py, the Vercel deployment itself) serves
// the API next to the page and uses a relative path.
//
// VERCEL_API is the production URL exactly as Vercel assigned it, with no
// trailing slash. While it is empty, the GitHub Pages copy keeps the forge off.
(function () {
  "use strict";
  const VERCEL_API = "";
  const onPages = location.hostname.endsWith("github.io");
  window.ASSET_PASSPORT_API_BASE = onPages && VERCEL_API ? VERCEL_API + "/" : "";
})();
