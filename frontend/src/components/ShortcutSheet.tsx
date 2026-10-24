// The shortcut sheet (?), DESIGN §7.

import { useEffect, useRef } from "react";
import { X } from "lucide-react";

const KEYS: [string, string][] = [
  ["Space", "Pause or resume the run"],
  ["→", "Release exactly one event (step)"],
  ["R", "Restart the case"],
  ["1–4", "Open the demo cases"],
  ["B", "Compare agent and text-only"],
  ["← →", "Move the compare divider by 10%"],
  ["E", "Open the report"],
  ["P", "Present mode"],
  ["?", "This sheet"],
  ["Esc", "Close"],
];

export function ShortcutSheet({ onClose }: { onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (d && !d.open) d.showModal();
  }, []);
  return (
    <dialog ref={ref} className="sheet" aria-labelledby="keys-title" onClose={onClose} onCancel={onClose}>
      <div className="sheet-head">
        <h2 id="keys-title">Keyboard</h2>
        <button type="button" className="icon-btn" onClick={onClose} aria-label="Close">
          <X size={18} strokeWidth={1.5} />
        </button>
      </div>
      <dl>
        {KEYS.map(([k, what]) => (
          <div key={k} className="sheet-row">
            <dt>
              <kbd>{k}</kbd>
            </dt>
            <dd>{what}</dd>
          </div>
        ))}
      </dl>
    </dialog>
  );
}
