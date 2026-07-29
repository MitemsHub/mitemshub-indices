"use client"

import { SkeletonBar } from "../ui/skeleton"

export function ThesisInvalidationSkeleton() {
  return (
    <section className="intelligence-panel surface rounded-[1.5rem] p-4" aria-hidden="true">
      <div className="flex items-center justify-between">
        <SkeletonBar width="7rem" height="0.75rem" />
        <SkeletonBar width="6rem" height="1.5rem" className="rounded-full" />
      </div>

      {/* 3 detail cards */}
      <div className="mt-4 grid gap-4 md:grid-cols-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="info-card rounded-[1rem] p-4">
            <SkeletonBar width="5rem" height="0.5rem" />
            <SkeletonBar width="4rem" height="1rem" className="mt-2" />
            <SkeletonBar width="6rem" height="0.5rem" className="mt-1.5" />
          </div>
        ))}
      </div>

      {/* Invalidation reason block */}
      <div className="mt-4 p-4 rounded-lg bg-red-50 border border-red-200">
        <div className="flex items-start gap-3">
          <SkeletonBar width="2rem" height="2rem" className="rounded-full flex-shrink-0" />
          <div className="flex-1">
            <SkeletonBar width="5rem" height="0.625rem" />
            <SkeletonBar width="100%" height="0.875rem" className="mt-2" />
            <SkeletonBar width="70%" height="0.875rem" className="mt-1.5" />
          </div>
        </div>
      </div>

      {/* Triggers */}
      <div className="mt-4">
        <SkeletonBar width="7rem" height="0.5rem" className="mb-3" />
        <div className="space-y-2">
          {[1, 2].map((i) => (
            <div key={i} className="flex items-center gap-3 p-3 rounded-lg bg-red-50 border border-red-200">
              <SkeletonBar width="1.5rem" height="1.5rem" className="rounded-full flex-shrink-0" />
              <SkeletonBar width="80%" height="0.875rem" />
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
