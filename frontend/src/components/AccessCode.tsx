// The access code for live checks on a public server. Kept for this tab only (sessionStorage).

import { useState } from "react";
import { getAccessCode, setAccessCode } from "../lib/api";

export function AccessCode({ id, autoFocus = false }: { id: string; autoFocus?: boolean }) {
  const [code, setCode] = useState(getAccessCode);
  return (
    <div className="access-code">
      <label htmlFor={id} className="label">
        Access code
      </label>
      <input
        id={id}
        type="text"
        autoFocus={autoFocus}
        autoComplete="off"
        autoCapitalize="off"
        autoCorrect="off"
        spellCheck={false}
        placeholder="Needed for pages outside the case files"
        value={code}
        onChange={(e) => {
          setCode(e.target.value);
          setAccessCode(e.target.value);
        }}
      />
    </div>
  );
}
