import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { listConversationsFor } from "@/lib/conversations";

export async function GET() {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const conversations = await listConversationsFor(session.user.id);
  return NextResponse.json({ conversations });
}
