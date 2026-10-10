import { useEffect, useState } from 'react'
import { CircleCheck, CircleX, LoaderCircle, RefreshCw } from 'lucide-react'
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import './App.css'

// Static sample data, only to confirm Recharts renders
const sampleData = [
  { t: 1, value: 3 },
  { t: 2, value: 5 },
  { t: 3, value: 4 },
  { t: 4, value: 7 },
  { t: 5, value: 6 },
]

// Calls the backend; the Vite proxy forwards /api/* to FastAPI on port 8000
async function fetchHealth() {
  const res = await fetch('/api/health')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

function App() {
  const [status, setStatus] = useState('loading') // 'loading' | 'ok' | 'error'
  const [payload, setPayload] = useState(null)
  const [error, setError] = useState(null)

  function loadHealth() {
    fetchHealth()
      .then((data) => {
        setPayload(data)
        setStatus('ok')
      })
      .catch((err) => {
        setError(err.message)
        setStatus('error')
      })
  }

  function recheck() {
    setStatus('loading')
    setError(null)
    loadHealth()
  }

  // Fetch once when the page first loads
  useEffect(() => {
    loadHealth()
  }, [])

  return (
    <main className="panel">
      <h1>HCL Hackathon</h1>

      <section className="card">
        <h2>Backend status</h2>
        <p className={`status status-${status}`}>
          {status === 'loading' && <LoaderCircle className="spin" size={20} />}
          {status === 'ok' && <CircleCheck size={20} />}
          {status === 'error' && <CircleX size={20} />}
          {status === 'loading' && 'Checking…'}
          {status === 'ok' && 'Connected'}
          {status === 'error' && `Unreachable (${error})`}
        </p>
        {payload && <pre>{JSON.stringify(payload, null, 2)}</pre>}
        <button type="button" onClick={recheck}>
          <RefreshCw size={16} /> Re-check
        </button>
      </section>

      <section className="card">
        <h2>Chart check</h2>
        <div className="chart">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={sampleData}>
              <XAxis dataKey="t" />
              <YAxis />
              <Tooltip />
              <Line
                type="monotone"
                dataKey="value"
                stroke="#2563eb"
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </section>
    </main>
  )
}

export default App
