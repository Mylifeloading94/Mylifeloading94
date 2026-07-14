"use client";

import { useEffect, useRef, useState } from "react";
import { Camera, RotateCcw, Upload } from "lucide-react";
import { uploadImage } from "@/lib/upload";

type Stage = "start" | "camera-back" | "camera-front" | "review" | "manual";

export function MomentCapture({ onPosted }: { onPosted: () => void }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const backInputRef = useRef<HTMLInputElement>(null);
  const frontInputRef = useRef<HTMLInputElement>(null);

  const [stage, setStage] = useState<Stage>("start");
  const [backFile, setBackFile] = useState<File | null>(null);
  const [frontFile, setFrontFile] = useState<File | null>(null);
  const [backPreview, setBackPreview] = useState<string | null>(null);
  const [frontPreview, setFrontPreview] = useState<string | null>(null);
  const [caption, setCaption] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    return () => stopStream();
  }, []);

  function stopStream() {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }

  async function startCamera(facing: "environment" | "user", nextStage: Stage) {
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: facing },
        audio: false,
      });
      streamRef.current = stream;
      setStage(nextStage);
      requestAnimationFrame(() => {
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          videoRef.current.play().catch(() => {});
        }
      });
    } catch {
      setError("Couldn't access your camera — upload two photos instead.");
      setStage("manual");
    }
  }

  function capture(which: "back" | "front") {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas) return;
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext("2d");
    ctx?.drawImage(video, 0, 0);
    canvas.toBlob((blob) => {
      if (!blob) return;
      const file = new File([blob], `${which}.jpg`, { type: "image/jpeg" });
      const url = URL.createObjectURL(blob);
      if (which === "back") {
        setBackFile(file);
        setBackPreview(url);
        stopStream();
        startCamera("user", "camera-front");
      } else {
        setFrontFile(file);
        setFrontPreview(url);
        stopStream();
        setStage("review");
      }
    }, "image/jpeg", 0.9);
  }

  function onManualFile(which: "back" | "front", file: File | undefined) {
    if (!file) return;
    const url = URL.createObjectURL(file);
    if (which === "back") {
      setBackFile(file);
      setBackPreview(url);
    } else {
      setFrontFile(file);
      setFrontPreview(url);
    }
  }

  async function submit() {
    if (!backFile || !frontFile) {
      setError("Add both photos first");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const [imageUrl, backImageUrl] = await Promise.all([
        uploadImage(backFile, "moments"),
        uploadImage(frontFile, "moments"),
      ]);
      const res = await fetch("/api/moments", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ imageUrl, backImageUrl, caption }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error ?? "Failed to post Moment");
      }
      onPosted();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  }

  if (stage === "start") {
    return (
      <div className="flex flex-col items-center gap-3 rounded-2xl border border-border p-8 text-center">
        <Camera size={40} className="text-brand" />
        <p className="font-semibold">Today&apos;s Moment</p>
        <p className="max-w-xs text-sm text-muted">
          Capture what&apos;s really happening — back camera, then a front-camera reaction. One shot a
          day.
        </p>
        <div className="flex gap-2">
          <button
            onClick={() => startCamera("environment", "camera-back")}
            className="rounded-full bg-brand px-5 py-2 text-sm font-semibold text-white hover:bg-brand-dark"
          >
            Open camera
          </button>
          <button
            onClick={() => setStage("manual")}
            className="rounded-full border border-border px-5 py-2 text-sm font-semibold hover:bg-black/5 dark:hover:bg-white/10"
          >
            Upload photos
          </button>
        </div>
        {error && <p className="text-sm text-red-500">{error}</p>}
      </div>
    );
  }

  if (stage === "camera-back" || stage === "camera-front") {
    return (
      <div className="flex flex-col items-center gap-3">
        <p className="text-sm font-medium text-muted">
          {stage === "camera-back" ? "1. Capture what's in front of you" : "2. Now your reaction"}
        </p>
        <div className="relative aspect-[3/4] w-full max-w-sm overflow-hidden rounded-2xl bg-black">
          <video ref={videoRef} muted playsInline className="h-full w-full object-cover" />
        </div>
        <button
          onClick={() => capture(stage === "camera-back" ? "back" : "front")}
          className="flex h-16 w-16 items-center justify-center rounded-full border-4 border-border"
        >
          <span className="h-12 w-12 rounded-full bg-brand" />
        </button>
        <canvas ref={canvasRef} className="hidden" />
      </div>
    );
  }

  if (stage === "manual") {
    return (
      <div className="space-y-3 rounded-2xl border border-border p-5">
        <p className="text-sm font-medium">Upload your Moment</p>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <input
              ref={backInputRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => onManualFile("back", e.target.files?.[0])}
            />
            <button
              type="button"
              onClick={() => backInputRef.current?.click()}
              className="flex aspect-square w-full items-center justify-center overflow-hidden rounded-xl border-2 border-dashed border-border"
            >
              {backPreview ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={backPreview} alt="" className="h-full w-full object-cover" />
              ) : (
                <Upload size={22} className="text-muted" />
              )}
            </button>
            <p className="mt-1 text-center text-xs text-muted">Main photo</p>
          </div>
          <div>
            <input
              ref={frontInputRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => onManualFile("front", e.target.files?.[0])}
            />
            <button
              type="button"
              onClick={() => frontInputRef.current?.click()}
              className="flex aspect-square w-full items-center justify-center overflow-hidden rounded-xl border-2 border-dashed border-border"
            >
              {frontPreview ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={frontPreview} alt="" className="h-full w-full object-cover" />
              ) : (
                <Upload size={22} className="text-muted" />
              )}
            </button>
            <p className="mt-1 text-center text-xs text-muted">Reaction photo</p>
          </div>
        </div>
        {backFile && frontFile && (
          <button
            onClick={() => setStage("review")}
            className="w-full rounded-lg bg-brand py-2 text-sm font-semibold text-white hover:bg-brand-dark"
          >
            Continue
          </button>
        )}
        {error && <p className="text-sm text-red-500">{error}</p>}
      </div>
    );
  }

  // review
  return (
    <div className="space-y-3">
      <div className="relative mx-auto aspect-[3/4] w-full max-w-sm overflow-hidden rounded-2xl bg-black">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        {backPreview && <img src={backPreview} alt="" className="h-full w-full object-cover" />}
        <div className="absolute left-3 top-3 h-24 w-16 overflow-hidden rounded-lg border-2 border-white shadow-lg">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          {frontPreview && <img src={frontPreview} alt="" className="h-full w-full object-cover" />}
        </div>
      </div>
      <textarea
        value={caption}
        onChange={(e) => setCaption(e.target.value)}
        placeholder="Add a caption…"
        rows={2}
        className="w-full resize-none rounded-xl border border-border bg-transparent px-3 py-2 text-sm outline-none focus:border-brand"
      />
      <div className="flex gap-2">
        <button
          onClick={() => {
            setBackFile(null);
            setFrontFile(null);
            setBackPreview(null);
            setFrontPreview(null);
            setStage("start");
          }}
          className="flex items-center gap-1.5 rounded-full border border-border px-4 py-2 text-sm font-medium hover:bg-black/5 dark:hover:bg-white/10"
        >
          <RotateCcw size={14} /> Retake
        </button>
        <button
          onClick={submit}
          disabled={submitting}
          className="flex-1 rounded-full bg-brand py-2 text-sm font-semibold text-white hover:bg-brand-dark disabled:opacity-60"
        >
          {submitting ? "Posting…" : "Share today's Moment"}
        </button>
      </div>
      {error && <p className="text-sm text-red-500">{error}</p>}
    </div>
  );
}
