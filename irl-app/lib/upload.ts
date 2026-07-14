export async function uploadImage(
  file: File,
  kind: "posts" | "moments" | "stories" | "avatars"
): Promise<string> {
  const form = new FormData();
  form.append("file", file);
  form.append("kind", kind);
  const res = await fetch("/api/upload", { method: "POST", body: form });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error ?? "Upload failed");
  }
  const data = await res.json();
  return data.url as string;
}
