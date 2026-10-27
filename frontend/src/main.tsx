import { StrictMode, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import type { Role } from './api'
import { AuthCard, Notice } from './components'
import Admin from './pages/Admin'
import ForgotPassword from './pages/ForgotPassword'
import Analysis from './pages/Analysis'
import AssignmentPage from './pages/Assignment'
import Board from './pages/Board'
import Dashboard from './pages/Dashboard'
import Home, { Regulation } from './pages/Home'
import IdeaEditor from './pages/IdeaEditor'
import IdeaView from './pages/IdeaView'
import MyIdeas from './pages/MyIdeas'
import Login from './pages/Login'
import Platform from './pages/Platform'
import Register from './pages/Register'
import SetPassword from './pages/SetPassword'
import { SiteProvider, useSite } from './site'
import './index.css'

function Guard({ roles, children }: { roles?: Role[]; children: ReactNode }) {
  const { me } = useSite()
  if (!me) return <Navigate to="/login" replace />
  if (roles && !roles.includes(me.role)) return <Navigate to="/" replace />
  return <>{children}</>
}

function App() {
  const { loading, error, site } = useSite()
  if (loading) return <main className="auth"><p className="muted">Carregando…</p></main>
  if (error) {
    return (
      <AuthCard title="Ops">
        <Notice kind="error">{error}</Notice>
        {/* ?tenant= vazio limpa o hospital lembrado pela aba e volta para a plataforma */}
        <p className="auth-links"><a className="link" href="/login?tenant=">Ir para o login da plataforma</a></p>
      </AuthCard>
    )
  }
  const inTenant = Boolean(site?.tenant)
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/esqueci-senha" element={<ForgotPassword />} />
      <Route path="/cadastro" element={<Register />} />
      <Route path="/redefinir-senha" element={<SetPassword mode="reset" />} />
      <Route path="/ativar-conta" element={<SetPassword mode="activate" />} />
      <Route path="/plataforma" element={<Guard roles={['consultor']}><Platform /></Guard>} />
      {inTenant ? (
        <>
          <Route path="/" element={<Guard><Home /></Guard>} />
          <Route path="/campanhas/:id" element={<Guard><Home /></Guard>} />
          <Route path="/campanhas/:id/regulamento" element={<Guard><Regulation /></Guard>} />
          <Route path="/ideias/nova" element={<Guard><IdeaEditor /></Guard>} />
          <Route path="/ideias/:id/editar" element={<Guard><IdeaEditor /></Guard>} />
          <Route path="/ideias/:id" element={<Guard><IdeaView /></Guard>} />
          <Route path="/minhas-ideias" element={<Guard><MyIdeas /></Guard>} />
          <Route path="/analise" element={<Guard roles={['administrador', 'consultor', 'membro_comite']}><Analysis /></Guard>} />
          <Route path="/analise/:id" element={<Guard roles={['administrador', 'consultor', 'membro_comite']}><AssignmentPage /></Guard>} />
          <Route path="/classificacao" element={<Guard roles={['administrador', 'consultor', 'gestor']}><Board /></Guard>} />
          <Route path="/dashboard" element={<Guard roles={['administrador', 'consultor']}><Dashboard /></Guard>} />
          <Route path="/administracao" element={<Guard roles={['administrador', 'consultor']}><Admin /></Guard>} />
        </>
      ) : (
        <Route path="/" element={<Guard roles={['consultor']}><Navigate to="/plataforma" replace /></Guard>} />
      )}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <SiteProvider><App /></SiteProvider>
    </BrowserRouter>
  </StrictMode>,
)
