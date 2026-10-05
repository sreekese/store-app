import { useEffect, useRef, useState } from "react";
import { BrowserQRCodeReader, type IScannerControls } from "@zxing/browser";
export default function Scanner({
  onRead,
}: {
  onRead: (token: string) => void;
}) {
  const video = useRef<HTMLVideoElement>(null),
    [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false,
      controls: IScannerControls | undefined,
      stream: MediaStream | undefined;
    const stopStream = () =>
      stream?.getTracks().forEach((track) => track.stop());
    const start = async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: "environment" },
          audio: false,
        });
        if (cancelled) {
          stopStream();
          return;
        }
        controls = await new BrowserQRCodeReader().decodeFromStream(
          stream,
          video.current!,
          (result, _error, current) => {
            if (cancelled || !result) return;
            const token = result.getText().trim();
            if (!/^[A-Za-z0-9_-]{20,100}$/.test(token)) {
              setError(
                "This is not a coupon QR code. Try another code or paste it below.",
              );
              return;
            }
            current.stop();
            stopStream();
            onRead(token);
          },
        );
        if (cancelled) {
          controls.stop();
          stopStream();
        }
      } catch {
        stopStream();
        if (!cancelled)
          setError(
            "Camera unavailable or permission denied. Use the manual coupon code instead.",
          );
      }
    };
    void start();
    return () => {
      cancelled = true;
      controls?.stop();
      stopStream();
    };
  }, [onRead]);
  return (
    <div className="redemption-scanner">
      <video
        ref={video}
        muted
        playsInline
        aria-label="Coupon QR camera preview"
      />
      <p>Point the camera at the shopper’s QR. Scanning does not redeem it.</p>
      {error && <p role="alert">{error}</p>}
    </div>
  );
}
