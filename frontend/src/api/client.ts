export interface PlatformStatus {
  name: string;
  version: string;
  sprint: number;
  stage: string;
}
export async function getPlatformStatus(): Promise<PlatformStatus> {
  const response = await fetch("/api/v1/status", {
    signal: AbortSignal.timeout(5000),
  });
  if (!response.ok)
    throw new Error("Unable to reach the platform. Please try again.");
  return response.json() as Promise<PlatformStatus>;
}
