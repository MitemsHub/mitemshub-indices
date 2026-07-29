"use client"

import { SkeletonBar } from "../ui/skeleton"

export function DecisionHistorySkeleton() {
  return (
    <section className="intelligence-panel surface rounded-[1.5rem] p-4" aria-hidden="true">
      <div className="flex items-center justify-between">
        <SkeletonBar width="7rem" height="0.75rem" />
        <SkeletonBar width="3rem" height="1.25rem" className="rounded-full" />
      </div>

      <div className="mt-4 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[var(--line-subtle)]">
              {["Time", "Symbol", "Call", "Confidence", "Regime", "Bias", "Status", "Price"].map((h) => (
                <th key={h} className="text-left py-2 px-3 utility-copy text-xs uppercase tracking-[0.1em]">
                  <SkeletonBar width="3rem" height="0.5rem" />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {[1, 2, 3, 4, 5].map((i) => (
              <tr key={i} className="border-b border-[var(--line-subtle)]/50">
                <td className="py-2.5 px-3"><SkeletonBar width="4rem" height="0.75rem" /></td>
                <td className="py-2.5 px-3"><SkeletonBar width="3rem" height="0.75rem" /></td>
                <td className="py-2.5 px-3"><SkeletonBar width="3rem" height="1rem" className="rounded-full" /></td>
                <td className="py-2.5 px-3"><SkeletonBar width="4rem" height="0.5rem" className="rounded-full" /></td>
                <td className="py-2.5 px-3"><SkeletonBar width="3rem" height="0.75rem" /></td>
                <td className="py-2.5 px-3"><SkeletonBar width="3rem" height="0.75rem" /></td>
                <td className="py-2.5 px-3"><SkeletonBar width="2.5rem" height="1rem" className="rounded-full" /></td>
                <td className="py-2.5 px-3"><SkeletonBar width="3rem" height="0.75rem" /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
