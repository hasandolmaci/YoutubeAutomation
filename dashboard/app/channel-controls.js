'use client';
import {useState,useEffect} from 'react';
export default function ChannelControls({data,channel,onChannel,onRefresh}){
  const [adding,setAdding]=useState(false),[settingsOpen,setSettingsOpen]=useState(false),[name,setName]=useState(''),[id,setId]=useState(''),[count,setCount]=useState(1),[form,setForm]=useState(null),[message,setMessage]=useState(''),[busy,setBusy]=useState(false);
  useEffect(()=>{setForm(data?.channel??null);},[channel,data?.channel?.voice,data?.channel?.speed,data?.channel?.period_pause,data?.channel?.min_words,data?.channel?.max_words]);
  async function action(body){setBusy(true);setMessage('');try{const response=await fetch('/api/channels',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...body,channel})});const result=await response.json();if(!response.ok)throw Error(result.error);if(body.action==='create'){onChannel(result.id);setAdding(false);}else if(body.action==='settings')setMessage('Settings saved.');await onRefresh();}catch(e){setMessage(e.message);}finally{setBusy(false);}}
  const set=(key,value)=>setForm({...form,[key]:value});
  return <section className="channel-controls"><div className="channel-toolbar"><label>CHANNEL<select value={channel} onChange={e=>onChannel(e.target.value)}>{(data?.channels??[{id:'main',name:'Main channel'}]).map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></label><button onClick={()=>setAdding(!adding)}>+ Add channel</button><button onClick={()=>setSettingsOpen(!settingsOpen)}>Settings</button><span className="channel-identity">{data?.channel.youtube_channel_id??'No YouTube channel connected'}</span><button disabled={busy||data?.connection.running} onClick={()=>action({action:'connect'})}>{data?.connection.running?'Finish Google sign-in…':data?.channel.connected?'Reconnect channel':'Connect channel'}</button></div>
  {data?.connection.running&&<div className="channel-note">Google sign-in is waiting for completion. If you closed its tab or saw an error, cancel and connect again. <button disabled={busy} onClick={()=>action({action:'cancel-connect'})}>Cancel sign-in</button></div>}
  {adding&&<form className="channel-form" onSubmit={e=>{e.preventDefault();action({action:'create',id,name});}}><label>Profile name<input required value={name} onChange={e=>setName(e.target.value)} placeholder="Wholesome stories"/></label><label>Folder ID<input required pattern="[a-z0-9][a-z0-9_-]{0,39}" value={id} onChange={e=>setId(e.target.value)} placeholder="wholesome"/></label><button disabled={busy}>Create channel</button></form>}
  {!data?.channel.connected&&<p className="channel-note">Connect once and choose the correct YouTube channel. Every upload checks its identity before publishing.</p>}
  {data?.connection.error&&<p role="alert" className="channel-message">{data.connection.error}</p>}
  {settingsOpen&&form&&<form className="settings-form" onSubmit={e=>{e.preventDefault();action({action:'settings',settings:form});}}>
    <label>Story category<input value={form.story_category} onChange={e=>set('story_category',e.target.value)}/></label>
    <label>Kokoro voice<input value={form.voice} onChange={e=>set('voice',e.target.value)}/></label>
    <label>Narration speed<input type="number" min="0.5" max="2" step="0.05" value={form.speed} onChange={e=>set('speed',Number(e.target.value))}/></label>
    <label>Period pause (seconds)<input type="number" min="0" max="2" step="0.05" value={form.period_pause} onChange={e=>set('period_pause',Number(e.target.value))}/></label>
    <label>Captions<select value={form.caption_style} onChange={e=>set('caption_style',e.target.value)}><option value="words">Yellow word-by-word</option><option value="phrases">White phrases</option></select></label>
    <label>Minimum script words<input type="number" value={form.min_words} onChange={e=>set('min_words',Number(e.target.value))}/></label>
    <label>Maximum script words<input type="number" value={form.max_words} onChange={e=>set('max_words',Number(e.target.value))}/></label>
    <label>Background rotation<select multiple value={form.backgrounds} onChange={e=>set('backgrounds',Array.from(e.target.selectedOptions,o=>o.value))}>{(data?.backgroundFiles??[]).map(f=><option key={f}>{f}</option>)}</select><small>No selection uses all backgrounds.</small></label>
    <label>Publishing time zone<input value={form.schedule.timezone} onChange={e=>set('schedule',{...form.schedule,timezone:e.target.value})}/></label>
    <label>Daily publish times<input value={form.schedule.times.join(',')} onChange={e=>set('schedule',{...form.schedule,times:e.target.value.split(',').map(t=>t.trim())})}/></label>
    <label className="schedule-check"><input type="checkbox" checked={form.schedule.enabled} onChange={e=>set('schedule',{...form.schedule,enabled:e.target.checked})}/>Enable public publishing schedule</label><p className="channel-note">Scheduled publishing runs only while start_scheduler.cmd is running. Video creation is separate.</p><button disabled={busy}>Save settings</button>
  </form>}
  <div className="production-row"><div><strong>Create videos</strong><p>{data?.eligibleStories??0} complete, unused stories meet this channel’s settings. Shared duplicate checks apply.</p><small>Story folder: {channel==='main'?'stories/':`channels/${channel}/stories/`}</small></div><input aria-label="Number of videos to create" type="number" min="1" max="100" value={count} onChange={e=>setCount(Number(e.target.value))}/><button disabled={busy||data?.production.running||!data?.eligibleStories} onClick={()=>action({action:'produce',count})}>{data?.production.running?'Creating videos…':'Create videos'}</button></div>
  {data?.production.running&&<p className="channel-note">Production running for {data.production.channel}. One batch runs at a time.</p>}
  {data?.production.log?.length>0&&<details><summary>Production progress</summary><pre>{data.production.log.join('')}</pre></details>}
  {message&&<p role="status" className="channel-message">{message}</p>}
  </section>;
}
