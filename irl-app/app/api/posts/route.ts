import { NextResponse } from "next/server";
import { z } from "zod";
import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";
import { postCardInclude, serializePost } from "@/lib/posts";

const createPostSchema = z.object({
  imageUrl: z.string().min(1),
  caption: z.string().max(2000).default(""),
  closeFriendsOnly: z.boolean().default(false),
  locationName: z.string().max(120).optional(),
  locationLat: z.number().optional(),
  locationLng: z.number().optional(),
  locationVerified: z.boolean().default(false),
});

export async function POST(req: Request) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const parsed = createPostSchema.safeParse(await req.json().catch(() => null));
  if (!parsed.success) {
    return NextResponse.json(
      { error: parsed.error.issues[0]?.message ?? "Invalid input" },
      { status: 400 }
    );
  }

  const post = await prisma.post.create({
    data: {
      authorId: session.user.id,
      imageUrl: parsed.data.imageUrl,
      caption: parsed.data.caption,
      closeFriendsOnly: parsed.data.closeFriendsOnly,
      locationName: parsed.data.locationName,
      locationLat: parsed.data.locationLat,
      locationLng: parsed.data.locationLng,
      locationVerified: parsed.data.locationVerified,
    },
    include: postCardInclude,
  });

  return NextResponse.json({ post: serializePost(post, session.user.id) }, { status: 201 });
}
