import { NextResponse } from "next/server";
import { propProfileRequestSchema } from "../../../../src/lib/contracts";
import {
  getCurrentPropProfile,
  getCurrentPropProfileForRequest,
} from "../../../../src/lib/engine-bridge";

export async function GET() {
  const payload = await getCurrentPropProfile();
  return NextResponse.json(payload);
}

export async function POST(request: Request) {
  const body = propProfileRequestSchema.parse(await request.json());
  const payload = await getCurrentPropProfileForRequest(body);
  return NextResponse.json(payload);
}
