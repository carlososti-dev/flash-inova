import { Layout } from '../components'
import { useSite } from '../site'

export default function Home() {
  const { me, site } = useSite()
  return (
    <Layout>
      <section className="card">
        <h1>Olá, {me?.name}</h1>
        <p className="muted">
          Você entrou em <strong>{site?.tenant?.name ?? 'Flash Inova'}</strong> como {me?.role_label}.
        </p>
        <p className="muted">A página da campanha (banner, período de inscrição, vídeo e temáticas) chega na Fatia 3.</p>
      </section>
    </Layout>
  )
}

export function Soon({ title, slice }: { title: string; slice: string }) {
  return (
    <Layout>
      <section className="card"><h1>{title}</h1><p className="muted">Esta área chega na {slice}.</p></section>
    </Layout>
  )
}
