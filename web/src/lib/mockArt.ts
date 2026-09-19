// Stand-in cutouts for mock mode, used only while the real art for an object has not
// been generated yet. Flat, neutral silhouettes with a transparent background, so the
// highlight outline and registration can still be judged.

const wrap = (w: number, h: number, body: string) =>
  `data:image/svg+xml;utf8,${encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" width="${w * 4}" height="${h * 4}">${body}</svg>`,
  )}`;

const SHAPES: Record<string, string> = {
  beer: wrap(
    40,
    120,
    `<path d="M15 2h10v26c0 8 9 12 9 24v62a4 4 0 0 1-4 4H10a4 4 0 0 1-4-4V52c0-12 9-16 9-24z" fill="#4d5a3c"/>
     <rect x="6" y="62" width="28" height="30" fill="#d9d2c0"/><rect x="15" y="2" width="10" height="7" fill="#b9a66a"/>`,
  ),
  water: wrap(
    40,
    110,
    `<path d="M14 2h12v14c0 6 8 8 8 18v70a4 4 0 0 1-4 4H10a4 4 0 0 1-4-4V34c0-10 8-12 8-18z" fill="#a9c3cf" fill-opacity=".85"/>
     <rect x="6" y="52" width="28" height="22" fill="#e9eef0"/><rect x="14" y="2" width="12" height="8" fill="#5f7f92"/>`,
  ),
  tea: wrap(
    90,
    64,
    `<path d="M8 10h58v26a24 24 0 0 1-24 24h-10A24 24 0 0 1 8 36z" fill="#d8d2c4"/>
     <path d="M66 18h8a10 10 0 0 1 0 20h-8v-7h7a3 3 0 0 0 0-6h-7z" fill="#d8d2c4"/>
     <ellipse cx="37" cy="12" rx="27" ry="6" fill="#7a5a36"/>`,
  ),
  menu: wrap(
    70,
    96,
    `<rect x="3" y="3" width="64" height="90" rx="3" fill="#2a2523"/><rect x="9" y="9" width="52" height="78" fill="#e6dfd0"/>
     <g fill="#8a8172"><rect x="16" y="20" width="38" height="4"/><rect x="16" y="34" width="30" height="3"/><rect x="16" y="44" width="34" height="3"/><rect x="16" y="54" width="26" height="3"/><rect x="16" y="64" width="32" height="3"/></g>`,
  ),
  money: wrap(
    120,
    60,
    `<rect x="10" y="10" width="104" height="46" rx="3" fill="#8f5a5a"/><rect x="4" y="4" width="104" height="46" rx="3" fill="#b97a76"/>
     <rect x="10" y="10" width="92" height="34" rx="2" fill="none" stroke="#e7c9c2" stroke-width="1.5"/><circle cx="56" cy="27" r="10" fill="#e7c9c2"/>`,
  ),
  noodles: wrap(
    110,
    70,
    `<path d="M6 26h98a49 40 0 0 1-98 0z" fill="#d7d0c2"/><ellipse cx="55" cy="26" rx="49" ry="9" fill="#c9a25e"/>
     <path d="M70 4l8 2-22 20h-6zM80 6l8 3-26 17h-7z" fill="#5a4632"/>`,
  ),
  dumplings: wrap(
    120,
    64,
    `<rect x="6" y="30" width="108" height="28" rx="5" fill="#b08d57"/><ellipse cx="60" cy="30" rx="54" ry="11" fill="#caa76c"/>
     <g fill="#efe8da"><ellipse cx="38" cy="26" rx="15" ry="9"/><ellipse cx="66" cy="23" rx="15" ry="9"/><ellipse cx="88" cy="28" rx="14" ry="8"/></g>`,
  ),
};

SHAPES.photo = wrap(
  80,
  96,
  `<g transform="rotate(-5 40 48)"><rect x="8" y="6" width="64" height="82" rx="2" fill="#e9e4d8"/><rect x="13" y="11" width="54" height="56" fill="#3d4a4f"/>
   <circle cx="40" cy="32" r="10" fill="#c9a98c"/><path d="M22 67c2-14 9-20 18-20s16 6 18 20z" fill="#7b4a4a"/><path d="M29 30c0-9 5-14 11-14s11 5 11 14c-3-5-7-7-11-7s-8 2-11 7z" fill="#1d1a19"/></g>`,
);
SHAPES.chili = wrap(50, 80, `<rect x="8" y="14" width="34" height="62" rx="6" fill="#8e2f25"/><rect x="12" y="4" width="26" height="12" rx="2" fill="#b9b3a6"/>`);

const GENERIC = wrap(60, 60, `<rect x="6" y="6" width="48" height="48" rx="8" fill="#8d8a84"/>`);

export function placeholderCutout(objectId: string): string {
  return SHAPES[objectId] ?? GENERIC;
}
