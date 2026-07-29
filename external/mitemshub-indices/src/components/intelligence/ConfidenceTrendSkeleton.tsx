"use client"

import { SkeletonBar } from "../ui/skeleton"

export function ConfidenceTrendSkeleton() {
  return (
    <div className="intelligence-panel surface rounded-[1.5rem] p-4" aria-hidden="true">
      <div className="flex items-center justify-between">
        <SkeletonBar width="8rem" height="0.75rem" />
        <SkeletonBar width="5rem" height="1.5rem" className="rounded-full" />
      </div>

      {/* 3 metric cards */}
      <div className="mt-4 grid gap-4 md:grid-cols-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="info-card rounded-[1rem] p-4">
            <SkeletonBar width="3rem" height="0.5rem" />
            <SkeletonBar width="4rem" height="1rem" className="mt-2" />
            <SkeletonBar width="5rem" height="0.5rem" className="mt-1.5" />
          </div>
        ))}
      </div>

      {/* Chart skeleton */}
      <div className="mt-4">
        <SkeletonBar width="7rem" height="0.5rem" className="mb-3" />
        <div className="h-64 relative rounded-lg bg-gray-50 border border-gray-100 flex items-end p-4">
          <SkeletonBar width="100%" height="60%" className="rounded-t" />
        </div>
      </div>

      {/* Recent readings */}
      <div className="mt-4">
        <SkeletonBar width="7rem" height="0.5rem" className="mb-3" />
        <div className="space-y-2 max-h-48">
          {[1, 2, 3].map((i) => (
            <div key={i} className="flex items-center justify-between p-3 rounded-lg bg-gray-50 border border-gray-100">
              <div className="flex items-center gap-3">
                <SkeletonBar width="1.5rem" height="0.875rem" />
                <div>
                  <SkeletonBar width="5rem" height="0.875rem" />
                  <SkeletonBar width="4rem" height="0.5rem" className="mt-1" />
                </div>
              </div>
              <SkeletonBar width="3rem" height="0.875rem" />
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
