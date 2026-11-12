import { cn } from "@stark/ui/utils/cn";

const helmet =
  "M12 1.5c-4.6 0-8.3 3.3-8.3 7.9V15c0 1.5.7 2.9 1.8 3.8L9 22h6l3.5-3.2A4.9 4.9 0 0020.3 15V9.4c0-4.6-3.7-7.9-8.3-7.9z";

type LogoMarkProps = {
  size?: number;
  /** The helmet's eye cut-outs take the background colour they sit on. */
  cutout?: string;
  className?: string;
  /** Sweep a highlight across the visor. The keyframes live in the UI globals. */
  glint?: boolean;
};

export function LogoMark({
  size = 26,
  cutout = "#111214",
  className,
  glint = false,
}: LogoMarkProps) {
  return (
    <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" className={className}>
      {glint ? (
        <defs>
          <clipPath id="stark-helmet">
            <path d={helmet} />
          </clipPath>
          <linearGradient id="stark-visor-glint" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0" stopColor="#fff" stopOpacity="0" />
            <stop offset="0.5" stopColor="#fff" stopOpacity="0.55" />
            <stop offset="1" stopColor="#fff" stopOpacity="0" />
          </linearGradient>
        </defs>
      ) : null}
      <path fill="#C2410C" d={helmet} />
      <path
        fill={cutout}
        d="M6.6 10.2l4 .9v1.5l-4-.6zM17.4 10.2l-4 .9v1.5l4-.6zM10 17.2h4v1h-4zM11.4 3.2h1.2v4h-1.2z"
      />
      {glint ? (
        <g clipPath="url(#stark-helmet)" transform="rotate(16 12 12)">
          <rect
            className="logo-glint"
            x="-15"
            y="-8"
            width="7"
            height="40"
            fill="url(#stark-visor-glint)"
          />
        </g>
      ) : null}
    </svg>
  );
}

export function Logo({
  className,
  cutout,
  size,
}: {
  className?: string;
  cutout?: string;
  size?: number;
}) {
  return (
    <span className={cn("inline-flex items-center gap-2 font-semibold", className)}>
      <LogoMark cutout={cutout} size={size} />
      <span>Stark</span>
    </span>
  );
}
