import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';

export default function Overview() {
  const [days, setDays] = useState(7);
  const [data, setData] = useState(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    let active = true;
    setError(false);
    const end = new Date(), start = new Date();
    start.setDate(start.getDate() - days + 1);
    const iso = d => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
    Promise.all([api.get('/leads/page?page_size=3'), api.get('/campaigns'), api.get(`/analytics/daily?start_date=${iso(start)}&end_date=${iso(end)}`)])
      .then(([leads, campaigns, stats]) => { if (active) setData({leads, campaigns, sent: stats.reduce((n,r)=>n+r.sent,0), replies: stats.reduce((n,r)=>n+r.total_replies,0)}); })
      .catch(() => { if(active) { setData(null); setError(true); } });
    return () => {active=false;};
  }, [days]);
  const cards = [
    ['Contatos encontrados', data?.leads.total, '↗ Sua base'],
    ['Campanhas criadas', data?.campaigns.length, '✦ Prospecção'],
    ['E-mails enviados', data?.sent, '↗ Campanha'],
    ['Novas respostas', data?.replies, '↗ Conversas'],
  ];
  return <main className="overview-page">
    <header className="overview-heading"><div><h1>Seu próximo negócio começa aqui.</h1><p>Sua operação de prospecção, em uma visão conectada.</p></div>
      <label className="sr-only" htmlFor="overview-period">Período dos envios e respostas</label><select id="overview-period" value={days} onChange={e=>setDays(Number(e.target.value))}><option value={7}>Últimos 7 dias</option><option value={30}>Últimos 30 dias</option><option value={90}>Últimos 90 dias</option></select>
    </header>
    {error && <p role="alert" className="overview-error">Não foi possível carregar os dados. Verifique a conexão com o servidor.</p>}
    <section className="overview-metrics" aria-label="Resumo da operação">{cards.map(([label,value,badge])=><article className="overview-card" key={label}><p>{label}</p><div><strong>{value == null ? '—' : value.toLocaleString('pt-BR')}</strong><span className="overview-badge">{badge}</span></div></article>)}</section>
    <section className="overview-columns">
      <article className="overview-panel"><header><h2>Empresas para sua próxima conversa</h2><Link to="/leads">VER TODAS ↗</Link></header>
        {data?.leads.items.length ? data.leads.items.map((lead,i)=><Link className="overview-person" to={`/leads/${lead.id}`} key={lead.id}><span className={`overview-avatar avatar-${i}`}>{(lead.name||lead.email).split(/[\s@]+/).slice(0,2).map(x=>x[0]).join('').toUpperCase()}</span><span><strong>{lead.name||lead.email}</strong><small>{lead.email}</small></span><span className="overview-badge">Ver contato ↗</span></Link>) : <div className="overview-empty"><p>{data ? 'Sua próxima oportunidade começa com uma empresa.' : 'Seus contatos aparecerão aqui.'}</p><Link to="/receita">Buscar empresas ↗</Link></div>}
      </article>
      <article className="overview-panel overview-approach"><header><h2>Sua próxima abordagem</h2><span>✦ BAZHI</span></header><div><h3>Uma boa conversa começa com contexto.</h3><p>Encontre empresas com o perfil ideal, <mark>organize seus contatos em listas</mark> e crie uma campanha para conectar sua solução às pessoas certas.</p><Link className="overview-outline" to="/campaigns/add">Criar abordagem ↗</Link></div></article>
    </section>
    <footer className="overview-footer"><span>● Sua próxima oportunidade está em movimento</span><span>Contatos e campanhas: total · Envios e respostas: período selecionado</span></footer>
  </main>;
}
