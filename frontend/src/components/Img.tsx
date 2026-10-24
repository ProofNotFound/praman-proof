// An <img> for listing photos. If the API can't serve a photo (e.g. the image cache isn't on this
// machine), it falls back once to the bundled, masked copy in public/demo/photos/.

import { useEffect, useState, type ImgHTMLAttributes } from "react";
import { assetUrl } from "../lib/api";

export function fallbackPhoto(src: string): string | null {
  const m = /^\/api\/photos\/([^/?]+)\/(\d+)(?:\?.*)?$/.exec(src);
  return m ? assetUrl(`demo/photos/${decodeURIComponent(m[1] ?? "")}/${m[2]}.jpg`) : null;
}

export function Img({ src, ...rest }: ImgHTMLAttributes<HTMLImageElement> & { src: string }) {
  const [current, setCurrent] = useState(src);
  useEffect(() => setCurrent(src), [src]);
  return (
    <img
      {...rest}
      src={current}
      onError={() => {
        const next = fallbackPhoto(current);
        if (next && next !== current) setCurrent(next);
      }}
    />
  );
}
