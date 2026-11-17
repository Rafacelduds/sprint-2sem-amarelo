export type HealthResponse = {
  status: 'ok'
  service: string
}

const apiUrl = import.meta.env.VITE_API_URL ?? '/api'

export async function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const response = await fetch(`${apiUrl}/health`, { signal })
  if (!response.ok) {
    throw new Error(`API respondeu com status ${response.status}`)
  }
  return response.json() as Promise<HealthResponse>
}

