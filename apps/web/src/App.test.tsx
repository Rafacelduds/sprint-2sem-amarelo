import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'

describe('App', () => {
  afterEach(() => vi.restoreAllMocks())

  it('shows the API health result', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ status: 'ok', service: 'api' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    render(<App />)

    expect(screen.getByText('Consultando a API…')).toBeInTheDocument()
    expect(await screen.findByText('ok')).toBeInTheDocument()
    expect(screen.getByText('api')).toBeInTheDocument()
  })

  it('shows a readable error when the API is unavailable', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(null, { status: 503 }))

    render(<App />)

    expect(await screen.findByText(/API indisponível/)).toBeInTheDocument()
  })
})

