// Tiny inline SVG icon set (no icon library dependency).
type IconName =
  | "search"
  | "summary"
  | "math"
  | "data"
  | "biology"
  | "chat"
  | "menu"
  | "close"
  | "sun"
  | "moon"
  | "book"
  | "external"
  | "copy"
  | "check"
  | "plus"
  | "trash"
  | "download"
  | "upload"
  | "quote"
  | "logo";

const PATHS: Record<IconName, string> = {
  search: "M11 3a8 8 0 1 0 4.9 14.3l4.4 4.4 1.4-1.4-4.4-4.4A8 8 0 0 0 11 3Zm0 2a6 6 0 1 1 0 12 6 6 0 0 1 0-12Z",
  summary: "M5 3h9l5 5v13H5V3Zm8 1.5V7h2.5L13 4.5ZM7 11h10v1.6H7V11Zm0 4h10v1.6H7V15Z",
  math: "M5 4h14v2H5V4Zm2 5 5 5-5 5v-2.6l3-3.4-3-3.4V9Zm6 8h6v2h-6v-2Z",
  data: "M4 4h4v16H4V4Zm6 5h4v11h-4V9Zm6-3h4v14h-4V6Z",
  biology: "M16.5 3c-3 0-5.4 2-6.3 5.1-.3-.2-.7-.2-1-.1-2 .8-3.3 2.8-3.3 5.1 0 1 .2 2 .7 2.9-.9.2-1.6 1-1.6 2v2h2a2 2 0 0 0 2-2c0-.3 0-.5-.1-.8 1.7 1.1 3.9 1.3 5.8.4 1-.5 1.9-1.2 2.5-2.2 2.3-.6 4-2.7 4-5.2C21.2 6.3 19.2 3 16.5 3Zm-6.9 8.4c.6-1.2 1.8-2 2.7-2.4-.4 1-.6 2.2-.6 3.4 0 .8.1 1.6.4 2.3-.9-.1-1.7-.5-2.3-1.2-.6-.6-.9-1.4-.2-2.1Z",
  chat: "M4 4h16a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H9l-5 4V5a1 1 0 0 1 1-1Zm3 4h10v2H7V8Zm0 4h7v2H7v-2Z",
  menu: "M4 6h16v2H4V6Zm0 5h16v2H4v-2Zm0 5h16v2H4v-2Z",
  close: "M6.4 5 5 6.4 10.6 12 5 17.6 6.4 19 12 13.4 17.6 19 19 17.6 13.4 12 19 6.4 17.6 5 12 10.6 6.4 5Z",
  sun: "M12 5a1 1 0 0 1-1-1V2h2v2a1 1 0 0 1-1 1Zm0 14a1 1 0 0 1 1 1v2h-2v-2a1 1 0 0 1 1-1Zm7-7a1 1 0 0 1 1-1h2v2h-2a1 1 0 0 1-1-1ZM2 12a1 1 0 0 1 1-1h2v2H3a1 1 0 0 1-1-1Zm14.2-5.2.7-.7 1.4 1.4-.7.7-1.4-1.4ZM5.7 16.9l.7-.7 1.4 1.4-.7.7-1.4-1.4Zm11.4 1.4 1.4-1.4.7.7-1.4 1.4-.7-.7ZM6.4 6.1 5 4.7l.7-.7 1.4 1.4-.7.7ZM12 7a5 5 0 1 1 0 10 5 5 0 0 1 0-10Z",
  moon: "M12 3a9 9 0 1 0 9 9 7 7 0 0 1-9-9Z",
  book: "M5 3h6a3 3 0 0 1 3 3v13a3 3 0 0 0-3-3H5V3Zm14 0h-4a3 3 0 0 0-3 3v13a3 3 0 0 1 3-3h4V3Z",
  external: "M14 4h6v6h-2V7.4l-7.3 7.3-1.4-1.4L16.6 6H14V4ZM5 6h5v2H7v9h9v-3h2v5H5V6Z",
  copy: "M8 3h9a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1h-1v2a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h3V3Zm2 2h6v9h1V5H9v2Zm5 4v7H6V7h9v2Z",
  check: "M9.6 16.6 5 12l1.4-1.4 3.2 3.2L17.6 6 19 7.4 9.6 16.6Z",
  plus: "M11 5h2v6h6v2h-6v6h-2v-6H5v-2h6V5Z",
  trash: "M9 3h6l1 2h4v2H4V5h4l1-2ZM6 8h12l-1 12H7L6 8Zm3 2v8h1.5v-8H9Zm4.5 0v8H15v-8h-1.5Z",
  download: "M11 3h2v8.2l2.6-2.6L17 10l-5 5-5-5 1.4-1.4L11 11.2V3ZM5 18h14v2H5v-2Z",
  upload: "M11 21h2v-8.2l2.6 2.6L17 14l-5-5-5 5 1.4 1.4L11 12.8V21ZM5 4h14v2H5V4Z",
  quote: "M7 6h4v5H8.5c0 1.7.9 2.6 2.5 2.8V16c-3-.3-4-2.2-4-5V6Zm7 0h4v5h-2.5c0 1.7.9 2.6 2.5 2.8V16c-3-.3-4-2.2-4-5V6Z",
  // Scholaris "insight" sparkle — also used as the app favicon.
  logo: "M12 4.5 13.65 10.35 19.5 12 13.65 13.65 12 19.5 10.35 13.65 4.5 12 10.35 10.35 Z",
};

interface IconProps {
  name: IconName;
  size?: number;
  className?: string;
}

export function Icon({ name, size = 18, className }: IconProps) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden="true"
      focusable="false"
    >
      <path d={PATHS[name]} />
    </svg>
  );
}

export type { IconName };
