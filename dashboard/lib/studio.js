import fs from 'node:fs/promises';
import path from 'node:path';
import {spawn} from 'node:child_process';
const root=path.resolve(process.cwd(),'..');
export function isLocalRequest(request){
  try{const origin=new URL(request.headers.get('origin'));return origin.host===request.headers.get('host')&&['localhost','127.0.0.1','[::1]'].includes(origin.hostname);}catch{return false;}
}
const jobs=globalThis.__channelJobs??={};
const connectionProcesses=globalThis.__connectionProcesses??=new Map();
const production=globalThis.__productionJob??={running:false,log:[],channel:null,error:null,exitCode:null};
async function json(file,fallback){try{return JSON.parse(await fs.readFile(file,'utf8'));}catch(e){if(e.code==='ENOENT')return fallback;throw e;}}
async function files(folder){try{return await fs.readdir(folder,{withFileTypes:true});}catch(e){if(e.code==='ENOENT')return [];throw e;}}
async function config(id='main'){
  if(!/^[a-z0-9][a-z0-9_-]{0,39}$/.test(id))throw Error('Invalid channel ID');
  const value=await json(path.join(root,'channels',id,'config.json'),null);
  if(!value)throw Error('Channel profile not found');return value;
}
function base(id){return id==='main'?root:path.join(root,'channels',id);}
function job(id){return jobs[id]??={upload:{running:false,log:[],error:null,exitCode:null},insights:{running:false,error:null,lastAttempt:0},connection:{running:false,log:[],error:null,exitCode:null}};}
function start(script,args,state,tts=false){
  if(state.running)throw Error('This job is already running.');
  Object.assign(state,{running:true,error:null,log:[],exitCode:null,lastAttempt:Date.now()});
  const child=spawn(path.join(root,tts?'.venv-tts':'.venv','Scripts','python.exe'),['-u',path.join(root,script),...args],{cwd:root,windowsHide:true,env:{...process.env,PYTHONIOENCODING:'utf-8'}});
  const append=chunk=>{state.log.push(chunk.toString());if(state.log.length>200)state.log.shift();};
  child.stdout.on('data',append);child.stderr.on('data',append);
  child.on('error',e=>{state.error=e.message;state.running=false;state.exitCode=1;});
  child.on('close',code=>{state.running=false;state.exitCode=code;if(code!==0)state.error=state.log.join('').slice(-1500)||'Job stopped.';});
  return child;
}
export async function syncInsights(connect=false,id='main'){
  await config(id);if(connect)return connectChannel(id);
  if(!job(id).insights.running)start('youtube_insights.py',['--channel',id],job(id).insights);
}
export async function connectChannel(id){
  await config(id);
  const child=start('manage_channel.py',['connect',id],job(id).connection);
  connectionProcesses.set(id,child);
  child.once('close',()=>{if(connectionProcesses.get(id)===child)connectionProcesses.delete(id);});
  return {started:true};
}
export async function cancelConnection(id){
  await config(id);
  const child=connectionProcesses.get(id),state=job(id).connection;
  if(child&&child.exitCode===null){
    await new Promise((resolve,reject)=>{
      child.once('close',resolve);
      if(!child.kill()){reject(Error('Could not stop the sign-in process. Please restart the dashboard.'));}
    });
  }
  connectionProcesses.delete(id);
  Object.assign(state,{running:false,error:null,exitCode:null,log:['Sign-in cancelled. You can connect again.']});
  return {cancelled:true};
}
export async function snapshot(id='main'){
  const selected=await config(id),directory=base(id),state=job(id),credentials=path.join(directory,'credentials');
  const connected=await fs.access(path.join(credentials,'channel_token.json')).then(()=>true,()=>false);
  const insightsConnected=connected||await fs.access(path.join(credentials,'insights_token.json')).then(()=>true,()=>false);
  const cache=await json(path.join(directory,'output/youtube_insights.json'),{updatedAt:null,videos:{}});
  if(insightsConnected&&Date.now()-state.insights.lastAttempt>300000)await syncInsights(false,id);
  const history=await json(path.join(credentials,'upload_history.json'),{}),records=Object.values(history),queue=[];
  for(const folder of (await files(path.join(directory,'videos'))).filter(f=>f.isDirectory()).sort((a,b)=>a.name.localeCompare(b.name))){
    const videoDir=path.join(directory,'videos',folder.name),batch=await json(path.join(videoDir,'batch.json'),[]);
    const names=new Set((await files(videoDir)).filter(f=>f.isFile()).map(f=>f.name));
    for(const item of batch){
      if(item.status!=='complete'||!item.video)continue;
      if(!names.has(item.video)&&!names.has(item.video.replace(/\.mp4$/i,'_used.mp4')))continue;
      const receipt=records.find(r=>r.file===path.join(videoDir,item.video));
      const status=receipt?.status==='uploaded'?'uploaded':receipt?'attention':names.has(item.video)?'ready':'used';
      queue.push({name:item.video,title:item.title,duration:item.duration_seconds,background:item.background,batch:folder.name,status,videoId:receipt?.video_id,privacy:receipt?.privacy,insights:cache.videos[receipt?.video_id]??null});
    }
  }
  let stories=0,eligible=0;
  const usage=await json(path.join(root,'output/shared/story_usage.json'),{}),seen=new Set();
  const {createHash}=await import('node:crypto');
  for(const file of (await files(path.join(directory,'stories'))).filter(f=>f.isFile()&&f.name.endsWith('.json'))){
    const story=await json(path.join(directory,'stories',file.name),{});
    if(typeof story.text!=='string'||!story.text.trim())continue;stories++;
    const normalized=story.text.normalize('NFKC').toLowerCase().trim().replace(/\s+/gu,' ');
    const hash=createHash('sha256').update(normalized).digest('hex');
    const count=((story.title+' '+story.text).match(/\b\w+(?:['’\-]\w+)*\b/g)||[]).length;
    const title=(story.title||'').trim(),storyId=story.id||file.name.replace(/\.json$/,'');
    const alreadyUsed=Object.values(usage).some(row=>row.story_id===storyId);
    if(!file.name.endsWith('_used.json')&&story.text_source==='post_page'&&!usage[hash]&&!alreadyUsed&&!seen.has(hash)&&title.length>0&&title.length<=100&&!/[<>]/.test(title)&&count>=selected.min_words&&count<=selected.max_words){eligible++;seen.add(hash);}
  }
  const backgroundFiles=(await files(path.join(root,'backgrounds'))).filter(f=>f.isFile()&&f.name.endsWith('.mp4')).map(f=>f.name),profiles=[];
  for(const folder of (await files(path.join(root,'channels'))).filter(f=>f.isDirectory())){const c=await json(path.join(root,'channels',folder.name,'config.json'),null);if(c)profiles.push({id:c.id,name:c.name,youtube_channel_id:c.youtube_channel_id});}
  return {channel:{...selected,connected},channels:profiles,backgroundFiles,eligibleStories:eligible,
    stats:{stories,backgrounds:backgroundFiles.length,total:queue.length,ready:queue.filter(v=>v.status==='ready').length,uploaded:queue.filter(v=>v.status==='uploaded').length},
    queue,next:queue.find(v=>v.status==='ready'||v.status==='attention')??null,
    insights:{...state.insights,connected:insightsConnected,updatedAt:cache.updatedAt,totals:queue.reduce((t,v)=>({views:t.views+(v.insights?.viewCount??0),likes:t.likes+(v.insights?.likeCount??0),comments:t.comments+(v.insights?.commentCount??0)}),{views:0,likes:0,comments:0})},
    upload:{...state.upload,log:[...state.upload.log]},connection:state.connection,production:{...production,log:[...production.log]},updatedAt:new Date().toISOString()};
}
export async function uploadNext(id='main'){
  const data=await snapshot(id);
  if(!data.channel.connected)throw Error('Connect this channel before uploading.');
  if(!data.next)throw Error('No unused videos remain.');
  if(data.next.status==='attention')throw Error('Check the previous upload in YouTube Studio before retrying.');
  start('upload_next.py',['--channel',id,'--folder',path.join(base(id),'videos',data.next.batch)],job(id).upload);return {started:true};
}
export async function produce(id,count){
  const data=await snapshot(id);
  if(!Number.isInteger(count)||count<1||count>100)throw Error('Choose between 1 and 100 videos.');
  if(count>data.eligibleStories)throw Error(`Only ${data.eligibleStories} complete, unused stories meet your settings.`);
  if(production.running)throw Error('Production is already running. Jobs run one batch at a time.');
  production.channel=id;start('produce_batch.py',['--channel',id,'--count',String(count)],production,true);return {started:true};
}
export async function createProfile(id,name){
  if(!/^[a-z0-9][a-z0-9_-]{0,39}$/.test(id))throw Error('Use lowercase letters, numbers or hyphens for the ID.');
  if(typeof name!=='string'||!name.trim()||name.length>80)throw Error('Enter a channel name under 80 characters.');
  await new Promise((resolve,reject)=>{let log='';const child=spawn(path.join(root,'.venv/Scripts/python.exe'),[path.join(root,'manage_channel.py'),'create',id,'--name',name],{cwd:root,windowsHide:true});child.stderr.on('data',c=>log+=c.toString());child.on('error',reject);child.on('close',code=>code===0?resolve():reject(Error(log||'Could not create profile.')));});return {id};
}
export async function saveSettings(id,values){
  const c=await config(id);
  if(!/^[ab][fm]_[a-z]+$/.test(values.voice))throw Error('Enter a Kokoro English voice ID, e.g. af_heart or am_adam.');
  if(!['words','phrases'].includes(values.caption_style))throw Error('Invalid caption style.');
  if(!Number.isFinite(values.speed)||values.speed<0.5||values.speed>2)throw Error('Speed must be 0.5–2.');
  if(!Number.isFinite(values.period_pause)||values.period_pause<0||values.period_pause>2)throw Error('Pause must be 0–2 seconds.');
  if(!Number.isInteger(values.min_words)||!Number.isInteger(values.max_words)||values.min_words<1||values.max_words<values.min_words||values.max_words>2000)throw Error('Invalid word limits.');
  if(!Array.isArray(values.backgrounds)||values.backgrounds.some(n=>!/^background_\d+\.mp4$/.test(n)))throw Error('Invalid backgrounds.');
  const schedule=values.schedule;
  if(!schedule||typeof schedule.enabled!=='boolean'||!Array.isArray(schedule.times)||!schedule.times.length||schedule.times.length>24||schedule.times.some(t=>!/^([01]\d|2[0-3]):[0-5]\d$/.test(t)))throw Error('Enter valid publishing times, such as 10:00,18:00.');
  try{new Intl.DateTimeFormat('en',{timeZone:schedule.timezone});}catch{throw Error('Invalid time zone.');}
  for(const key of ['voice','speed','period_pause','caption_style','min_words','max_words','backgrounds','schedule'])c[key]=values[key];
  c.story_category=String(values.story_category||'General stories').slice(0,100);
  const file=path.join(root,'channels',id,'config.json');await fs.writeFile(file+'.tmp',JSON.stringify(c,null,2));await fs.rename(file+'.tmp',file);return {saved:true};
}
