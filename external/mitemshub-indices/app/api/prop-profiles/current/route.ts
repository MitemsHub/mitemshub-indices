import { NextResponse } from "next/server";
import { ZodError } from "zod";
import { propProfileRequestSchema } from "../../../../src/lib/contracts";
import {
  getCurrentPropProfile,
  getCurrentPropProfileForRequest,
} from "../../../../src/lib/engine-bridge";

export async function GET(_request: Request) {
  const payload = await getCurrentPropProfile();
  return NextResponse.json(payload);
}

export async function POST(request: Request) {
  try {
    const body = propProfileRequestSchema.parse(await request.json());
    const payload = await getCurrentPropProfileForRequest(body);
    return NextResponse.json(payload);
  } catch (error) {
    if (error instanceof SyntaxError) {
      return NextResponse.json(
        { error: "Invalid JSON body." },
        { status: 400 },
      );
    }

    if (error instanceof ZodError) {
      return NextResponse.json(
        { error: "Invalid prop-profile payload." },
        { status: 400 },
      );
    }

    throw error;
  }
}
