import { useEffect, useState } from 'react'
import reactLogo from './assets/react.svg'
import viteLogo from '/vite.svg'
import { getHealth, type HealthResponse } from './api/health'
import './App.css'

type ApiState =
  | { kind: 'loading' }
  | { kind: 'ready'; health: HealthResponse }
  | { kind: 'error'; message: string }

export default function App() {
  const [apiState, setApiState] = useState<ApiState>({ kind: 'loading' })

  useEffect(() => {
    const controller = new AbortController()
    getHealth(controller.signal)
      .then((health) => setApiState({ kind: 'ready', health }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === 'AbortError') return
        setApiState({
          kind: 'error',
          message: error instanceof Error ? error.message : 'Erro desconhecido',
        })
      })
    return () => controller.abort()
  }, [])

  return (
    <main>
      <div className="logos" aria-label="React com Vite">
        <a href="https://vite.dev" target="_blank" rel="noreferrer">
          <img src={viteLogo} className="logo" alt="Vite" />
        </a>
        <a href="https://react.dev" target="_blank" rel="noreferrer">
          <img src={reactLogo} className="logo react" alt="React" />
        </a>
      </div>
      <h1>Vite + React</h1>
      <p className="subtitle">Setup mínimo da Sprint Amarelo</p>

      <section className="health-card" aria-live="polite">
        <span className={`status-dot ${apiState.kind}`} aria-hidden="true" />
        {apiState.kind === 'loading' && <p>Consultando a API…</p>}
        {apiState.kind === 'ready' && (
          <p>
            API <strong>{apiState.health.status}</strong> · serviço{' '}
            <code>{apiState.health.service}</code>
          </p>
        )}
        {apiState.kind === 'error' && <p>API indisponível: {apiState.message}</p>}
      </section>

      <p className="read-the-docs">Abra /docs na API para visualizar o Swagger.</p>
    </main>
  )
}

