"use client";

import { useRouter } from "next/navigation";
import { useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { ImagePlus, MapPin, BadgeCheck, Lock } from "lucide-react";
import { uploadImage } from "@/lib/upload";

export default function CreatePostPage() {
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [caption, setCaption] = useState("");
  const [closeFriendsOnly, setCloseFriendsOnly] = useState(false);
  const [locationName, setLocationName] = useState("");
  const [coords, setCoords] = useState<{ lat: number; lng: number } | null>(null);
  const [locating, setLocating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function onFileChange(e: ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (!f) return;
    setFile(f);
    setPreview(URL.createObjectURL(f));
  }

  function useMyLocation() {
    if (!navigator.geolocation) {
      setError("Location isn't available in this browser");
      return;
    }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setCoords({ lat: pos.coords.latitude, lng: pos.coords.longitude });
        setLocating(false);
      },
      () => {
        setError("Couldn't verify your location — you can still type a place name.");
        setLocating(false);
      },
      { enableHighAccuracy: true, timeout: 8000 }
    );
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!file) {
      setError("Choose a photo first");
      return;
    }
    setSubmitting(true);
    try {
      const imageUrl = await uploadImage(file, "posts");
      const res = await fetch("/api/posts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          imageUrl,
          caption,
          closeFriendsOnly,
          locationName: locationName.trim() || undefined,
          locationLat: coords?.lat,
          locationLng: coords?.lng,
          locationVerified: Boolean(coords),
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error ?? "Failed to post");
      }
      router.push("/");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto max-w-lg px-4 py-6">
      <h1 className="mb-5 text-xl font-bold">New post</h1>
      <form onSubmit={onSubmit} className="space-y-4">
        <input
          ref={fileInputRef}
          type="file"
          accept="image/jpeg,image/png,image/webp,image/gif"
          className="hidden"
          onChange={onFileChange}
        />
        {preview ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={preview}
            alt="Preview"
            onClick={() => fileInputRef.current?.click()}
            className="max-h-[500px] w-full cursor-pointer rounded-2xl object-cover"
          />
        ) : (
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="flex aspect-square w-full flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-border text-muted hover:border-brand hover:text-brand"
          >
            <ImagePlus size={36} />
            <span className="text-sm font-medium">Choose a photo</span>
          </button>
        )}

        <textarea
          value={caption}
          onChange={(e) => setCaption(e.target.value)}
          placeholder="Write a caption…"
          rows={3}
          className="w-full resize-none rounded-xl border border-border bg-transparent px-3 py-2 text-sm outline-none focus:border-brand"
        />

        <div className="rounded-xl border border-border p-3">
          <div className="flex items-center gap-2">
            <MapPin size={16} className="text-muted" />
            <input
              value={locationName}
              onChange={(e) => setLocationName(e.target.value)}
              placeholder="Add a location"
              className="flex-1 bg-transparent text-sm outline-none"
            />
            {coords && <BadgeCheck size={16} className="text-brand" />}
          </div>
          <button
            type="button"
            onClick={useMyLocation}
            disabled={locating || Boolean(coords)}
            className="mt-2 text-xs font-medium text-brand disabled:opacity-50"
          >
            {coords ? "Location verified" : locating ? "Locating…" : "Verify with my current location"}
          </button>
        </div>

        <label className="flex items-center justify-between rounded-xl border border-border p-3 text-sm">
          <span className="flex items-center gap-2">
            <Lock size={16} className="text-muted" /> Close friends only
          </span>
          <input
            type="checkbox"
            checked={closeFriendsOnly}
            onChange={(e) => setCloseFriendsOnly(e.target.checked)}
            className="h-4 w-4 accent-[var(--brand)]"
          />
        </label>

        {error && <p className="text-sm text-red-500">{error}</p>}

        <button
          disabled={submitting}
          className="w-full rounded-xl bg-brand py-2.5 text-sm font-semibold text-white hover:bg-brand-dark disabled:opacity-60"
        >
          {submitting ? "Posting…" : "Share"}
        </button>
      </form>
    </div>
  );
}
