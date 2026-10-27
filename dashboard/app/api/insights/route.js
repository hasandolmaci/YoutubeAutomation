import {syncInsights,isLocalRequest} from '../../../lib/studio';
export async function POST(request) {
  if(!isLocalRequest(request)) return Response.json({error:'Only dashboard requests are allowed.'},{status:403});
  const body=await request.json().catch(()=>({}));
  try {await syncInsights(body.connect===true,body.channel||'main');return Response.json({started:true});}
  catch(error){return Response.json({error:error.message},{status:400});}
}
