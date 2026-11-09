/** Folio's mark: two stacked pages (your files, in one place) carrying a small knowledge graph.
 * ``animated`` plays the loading animation (pages settle, the graph draws itself). */
import { useId } from "react";

export function Logo({ size = 28, animated = false }: { size?: number; animated?: boolean }) {
  const id = useId().replace(/:/g, "");
  return (
    <svg className={`logo ${animated ? "logo-animated" : ""}`} width={size} height={size} viewBox="0 0 1024 1024" aria-hidden="true">
      <defs>
        <linearGradient id={`${id}bg`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#3D63F5" />
          <stop offset="0.55" stopColor="#7C5CF6" />
          <stop offset="1" stopColor="#EC4F9C" />
        </linearGradient>
        <linearGradient id={`${id}sh`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#FFFFFF" stopOpacity="0.28" />
          <stop offset="0.5" stopColor="#FFFFFF" stopOpacity="0" />
        </linearGradient>
      </defs>
      <rect className="logo-tile" x="64" y="64" width="896" height="896" rx="216" fill={`url(#${id}bg)`} />
      <rect x="64" y="64" width="896" height="896" rx="216" fill={`url(#${id}sh)`} />
      <rect className="logo-back" x="372" y="236" width="400" height="520" rx="72" fill="#FFFFFF" fillOpacity="0.38" transform="rotate(9 572 496)" />
      <rect className="logo-front" x="268" y="276" width="400" height="520" rx="72" fill="#FFFFFF" />
      <g className="logo-edges" stroke="#B9AEF8" strokeWidth="22" strokeLinecap="round">
        <line x1="378" y1="440" x2="548" y2="392" pathLength={1} />
        <line x1="378" y1="440" x2="520" y2="620" pathLength={1} />
        <line x1="548" y1="392" x2="520" y2="620" pathLength={1} />
      </g>
      <circle className="logo-node n1" cx="378" cy="440" r="46" fill="#3D63F5" />
      <circle className="logo-node n2" cx="548" cy="392" r="40" fill="#7C5CF6" />
      <circle className="logo-node n3" cx="520" cy="620" r="50" fill="#EC4F9C" />
    </svg>
  );
}
