import type { ReactNode } from "react";

interface FriendlyStateProps {
  title: string;
  children?: ReactNode;
  actions?: ReactNode;
  compact?: boolean;
}

/**
 * The small plain-text `:(` state used for low, empty, and failed searches.
 * It stays centered on phones and deliberately avoids an emoji font.
 */
export function FriendlyState({ title, children, actions, compact = false }: FriendlyStateProps) {
  return (
    <div
      className={`empty-state empty-hero friendly-state${compact ? " empty-compact" : ""}`}
      role="status"
    >
      <div className="empty-face" aria-hidden="true">
        :(
      </div>
      <h2>{title}</h2>
      {children ? <p className="muted">{children}</p> : null}
      {actions ? <div className="empty-actions">{actions}</div> : null}
    </div>
  );
}
