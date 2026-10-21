import { useState } from "react";

import type { CitationStyles } from "../../api/types";
import { Icon } from "../../components/Icon";

type StyleKey = keyof CitationStyles;

const TABS: Array<{ key: StyleKey; label: string }> = [
  { key: "apa", label: "APA 7" },
  { key: "mla", label: "MLA 9" },
  { key: "chicago", label: "Chicago" },
];

/** Citation styles with a dropdown-style tab switcher and copy buttons. */
export function CitationTabs({ styles }: { styles: CitationStyles }) {
  const [active, setActive] = useState<StyleKey>("apa");
  const [copied, setCopied] = useState<StyleKey | null>(null);

  const copy = async (key: StyleKey) => {
    const text = styles[key];
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // Clipboard API can be blocked; fall back to a temporary textarea.
      const textarea = document.createElement("textarea");
      textarea.value = text;
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      textarea.remove();
    }
    setCopied(key);
    window.setTimeout(() => setCopied((current) => (current === key ? null : current)), 1500);
  };

  return (
    <div>
      <div className="tabs" role="tablist" aria-label="Citation style">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            role="tab"
            aria-selected={active === tab.key}
            className={`tab ${active === tab.key ? "tab-active" : ""}`}
            onClick={() => setActive(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="citation-box">
        <pre className="citation-text">{styles[active]}</pre>
        <button
          type="button"
          className="btn btn-small"
          onClick={() => copy(active)}
          aria-label={`Copy ${active} citation`}
        >
          <Icon name={copied === active ? "check" : "copy"} size={15} />
          {copied === active ? "Copied" : "Copy"}
        </button>
      </div>
    </div>
  );
}
