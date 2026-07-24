"use client";

import React from "react";

/**
 * Reusable skeleton loading primitives for intelligence panels.
 *
 * All components use the existing `skeleton` CSS class which provides
 * the `skeletonShimmer` keyframe animation — no additional CSS needed.
 *
 * Usage:
 * ```tsx
 * import { SkeletonBar, SkeletonRow, SkeletonCard } from "../ui/skeleton";
 *
 * <SkeletonBar width="6rem" />
 * <SkeletonRow columns={[{width:"3rem"}, {width:"5rem", hide:"md"}]} />
 * <SkeletonCard rows={3} />
 * ```
 */

type SkeletonBarProps = {
  /** Width of the bar. Accepts any CSS width value. Default: "100%". */
  width?: string;
  /** Height of the bar. Default: "0.75rem" (h-3). */
  height?: string;
  /** Additional CSS classes. */
  className?: string;
};

export function SkeletonBar({
  width = "100%",
  height = "0.75rem",
  className = "",
}: SkeletonBarProps) {
  return (
    <div
      className={`skeleton rounded-full ${className}`}
      style={{ width, height }}
    />
  );
}

type ColumnDef = {
  /** Width of the skeleton bar in this column. */
  width: string;
  /** Hide this column below this breakpoint. "md" = hidden below 768px, "lg" = hidden below 1024px. */
  hide?: "md" | "lg";
};

type SkeletonRowProps = {
  /** Column definitions with optional responsive hiding. */
  columns: ColumnDef[];
  /** Additional CSS classes on the wrapper tr. */
  className?: string;
};

export function SkeletonRow({
  columns,
  className = "",
}: SkeletonRowProps) {
  return (
    <tr className={`border-b border-[var(--border)]/50 ${className}`}>
      {columns.map((col, i) => (
        <td
          key={i}
          className={`py-2.5 px-3 ${col.hide === "md" ? "hidden md:table-cell" : col.hide === "lg" ? "hidden lg:table-cell" : ""}`}
        >
          <SkeletonBar width={col.width} />
        </td>
      ))}
    </tr>
  );
}

type SkeletonCardProps = {
  /** Number of text-line placeholders inside the card. Default: 3. */
  rows?: number;
  /** Widths for each row. If not provided, alternating full/half. */
  widths?: string[];
  /** Additional CSS classes on the wrapper div. */
  className?: string;
};

const DEFAULT_CARD_WIDTHS = ["100%", "75%", "85%"];

export function SkeletonCard({
  rows = 3,
  widths,
  className = "",
}: SkeletonCardProps) {
  const rowWidths = widths || DEFAULT_CARD_WIDTHS;

  return (
    <div className={`p-4 rounded-lg bg-gray-50 border border-gray-200 ${className}`}>
      {rowWidths.slice(0, rows).map((w, i) => (
        <div key={i} className={i > 0 ? "mt-2" : ""}>
          <SkeletonBar width={w} />
        </div>
      ))}
    </div>
  );
}
