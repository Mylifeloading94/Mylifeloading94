import { NextResponse } from "next/server";
import { randomUUID } from "crypto";
import { mkdir, writeFile } from "fs/promises";
import path from "path";
import { auth } from "@/auth";

const ALLOWED_TYPES: Record<string, string> = {
  "image/jpeg": "jpg",
  "image/png": "png",
  "image/webp": "webp",
  "image/gif": "gif",
};

const MAX_BYTES = 10 * 1024 * 1024; // 10MB
const ALLOWED_KINDS = new Set(["posts", "moments", "stories", "avatars"]);

export async function POST(req: Request) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const form = await req.formData();
  const file = form.get("file");
  const kindRaw = form.get("kind");
  const kind = typeof kindRaw === "string" && ALLOWED_KINDS.has(kindRaw) ? kindRaw : "posts";

  if (!(file instanceof File)) {
    return NextResponse.json({ error: "No file provided" }, { status: 400 });
  }
  const ext = ALLOWED_TYPES[file.type];
  if (!ext) {
    return NextResponse.json({ error: "Unsupported image type" }, { status: 400 });
  }
  if (file.size > MAX_BYTES) {
    return NextResponse.json({ error: "File too large (max 10MB)" }, { status: 400 });
  }

  const buffer = Buffer.from(await file.arrayBuffer());
  const dir = path.join(process.cwd(), "public", "uploads", kind);
  await mkdir(dir, { recursive: true });

  const filename = `${randomUUID()}.${ext}`;
  await writeFile(path.join(dir, filename), buffer);

  return NextResponse.json({ url: `/uploads/${kind}/${filename}` });
}
