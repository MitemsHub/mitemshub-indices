import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const PROTECTED_ROUTES = [
  "/api/calls/run",
  "/api/calls/guardian",
  "/api/calls/prepared",
  "/api/execution/submit",
  "/api/execution/close",
  "/api/intelligence",
];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const isProtected = PROTECTED_ROUTES.some((route) => pathname.startsWith(route));

  if (isProtected) {
    const authHeader = request.headers.get("x-api-key");
    const expectedKey = process.env.SYNTHETIC_API_KEY;

    if (!expectedKey) {
      return NextResponse.next();
    }

    if (!authHeader || authHeader !== expectedKey) {
      return NextResponse.json(
        { error: "Unauthorized. Provide x-api-key header." },
        { status: 401 },
      );
    }
  }

  return NextResponse.next();
}

export const config = {
  matcher: "/api/:path*",
};