import {createProfile,connectChannel,cancelConnection,produce,saveSettings,isLocalRequest} from '../../../lib/studio';
export async function POST(request){
  if(!isLocalRequest(request))return Response.json({error:'Only dashboard requests are allowed.'},{status:403});
  try{
    const body=await request.json();let result;
    if(body.action==='create')result=await createProfile(body.id,body.name);
    else if(body.action==='connect')result=await connectChannel(body.channel);
    else if(body.action==='cancel-connect')result=await cancelConnection(body.channel);
    else if(body.action==='produce')result=await produce(body.channel,body.count);
    else if(body.action==='settings')result=await saveSettings(body.channel,body.settings);
    else throw Error('Unknown action');
    return Response.json(result);
  }catch(error){return Response.json({error:error.message},{status:400});}
}
