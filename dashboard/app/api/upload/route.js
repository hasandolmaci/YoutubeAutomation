import {uploadNext,isLocalRequest} from '../../../lib/studio';
export const dynamic='force-dynamic';
export async function POST(request) {
  if(!isLocalRequest(request)) return Response.json({error:'Only dashboard requests are allowed.'},{status:403});
  try {const body=await request.json().catch(()=>({}));return Response.json(await uploadNext(body.channel||'main'));}
  catch(error) {return Response.json({error:error.message},{status:409});}
}
