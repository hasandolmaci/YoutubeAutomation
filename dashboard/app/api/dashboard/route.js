import {snapshot} from '../../../lib/studio';
export const dynamic='force-dynamic';
export async function GET(request) {
  try {return Response.json(await snapshot(new URL(request.url).searchParams.get('channel')||'main'),{headers:{'Cache-Control':'no-store'}});}
  catch(error) {return Response.json({error:error.message},{status:500});}
}
