"use client"

import { SkeletonBar } from "../ui/skeleton"

export function RiskAssessmentSkeleton() {
  return (
    <section className="intelligence-panel surface rounded-[1.5rem] p-4" aria-hidden="true">
      <div className="flex items-center justify-between">
        <SkeletonBar width="7rem" height="0.75rem" />
        <SkeletonBar width="4rem" height="1.5rem" className="rounded-full" />
      </div>

      {/* 4 metric cards */}
      <div className="mt-4 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="info-card rounded-[1rem] p-4">
            <SkeletonBar width="5rem" height="0.5rem" />
            <SkeletonBar width="3rem" height="1.25rem" className="mt-2" />
            <SkeletonBar width="4rem" height="0.5rem" className="mt-1.5" />
            <SkeletonBar width="2rem" height="1rem" className="rounded-full mt-2" />
          </div>
        ))}
      </div>

      {/* 2 detail cards */}
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        {[1, 2].map((i) => (
          <div key={i} className="info-card rounded-[1rem] p-4">
            <SkeletonBar width="4rem" height="0.5rem" />
            <SkeletonBar width="3rem" height="1rem" className="mt-2" />
            <SkeletonBar width="5rem" height="0.5rem" className="mt-1.5" />
          </div>
        ))}
      </div>

      {/* Parameters block */}
      <div className="mt-4 p-4 rounded-lg bg-gray-50 border border-gray-200">
        <SkeletonBar width="5rem" height="0.5rem" className="mb-3" />
        <div className="grid gap-2 md:grid-cols-3">
          {[1, 2, 3].map((i) => (
            <div key={i}>
              <SkeletonBar width="4rem" height="0.5rem" />
              <SkeletonBar width="3rem" height="0.875rem" className="mt-1" />
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
