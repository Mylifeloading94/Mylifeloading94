/*
  Warnings:

  - You are about to drop the column `isLate` on the `Post` table. All the data in the column will be lost.

*/
-- RedefineTables
PRAGMA defer_foreign_keys=ON;
PRAGMA foreign_keys=OFF;
CREATE TABLE "new_Post" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "authorId" TEXT NOT NULL,
    "imageUrl" TEXT NOT NULL,
    "backImageUrl" TEXT,
    "caption" TEXT NOT NULL DEFAULT '',
    "isMoment" BOOLEAN NOT NULL DEFAULT false,
    "momentDate" TEXT,
    "closeFriendsOnly" BOOLEAN NOT NULL DEFAULT false,
    "locationName" TEXT,
    "locationLat" REAL,
    "locationLng" REAL,
    "locationVerified" BOOLEAN NOT NULL DEFAULT false,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "Post_authorId_fkey" FOREIGN KEY ("authorId") REFERENCES "User" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);
INSERT INTO "new_Post" ("authorId", "backImageUrl", "caption", "closeFriendsOnly", "createdAt", "id", "imageUrl", "isMoment", "locationLat", "locationLng", "locationName", "locationVerified", "momentDate") SELECT "authorId", "backImageUrl", "caption", "closeFriendsOnly", "createdAt", "id", "imageUrl", "isMoment", "locationLat", "locationLng", "locationName", "locationVerified", "momentDate" FROM "Post";
DROP TABLE "Post";
ALTER TABLE "new_Post" RENAME TO "Post";
CREATE INDEX "Post_authorId_createdAt_idx" ON "Post"("authorId", "createdAt");
CREATE INDEX "Post_momentDate_idx" ON "Post"("momentDate");
PRAGMA foreign_keys=ON;
PRAGMA defer_foreign_keys=OFF;
