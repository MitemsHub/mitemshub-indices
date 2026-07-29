"use client"

import { SkeletonBar } from "../ui/skeleton"

export function AlternativeScenarioSkeleton() {
  return (
    <div className="intelligence-panel surface rounded-[1.5rem] p-3 md:p-4" aria-hidden="true">
      <div className="flex items-center justify-between">
        <SkeletonBar width="8rem" height="0.75rem" />
        <SkeletonBar width="5rem" height="1.5rem" className="rounded-full" />
      </div>

      <div className="mt-3 md:mt-4 space-y-3">
        {/* Scenario block */}
        <div className="p-3 md:p-4 rounded-lg bg-gray-50 border border-gray-200">
          <SkeletonBar width="4rem" height="0.5rem" className="mb-2" />
          <SkeletonBar width="100%" height="0.875rem" />
        </div>
        {/* Description block */}
        <div className="p-3 md:p-4 rounded-lg bg-blue-50 border border-blue-200">
          <SkeletonBar width="6rem" height="0.5rem" className="mb-2" />
          <SkeletonBar width="90%" height="0.875rem" />
          <SkeletonBar width="60%" height="0.875rem" className="mt-1.5" />
        </div>
        {/* What would change */}
        <div className="p-3 md:p-4 rounded-lg bg-amber-50 border border-amber-200">
          <SkeletonBar width="8rem" height="0.5rem" className="mb-2" />
          <SkeletonBar width="85%" height="0.875rem" />
        </div>
        {/* Probability bar */}
        <div className="p-3 md:p-4 rounded-lg bg-blue-50 border border-blue-200">
          <SkeletonBar width="7rem" height="0.5rem" className="mb-2" />
          <SkeletonBar width="100%" height="0.75rem" className="rounded-full" />
          <SkeletonBar width="5rem" height="0.625rem" className="mt-2" />
        </div>
      </div>
    </div>
  )
}
