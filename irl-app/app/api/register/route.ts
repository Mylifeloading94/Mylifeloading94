import { NextResponse } from "next/server";
import bcrypt from "bcryptjs";
import { z } from "zod";
import { prisma } from "@/lib/prisma";

const registerSchema = z.object({
  name: z.string().min(1).max(60),
  username: z
    .string()
    .min(3)
    .max(24)
    .regex(/^[a-z0-9_.]+$/, "Lowercase letters, numbers, dots and underscores only"),
  email: z.string().email(),
  password: z.string().min(8).max(200),
});

export async function POST(req: Request) {
  const body = await req.json().catch(() => null);
  const parsed = registerSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json(
      { error: parsed.error.issues[0]?.message ?? "Invalid input" },
      { status: 400 }
    );
  }

  const { name, username, email, password } = parsed.data;
  const normalizedUsername = username.toLowerCase();
  const normalizedEmail = email.toLowerCase();

  const existing = await prisma.user.findFirst({
    where: { OR: [{ email: normalizedEmail }, { username: normalizedUsername }] },
  });
  if (existing) {
    return NextResponse.json(
      { error: "Username or email already taken" },
      { status: 409 }
    );
  }

  const passwordHash = await bcrypt.hash(password, 10);

  const user = await prisma.user.create({
    data: {
      name,
      username: normalizedUsername,
      email: normalizedEmail,
      passwordHash,
    },
    select: { id: true, username: true, name: true, email: true },
  });

  return NextResponse.json({ user }, { status: 201 });
}
