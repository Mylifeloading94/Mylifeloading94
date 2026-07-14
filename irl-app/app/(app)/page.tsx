import { redirect } from "next/navigation";
import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";
import { postCardInclude, serializePost } from "@/lib/posts";
import { feedWhereFor } from "@/lib/feed";
import { Feed } from "@/components/Feed";
import { StoryBar } from "@/components/StoryBar";

const PAGE_SIZE = 10;

export default async function HomePage() {
  const session = await auth();
  if (!session?.user?.id) redirect("/login");
  const userId = session.user.id;

  const where = await feedWhereFor(userId);
  const posts = await prisma.post.findMany({
    where,
    orderBy: { createdAt: "desc" },
    take: PAGE_SIZE + 1,
    include: postCardInclude,
  });

  const hasMore = posts.length > PAGE_SIZE;
  const page = posts.slice(0, PAGE_SIZE);

  return (
    <div className="mx-auto max-w-xl px-3 pt-4">
      <StoryBar />
      <Feed
        initialPosts={page.map((p) => serializePost(p, userId))}
        initialCursor={hasMore ? page[page.length - 1]?.id ?? null : null}
      />
    </div>
  );
}
