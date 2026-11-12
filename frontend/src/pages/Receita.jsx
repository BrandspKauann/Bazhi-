import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { RiSearchLine, RiBuildingLine, RiMailLine, RiPhoneLine, RiBookmarkLine, RiCheckLine, RiCloseLine, RiArrowRightLine, RiFilter3Line } from 'react-icons/ri';
import { api } from '../api';

const INITIAL = { segmentos: [], uf: '', com_email: true, telefone: '', confiabilidade: '', tipo_email: '' };
const UFS = ['AC','AL','AP','AM','BA','CE','DF','ES','GO','MA','MT','MS','MG','PA','PB','PR','PE','PI','RJ','RN','RS','RO','RR','SC','SP','SE','TO'];
const RELIABILITY = { smtp_comprovado: 'SMTP comprovado', inconclusivo: 'Inconclusivo', nao_verificado: 'Não verificado', recusado: 'Recusado / inválido' };
const fieldClass = 'mt-1.5 w-full rounded-lg border border-gray-200 bg-white px-3 py-2.5 text-sm focus:border-teal-500 focus:outline-none focus:ring-2 focus:ring-teal-100 disabled:opacity-50';
const normalize = value => (value || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
function distance(a, b) {
  let prev = Array.from({length:b.length+1}, (_,i)=>i);
  for (let i=1;i<=a.length;i++) { const next=[i]; for(let j=1;j<=b.length;j++) next[j]=Math.min(next[j-1]+1,prev[j]+1,prev[j-1]+(a[i-1]===b[j-1]?0:1)); prev=next; }
  return prev[b.length];
}
function score(item, query) {
  const q=normalize(query).trim(); if(!q) return 1;
  const name=normalize(item.nome); const hay=normalize(`${item.nome} ${item.busca} ${item.tag}`);
  if(name.includes(q)) return 100;
  if(q.split(/\s+/).every(token=>hay.includes(token))) return 75;
  if(q.length>=4 && hay.split(/\W+/).some(word=>Math.abs(word.length-q.length)<=2 && distance(word,q)<= (q.length>6?2:1))) return 35;
  return 0;
}
function Tag({children}) { return <span className="inline-block rounded-md bg-gray-100 px-2 py-1 text-xs text-gray-600">{children}</span>; }
function Reliability({value}) { return <span className={`inline-flex rounded-full px-2 py-1 text-xs font-medium ${value==='smtp_comprovado'?'bg-emerald-50 text-emerald-700':value==='inconclusivo'?'bg-amber-50 text-amber-700':value==='recusado'?'bg-red-50 text-red-700':'bg-gray-100 text-gray-500'}`}>{RELIABILITY[value] || RELIABILITY.nao_verificado}</span>; }
function phone(row) { return [[row.ddd_1,row.telefone_1],[row.ddd_2,row.telefone_2]].filter(([,n])=>n?.replace(/\D/g,'').length>=8).map(([ddd,n])=>`${ddd?`(${ddd}) `:''}${n}`).join(' · '); }

export default function Receita() {
  const [filters,setFilters]=useState(INITIAL);
  const [catalog,setCatalog]=useState([]);
  const [catalogBusy,setCatalogBusy]=useState(true);
  const [catalogError,setCatalogError]=useState('');
  const [query,setQuery]=useState('');
  const [open,setOpen]=useState(false);
  const [active,setActive]=useState(-1);
  const [result,setResult]=useState(null);
  const [selected,setSelected]=useState([]);
  const [busy,setBusy]=useState(false);
  const [saving,setSaving]=useState(false);
  const [importing,setImporting]=useState(false);
  const [error,setError]=useState('');
  const [notice,setNotice]=useState('');
  const [lists,setLists]=useState([]);
  const [listName,setListName]=useState('');
  const [importTag,setImportTag]=useState('');
  const [saveOpen,setSaveOpen]=useState(false);
  const [tab,setTab]=useState('buscar');
  const [listId,setListId]=useState(null);
  const [listTitle,setListTitle]=useState('');
  const box=useRef(null);
  const searchController=useRef(null);
  useEffect(()=>()=>searchController.current?.abort(),[]);
  const locked=busy||saving||importing;
  const suggestions=useMemo(()=>catalog.filter(item=>!filters.segmentos.includes(item.id)).map(item=>({...item,rank:score(item,query)})).filter(item=>item.rank>0).sort((a,b)=>b.rank-a.rank).slice(0,8),[catalog,filters.segmentos,query]);
  async function loadCatalog() { setCatalogBusy(true); setCatalogError(''); try { const data=await api.get('/receita/segmentos'); setCatalog(data.segmentos); } catch(e) { setCatalogError('Não foi possível carregar suas segmentações.'); } finally {setCatalogBusy(false);} }
  async function loadLists() { const data=await api.get('/receita/listas'); setLists(data.listas); }
  useEffect(()=>{loadCatalog(); loadLists().catch(()=>setError('Não foi possível carregar suas listas.'));},[]);
  useEffect(()=>{ const close=e=>{if(box.current&&!box.current.contains(e.target))setOpen(false);}; document.addEventListener('pointerdown',close);return()=>document.removeEventListener('pointerdown',close);},[]);
  function change(patch) { setFilters(prev=>({...prev,...patch})); setResult(null);setSelected([]);setListId(null);setListTitle('');setNotice('');setError('');setSaveOpen(false); }
  function choose(item) {change({segmentos:[...filters.segmentos,item.id]});setQuery('');setActive(-1);setOpen(false);}
  function handleKeys(event) {
    if(event.key==='ArrowDown') {event.preventDefault();setOpen(true);setActive(i=>Math.min(i+1,suggestions.length-1));}
    else if(event.key==='ArrowUp') {event.preventDefault();setActive(i=>Math.max(0,i-1));}
    else if(event.key==='Escape') {setOpen(false);setActive(-1);}
    else if(event.key==='Enter'&&open) {event.preventDefault();if(suggestions[active>=0?active:0])choose(suggestions[active>=0?active:0]);}
  }
  async function search(event, patch = {}) {
    event?.preventDefault(); if(locked)return;
    if(query.trim()) {setError('Escolha uma sugestão de segmentação ou limpe o texto para buscar em todos os segmentos.');return;}
    const applied = {...filters,...patch}; setFilters(applied);
    setOpen(false);setBusy(true);setError('');setNotice('');setResult(null);setSelected([]);setListId(null);setListTitle('');setSaveOpen(false);
    const controller = new AbortController(); searchController.current = controller;
    const timeout = setTimeout(()=>controller.abort(),95000);
    try {const params=new URLSearchParams(); Object.entries(applied).forEach(([key,value])=>{if(key==='segmentos')value.forEach(id=>params.append(key,id));else params.set(key,String(value));});setResult(await api.get('/receita/empresas?'+params,{signal:controller.signal}));}
    catch(e){setError(e.name==='AbortError'?'Consulta interrompida. Você pode ajustar os filtros e buscar novamente.':e.message||'Não foi possível consultar a base.');}
    finally{clearTimeout(timeout);searchController.current=null;setBusy(false);}
  }
  async function saveList(event) {
    event.preventDefault();if(!selected.length||locked)return;setSaving(true);setError('');
    try {const data=await api.post('/receita/listas',{nome:listName,cnpjs:selected,filtros:filters});setListId(data.id);setListTitle(data.nome);setResult(prev=>({...prev,rows:prev.rows.filter(row=>selected.includes(row.cnpj_basico)),has_more:false}));setNotice(`Lista “${data.nome}” salva com ${data.quantidade} empresas.`);setSaveOpen(false);setListName('');await loadLists();}
    catch(e){setError(e.message||'Não foi possível salvar a lista.');}finally{setSaving(false);}
  }
  async function openList(item) {setBusy(true);setError('');setNotice('');setTab('buscar');setResult(null);setSelected([]);setSaveOpen(false);try{const data=await api.get('/receita/listas/'+item.id);setResult(data);setFilters({...INITIAL,...data.filtros});setSelected(data.cnpjs);setListId(data.id);setListTitle(data.nome);setQuery('');}catch(e){setError(e.message);}finally{setBusy(false);}}
  async function importSelected() {if(!selected.length||locked)return;setImporting(true);setError('');setNotice('');try{const data=await api.post('/receita/importar',{cnpjs:selected,lista_id:listId,tag:importTag.trim()});setNotice(`${data.criados} contatos adicionados; ${data.atualizados} contatos existentes receberam tags; ${data.sem_email_valido} empresas sem e-mail válido; ${data.nao_encontrados} não encontradas.`);setSelected([]);}catch(e){setError(e.message||'Não foi possível adicionar os contatos.');}finally{setImporting(false);}}
  function toggle(id) {setSelected(prev=>prev.includes(id)?prev.filter(x=>x!==id):prev.length<50?[...prev,id]:prev);}
  const rows=result?.rows||[];
  const selectedItems=catalog.filter(item=>filters.segmentos.includes(item.id));
  return <div className="flex-1 min-h-0 min-w-0 w-full overflow-y-auto"><div className="mx-auto w-full min-w-0 max-w-7xl space-y-6 p-4 sm:p-6 pb-12">
    <div className="flex flex-wrap items-center justify-between gap-4"><div><div className="text-xs font-semibold uppercase tracking-widest text-teal-600 mb-2">Prospecção · Base Receita</div><h1 className="text-3xl font-semibold tracking-tight">Encontre seus próximos clientes</h1><p className="text-sm text-gray-500 mt-2">Combine seus segmentos com os canais de contato e salve listas de até 50 empresas.</p></div><span className="rounded-full border bg-white px-3 py-1.5 text-xs text-gray-500">Empresas ativas · out/2026</span></div>
    <div className="flex gap-6 border-b text-sm"><button disabled={locked} onClick={()=>setTab('buscar')} className={`pb-3 border-b-2 font-medium ${tab==='buscar'?'border-teal-600 text-teal-700':'border-transparent text-gray-500'}`}><RiSearchLine className="inline mr-2"/>Buscar empresas</button><button disabled={locked} onClick={()=>setTab('listas')} className={`pb-3 border-b-2 font-medium ${tab==='listas'?'border-teal-600 text-teal-700':'border-transparent text-gray-500'}`}><RiBookmarkLine className="inline mr-2"/>Minhas listas <span className="ml-1 rounded bg-gray-100 px-1.5">{lists.length}</span></button></div>
    {error&&<div role="alert" className="rounded-lg border border-red-100 bg-red-50 p-4 text-sm text-red-700">{error}</div>}
    {notice&&<div role="status" className="rounded-lg border border-emerald-100 bg-emerald-50 p-4 text-sm text-emerald-800"><RiCheckLine className="inline mr-2"/>{notice} <Link to="/leads" className="ml-2 underline">Ver contatos</Link></div>}
    {tab==='listas'? <div className="grid md:grid-cols-3 gap-4">{lists.map(item=><button key={item.id} onClick={()=>openList(item)} className="text-left rounded-xl border bg-white p-5 hover:border-teal-400 transition-colors"><RiBookmarkLine className="text-teal-600 text-xl mb-4"/><h2 className="font-semibold">{item.nome}</h2><p className="text-sm text-gray-500 mt-2">{item.quantidade} empresas · {new Date(item.criado_em).toLocaleDateString('pt-BR')}</p><span className="inline-flex items-center gap-2 text-sm text-teal-700 mt-5">Abrir lista <RiArrowRightLine/></span></button>)}{!lists.length&&<div className="col-span-full rounded-xl border border-dashed p-12 text-center text-gray-500">Suas listas aparecerão aqui. Busque empresas, selecione até 50 e salve uma lista.</div>}</div>:
    <>
    <form onSubmit={search} className="rounded-2xl border bg-white p-6 space-y-5 shadow-sm">
      <div className="flex items-center justify-between"><h2 className="font-semibold flex items-center gap-2"><RiFilter3Line className="text-teal-600"/>Monte seu público</h2><button type="button" disabled={locked} onClick={()=>{change(INITIAL);setQuery('');}} className="text-xs text-gray-500 hover:text-teal-700">Limpar filtros</button></div>
      <div ref={box} className="relative"><label htmlFor="segment-search" className="text-sm font-medium">Segmentação</label><div className="relative"><RiSearchLine className="absolute left-3 top-5 text-gray-400"/><input id="segment-search" role="combobox" aria-autocomplete="list" aria-expanded={open} aria-controls="segment-options" aria-activedescendant={open&&active>=0&&suggestions[active]?`segment-option-${active}`:undefined} autoComplete="off" disabled={locked||catalogBusy} placeholder={catalogBusy?'Carregando suas segmentações…':'Ex.: tecnologia, marketing, RH, consultoria…'} className={fieldClass+' pl-9'} value={query} onFocus={()=>setOpen(true)} onChange={e=>{setQuery(e.target.value);setOpen(true);setActive(-1);}} onKeyDown={handleKeys}/></div>
      {open&&<div id="segment-options" role="listbox" aria-label="Sugestões de segmentação" className="absolute z-30 mt-2 max-h-80 overflow-auto w-full rounded-xl border bg-white shadow-xl"><div className="px-4 py-2 text-xs text-gray-400">{query?'Sugestões parecidas com sua busca':'Suas tags e segmentos salvos'} · contagens na base salva</div>{suggestions.map((item,index)=><button type="button" role="option" aria-selected={active===index} id={`segment-option-${index}`} key={item.id} onMouseDown={e=>e.preventDefault()} onClick={()=>choose(item)} className={`w-full text-left px-4 py-3 flex flex-col sm:flex-row justify-between gap-2 hover:bg-teal-50 ${index===active?'bg-teal-50':''}`}><span><span className="block text-sm font-medium">{item.nome}</span><span className="text-xs text-gray-400">{item.tipo}</span></span><span className="text-xs text-gray-500 whitespace-nowrap">{Number(item.quantidade||0).toLocaleString('pt-BR')} empresas</span></button>)}{!suggestions.length&&<p className="p-4 text-sm text-gray-500">Nenhum segmento parecido. Tente outra palavra.</p>}</div>}
      {catalogError&&<p role="alert" className="text-sm text-red-600 mt-2">{catalogError} <button type="button" onClick={loadCatalog} className="underline">Tentar novamente</button></p>}
      <div className="flex flex-wrap gap-2 mt-3">{selectedItems.map(item=><span key={item.id} className="inline-flex items-center gap-2 rounded-full bg-teal-50 border border-teal-100 text-teal-800 pl-3 pr-2 py-1.5 text-xs font-medium">{item.nome}<button type="button" disabled={locked} aria-label={`Remover ${item.nome}`} onClick={()=>change({segmentos:filters.segmentos.filter(id=>id!==item.id)})}><RiCloseLine/></button></span>)}</div>
      <p className="text-xs text-gray-400 mt-2">{filters.segmentos.length>1?'Inclui empresas de qualquer um dos segmentos selecionados.':'Clique no campo para ver sugestões. Sem seleção, a busca considera todos os segmentos.'}</p></div>
      <div className="grid md:grid-cols-3 gap-5 border-t pt-5">
        <div className="space-y-4"><label className="flex items-center gap-2 text-sm font-medium"><input type="checkbox" className="rounded text-teal-600" disabled={locked} checked={filters.com_email} onChange={e=>change({com_email:e.target.checked,confiabilidade:'',tipo_email:''})}/><RiMailLine className="text-gray-400"/>Com e-mail</label>
          {filters.com_email&&<><label className="block text-xs text-gray-500">Confiabilidade<select aria-label="Confiabilidade" disabled={locked} className={fieldClass} value={filters.confiabilidade} onChange={e=>change({confiabilidade:e.target.value})}><option value="">Todas as situações</option>{Object.entries(RELIABILITY).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label><label className="block text-xs text-gray-500">Tipo de e-mail<select aria-label="Tipo de e-mail" disabled={locked} className={fieldClass} value={filters.tipo_email} onChange={e=>change({tipo_email:e.target.value})}><option value="">Todos os tipos</option><option value="corporativo">Corporativo (classificação salva)</option><option value="publico">Provedor público: Gmail, Outlook e outros</option></select></label></>}
        </div>
        <label className="block text-sm font-medium"><span className="flex gap-2 items-center"><RiPhoneLine className="text-gray-400"/>Telefone</span><select aria-label="Telefone" disabled={locked} className={fieldClass} value={filters.telefone} onChange={e=>change({telefone:e.target.value})}><option value="">Com ou sem telefone</option><option value="com">Somente com telefone</option><option value="sem">Excluir empresas que têm telefone</option></select><span className="block mt-2 text-xs font-normal text-gray-400">Considera os dois números disponíveis no cadastro.</span></label>
        <label className="block text-sm font-medium"><span className="flex gap-2 items-center"><RiBuildingLine className="text-gray-400"/>Localização</span><select aria-label="Estado" disabled={locked} className={fieldClass} value={filters.uf} onChange={e=>change({uf:e.target.value})}><option value="">Todos os estados</option>{UFS.map(uf=><option key={uf}>{uf}</option>)}</select></label>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-4 border-t pt-4"><div className="flex flex-wrap gap-2"><span className="text-xs text-gray-400 self-center mr-1">Atalhos</span>{[['SMTP comprovado',{com_email:true,confiabilidade:'smtp_comprovado'}],['E-mail + telefone',{com_email:true,telefone:'com'}],['E-mail corporativo',{com_email:true,tipo_email:'corporativo'}]].map(([label,patch])=><button type="button" disabled={locked} key={label} onClick={()=>change(patch)} className="rounded-full border px-3 py-1.5 text-xs text-gray-600 hover:border-teal-300 hover:text-teal-700">{label}</button>)}</div><button disabled={locked||catalogBusy||!!catalogError} className="rounded-lg bg-teal-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-teal-700 disabled:opacity-50 flex items-center gap-2"><RiSearchLine/>{busy?'Buscando empresas…':'Buscar empresas'}</button></div>
    </form>
    <div className="flex flex-wrap items-center gap-2 text-xs"><span className="font-medium text-gray-500">Filtros ativos:</span><Tag>{filters.segmentos.length?`${filters.segmentos.length} segmento(s)`:'Todos os segmentos'}</Tag><Tag>{filters.uf||'Todos os estados'}</Tag>{filters.com_email&&<Tag>Com e-mail</Tag>}{filters.com_email&&filters.confiabilidade&&<Tag>{RELIABILITY[filters.confiabilidade]}</Tag>}{filters.com_email&&filters.tipo_email&&<Tag>{filters.tipo_email==='corporativo'?'Somente e-mail corporativo':'Somente provedor público'}</Tag>}{filters.telefone&&<Tag>{filters.telefone==='sem'?'Excluir empresas com telefone':'Somente empresas com telefone'}</Tag>}</div>
    <p className="text-xs text-gray-400">SMTP comprovado = endereço aceito pelo servidor na checagem salva; não comprova titularidade nem entrega. Inconclusivo não inclui endereços ainda não verificados. Nenhuma nova verificação é iniciada nesta busca.</p>
    {busy&&<div role="status" className="rounded-xl border p-10 text-center text-gray-500">Consultando os dados de contato…<p className="text-xs mt-2">A busca será interrompida se ultrapassar 90 segundos.</p><button type="button" onClick={()=>searchController.current?.abort()} className="mt-4 text-sm underline text-teal-700">Cancelar busca</button></div>}
    {result&&<section className="space-y-4"><div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-semibold">{listTitle||'Empresas encontradas'}</h2><p className="text-xs text-gray-500 mt-1">{rows.length} exibidas · {selected.length} de 50 selecionadas{listId?' · lista salva':''}</p></div><div className="flex flex-wrap gap-2"><button type="button" disabled={!selected.length||locked} onClick={()=>setSaveOpen(!saveOpen)} className="rounded-lg border bg-white px-4 py-2 text-sm disabled:opacity-40"><RiBookmarkLine className="inline mr-2"/>Salvar lista</button><button type="button" disabled={!selected.length||locked} onClick={importSelected} className="rounded-lg bg-teal-600 px-4 py-2 text-sm text-white disabled:opacity-40">{importing?'Adicionando…':'Adicionar aos contatos'}</button></div></div>
    {!!selected.length&&<label className="block rounded-xl border bg-white p-4 text-sm font-medium">Tag para os contatos desta importação (opcional)<input maxLength={80} disabled={locked} value={importTag} onChange={e=>setImportTag(e.target.value)} placeholder="Ex.: Prospecção novembro · Tecnologia SP" className={fieldClass}/><span className="block mt-2 text-xs font-normal text-gray-500">Será aplicada aos contatos novos e existentes, preservando as tags anteriores. Depois, filtre por essa tag em Contatos.</span></label>}
    {saveOpen&&<form onSubmit={saveList} className="flex flex-wrap gap-3 items-end rounded-xl bg-teal-50 border border-teal-100 p-4"><label className="flex-1 min-w-[200px] text-xs text-teal-800">Nome da lista<input autoFocus required maxLength={150} disabled={locked} placeholder="Ex.: Agências de marketing · SP" value={listName} onChange={e=>setListName(e.target.value)} className={fieldClass}/></label><button disabled={locked||!listName.trim()} className="rounded-lg bg-teal-600 text-white px-4 py-2.5 text-sm disabled:opacity-40">{saving?'Salvando…':`Salvar ${selected.length} empresas`}</button><button type="button" disabled={locked} onClick={()=>setSaveOpen(false)} className="p-2 text-sm text-gray-500">Cancelar</button></form>}
    {!rows.length&&<div className="rounded-xl border border-amber-200 bg-amber-50 p-5"><h3 className="font-medium text-amber-900">Nenhuma empresa atende a todos os filtros ativos.</h3><p className="text-sm text-amber-800 mt-2">Todos os segmentos e estados não removem os filtros de e-mail, confiabilidade e telefone.{filters.telefone==='sem'?' A opção de telefone está excluindo todas as empresas que têm número cadastrado.':''}</p><div className="flex flex-wrap gap-2 mt-4">{(result.alternativas||[]).map(option=><button type="button" disabled={locked} key={option.id} onClick={()=>search(null,option.filtros)} className="rounded-lg bg-white border border-amber-300 px-3 py-2 text-sm text-amber-900">{option.nome} · {option.quantidade.toLocaleString('pt-BR')} empresas</button>)}</div></div>}
    {result.has_more&&<p className="text-xs text-gray-500">Há mais empresas nesse público. Refine os filtros para localizar outras empresas. Cada lista pode ter até 50.</p>}
    <div className="overflow-x-auto rounded-xl border bg-white"><table className="w-full text-sm"><thead className="bg-gray-50 text-xs uppercase tracking-wide text-gray-500"><tr className="text-left"><th className="p-4"><input aria-label="Selecionar até 50 empresas" type="checkbox" disabled={locked||!rows.length} checked={!!rows.length&&rows.every(row=>selected.includes(row.cnpj_basico))} onChange={e=>setSelected(e.target.checked?rows.slice(0,50).map(row=>row.cnpj_basico):[])}/></th>{['Empresa / segmento','Localização','Contatos','Confiabilidade'].map(label=><th key={label} className="p-4">{label}</th>)}</tr></thead><tbody>{rows.map(row=><tr key={row.cnpj_basico} className={`border-t align-top ${selected.includes(row.cnpj_basico)?'bg-teal-50/40':'hover:bg-gray-50'}`}><td className="p-4"><input aria-label={`Selecionar ${row.razao_social}`} type="checkbox" disabled={locked} checked={selected.includes(row.cnpj_basico)} onChange={()=>toggle(row.cnpj_basico)}/></td><td className="p-4 min-w-[240px]"><div className="font-medium">{row.nome_fantasia||row.razao_social}</div><div className="text-xs text-gray-400 mt-1">{row.cnpj_basico}{row.cnpj_ordem}{row.cnpj_dv}</div><div className="flex flex-wrap gap-1 mt-2">{(row.segmentos||[]).map(item=><Tag key={item.id}>{item.nome}</Tag>)}</div></td><td className="p-4 text-gray-600"><span className="font-medium">{row.uf}</span><div className="text-xs text-gray-400 mt-1">Município {row.municipio}</div></td><td className="p-4 min-w-[210px]"><div className="flex gap-2 items-start"><RiMailLine className="mt-0.5 text-gray-400 shrink-0"/><span className="break-all">{row.email||'Sem e-mail'}</span></div><div className="flex gap-2 mt-2 text-xs text-gray-500"><RiPhoneLine className="mt-0.5 shrink-0"/>{phone(row)||'Sem telefone'}</div></td><td className="p-4 whitespace-nowrap"><Reliability value={row.confiabilidade}/>{row.verificado_em&&<p className="text-xs text-gray-400 mt-2">Checagem: {row.verificado_em.slice(0,10).split('-').reverse().join('/')}</p>}</td></tr>)}{!rows.length&&<tr><td colSpan={5} className="p-12 text-center text-gray-500">Nenhuma empresa corresponde a esta combinação. Experimente remover um filtro.</td></tr>}</tbody></table></div>
    <p className="text-xs text-gray-400">Salvar uma lista preserva a seleção. Ao adicionar aos contatos, os dados atuais e as tags são consultados novamente. Empresas sem e-mail válido ficam na lista, mas não são adicionadas aos contatos de e-mail.</p></section>}
    {!result&&!busy&&<div className="rounded-xl border border-dashed px-6 py-12 text-center"><RiBuildingLine className="mx-auto text-3xl text-teal-500 mb-3"/><h2 className="font-medium">Seu próximo público começa aqui</h2><p className="text-sm text-gray-500 mt-2">Escolha uma segmentação, combine os filtros e busque até 50 empresas para sua lista.</p></div>}
    </>}
  </div></div>;
}
