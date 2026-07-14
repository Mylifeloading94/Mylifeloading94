"use client";

import { useEffect } from "react";

export function MarkNotificationsRead() {
  useEffect(() => {
    fetch("/api/notifications/read-all", { method: "POST" });
  }, []);
  return null;
}
