import { useEffect, useRef, useState } from "react";
export interface Coordinates {
  latitude: number;
  longitude: number;
}
export function useDeviceLocation() {
  const generation = useRef(0);
  const [pending, setPending] = useState(false),
    [error, setError] = useState("");
  useEffect(
    () => () => {
      generation.current += 1;
    },
    [],
  );
  function cancel() {
    generation.current += 1;
    setPending(false);
    setError("");
  }
  function locate(accept: (coordinates: Coordinates) => void) {
    const request = ++generation.current;
    if (!navigator.geolocation) {
      setError(
        "Location is unavailable in this browser. Choose a place manually.",
      );
      return;
    }
    setPending(true);
    setError("");
    navigator.geolocation.getCurrentPosition(
      (position) => {
        if (request !== generation.current) return;
        setPending(false);
        accept({
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
        });
      },
      (failure) => {
        if (request !== generation.current) return;
        setPending(false);
        setError(
          failure.code === 1
            ? "Location permission was denied. Choose a city or area below."
            : failure.code === 3
              ? "Finding your location timed out. Try again or choose a place manually."
              : "Your location could not be found. Choose a place manually.",
        );
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 },
    );
  }
  return { pending, error, locate, cancel };
}
