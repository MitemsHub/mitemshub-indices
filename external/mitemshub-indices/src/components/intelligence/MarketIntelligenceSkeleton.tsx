"use client"

import { SkeletonBar } from "../ui/skeleton"

export function MarketIntelligenceSkeleton() {
  return (
    <div className="intelligence-panel surface rounded-[1.5rem]" aria-hidden="true">
      <div className="h-[3px] w-full rounded-t-[1.5rem] bg-transparent" />
      <div className="p-3 md:p-4">
        {/* Header: title + regime chip */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <SkeletonBar width="8rem" height="0.75rem" />
          </div>
          <SkeletonBar width="4rem" height="1.5rem" className="rounded-full" />
        </div>

        {/* 4 metric cards */}
        <div className="mt-3 md:mt-4 grid grid-cols-2 gap-2 md:gap-3 lg:gap-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="info-card rounded-xl md:rounded-[1.5rem] p-3 md:p-4 lg:p-5">
              <SkeletonBar width="5rem" height="0.625rem" />
              <SkeletonBar width="4rem" height="1.25rem" className="mt-2" />
              <SkeletonBar width="3rem" height="0.625rem" className="mt-1.5" />
            </div>
          ))}
        </div>

        {/* 3 detail cards */}
        <div className="mt-3 md:mt-4 grid gap-2 md:gap-3 lg:grid-cols-3 md:grid-cols-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="info-card rounded-xl md:rounded-[1.5rem] p-3 md:p-4 lg:p-5">
              <SkeletonBar width="6rem" height="0.625rem" />
              <div className="mt-2 md:mt-4 space-y-3">
                {[1, 2, 3].map((j) => (
                  <div key={j}>
                    <SkeletonBar width="3rem" height="0.5rem" />
                    <SkeletonBar width="4rem" height="0.875rem" className="mt-1" />
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
