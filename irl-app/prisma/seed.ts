import { PrismaClient } from "@prisma/client";
import bcrypt from "bcryptjs";

const prisma = new PrismaClient();

function placeholderImage(label: string, color: string, w = 900, h = 1200) {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}">
    <rect width="100%" height="100%" fill="${color}"/>
    <text x="50%" y="50%" font-size="48" font-family="sans-serif" fill="white"
      text-anchor="middle" dominant-baseline="middle">${label}</text>
  </svg>`;
  return `data:image/svg+xml;base64,${Buffer.from(svg).toString("base64")}`;
}

function todayKey() {
  return new Date().toISOString().slice(0, 10);
}

async function main() {
  const passwordHash = await bcrypt.hash("password123", 10);

  const usersData = [
    { username: "alex", name: "Alex Rivera", bio: "Coffee, code, and long walks.", color: "#ff5252" },
    { username: "mia", name: "Mia Chen", bio: "Photographer. Always chasing golden hour.", color: "#5271ff" },
    { username: "noah", name: "Noah Bennett", bio: "Trail runner. IRL > URL.", color: "#22a06b" },
    { username: "priya", name: "Priya Patel", bio: "Cooking things that don't survive the photo.", color: "#e0a100" },
    { username: "zeke", name: "Zeke Thompson", bio: "Building small things that matter.", color: "#8e44ad" },
    { username: "sam", name: "Sam Okafor", bio: "New here — be nice.", color: "#16a3a3" },
  ];

  const users = new Map<string, { id: string; color: string }>();
  for (const u of usersData) {
    const user = await prisma.user.upsert({
      where: { username: u.username },
      update: {},
      create: {
        username: u.username,
        email: `${u.username}@irl.demo`,
        name: u.name,
        bio: u.bio,
        passwordHash,
      },
    });
    users.set(u.username, { id: user.id, color: u.color });
  }

  const follows: [string, string][] = [
    ["alex", "mia"],
    ["alex", "noah"],
    ["alex", "priya"],
    ["mia", "alex"],
    ["mia", "noah"],
    ["noah", "alex"],
    ["noah", "mia"],
    ["noah", "priya"],
    ["noah", "zeke"],
    ["priya", "alex"],
    ["priya", "mia"],
    ["zeke", "noah"],
    ["zeke", "alex"],
    ["sam", "alex"],
    ["sam", "noah"],
  ];
  for (const [a, b] of follows) {
    await prisma.follow.upsert({
      where: {
        followerId_followingId: {
          followerId: users.get(a)!.id,
          followingId: users.get(b)!.id,
        },
      },
      update: {},
      create: { followerId: users.get(a)!.id, followingId: users.get(b)!.id },
    });
  }

  await prisma.closeFriend.upsert({
    where: {
      ownerId_friendId: { ownerId: users.get("alex")!.id, friendId: users.get("mia")!.id },
    },
    update: {},
    create: { ownerId: users.get("alex")!.id, friendId: users.get("mia")!.id },
  });

  const captions: Record<string, string[]> = {
    alex: ["Shipped something small today.", "Rainy Sunday, good book."],
    mia: ["Golden hour never misses.", "Film roll #12, developed."],
    noah: ["12 miles before breakfast.", "New trail, same legs."],
    priya: ["It was supposed to be soup.", "Sunday meal prep."],
    zeke: ["Small tools, big leverage.", "Whiteboard day."],
    sam: ["First post — hi IRL."],
  };

  const posts: Record<string, string> = {};
  for (const [username, userCaptions] of Object.entries(captions)) {
    const { id, color } = users.get(username)!;
    for (let i = 0; i < userCaptions.length; i++) {
      const post = await prisma.post.create({
        data: {
          authorId: id,
          imageUrl: placeholderImage(username, color),
          caption: userCaptions[i],
          closeFriendsOnly: username === "alex" && i === 0,
          locationName: i === 0 ? "San Francisco, CA" : undefined,
          locationVerified: i === 0,
        },
      });
      posts[`${username}-${i}`] = post.id;
    }
  }

  await prisma.like.createMany({
    data: [
      { postId: posts["alex-1"], userId: users.get("mia")!.id },
      { postId: posts["alex-1"], userId: users.get("noah")!.id },
      { postId: posts["mia-0"], userId: users.get("alex")!.id },
      { postId: posts["noah-0"], userId: users.get("alex")!.id },
      { postId: posts["noah-0"], userId: users.get("priya")!.id },
    ],
  });

  await prisma.comment.createMany({
    data: [
      { postId: posts["mia-0"], authorId: users.get("alex")!.id, body: "This is unreal 📸" },
      { postId: posts["noah-0"], authorId: users.get("priya")!.id, body: "Absolute legend." },
    ],
  });

  const momentDate = todayKey();
  await prisma.post.create({
    data: {
      authorId: users.get("noah")!.id,
      imageUrl: placeholderImage("noah - view", "#22a06b"),
      backImageUrl: placeholderImage("noah - selfie", "#1c7a53", 400, 500),
      caption: "Mid-run.",
      isMoment: true,
      momentDate,
    },
  });
  await prisma.post.create({
    data: {
      authorId: users.get("priya")!.id,
      imageUrl: placeholderImage("priya - view", "#e0a100"),
      backImageUrl: placeholderImage("priya - selfie", "#a67c00", 400, 500),
      caption: "Kitchen chaos.",
      isMoment: true,
      momentDate,
    },
  });

  const expiresAt = new Date(Date.now() + 24 * 60 * 60 * 1000);
  await prisma.story.createMany({
    data: [
      { authorId: users.get("mia")!.id, imageUrl: placeholderImage("mia story", "#5271ff"), expiresAt },
      { authorId: users.get("noah")!.id, imageUrl: placeholderImage("noah story", "#22a06b"), expiresAt },
    ],
  });

  const conversation = await prisma.conversation.create({
    data: {
      participants: {
        create: [{ userId: users.get("alex")!.id }, { userId: users.get("mia")!.id }],
      },
    },
  });
  await prisma.message.createMany({
    data: [
      { conversationId: conversation.id, senderId: users.get("alex")!.id, body: "That last shot was incredible" },
      { conversationId: conversation.id, senderId: users.get("mia")!.id, body: "Thank you!! Shot on film" },
    ],
  });

  console.log("Seed complete. Demo accounts: alex / mia / noah / priya / zeke / sam");
  console.log("Password for all: password123");
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
