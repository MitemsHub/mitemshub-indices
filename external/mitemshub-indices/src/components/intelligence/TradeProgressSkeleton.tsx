"use client"

import { SkeletonBar } from "../ui/skeleton"

export function TradeProgressSkeleton() {
  return (
    <section className="intelligence-panel surface rounded-[1.5rem] p-4" aria-hidden="true">
      <div className="flex items-center justify-between">
        <SkeletonBar width="8rem" height="0.75rem" />
        <SkeletonBar width="4rem" height="1.25rem" className="rounded-full" />
      </div>

      <div className="mt-4">
        <div className="relative">
          <div className="absolute left-4 top-0 bottom-0 w-px bg-gray-200" />
          <div className="space-y-4 ml-4">
            {[1, 2, 3].map((i) => (
              <div key={i} className="relative flex gap-3">
                <div className="flex-shrink-0 w-3 h-3 rounded-full border-2 border-gray-200 bg-white" />
                <div className="flex-1 min-w-0">
                  <div className="p-3 rounded-lg border border-gray-200 bg-gray-50">
                    <div className="flex items-center gap-2">
                      <SkeletonBar width="6rem" height="0.875rem" />
                      <SkeletonBar width="3rem" height="1rem" className="rounded-full" />
                    </div>
                    <SkeletonBar width="8rem" height="0.625rem" className="mt-2" />
                    <div className="mt-2 flex gap-3">
                      <SkeletonBar width="4rem" height="0.5rem" />
                      <SkeletonBar width="5rem" height="0.5rem" />
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}
