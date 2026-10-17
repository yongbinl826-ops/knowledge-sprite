"""Read-only isolated UI against a copied evidence DB; never serves port 8000."""
import argparse,os,sys
from dataclasses import replace
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from fastapi.responses import FileResponse,JSONResponse
from fastapi.staticfiles import StaticFiles
from backend.app.config import Settings
from backend.app.main import create_app
import uvicorn

def app_for(database,dist):
    database=Path(database).resolve();dist=Path(dist).resolve()
    allowed=ROOT/'reports/evidence-followup-20261014'
    assert database.is_relative_to(allowed) and database.exists()
    assert dist.is_relative_to(allowed) and (dist/'index.html').is_file()
    settings=replace(Settings.from_env(),database_path=str(database),fetch_enabled=False,js_render_enabled=False,llm_provider='none',llm_api_key='',max_results_per_point=3)
    app=create_app(settings)
    # Replace only the factory's UI mounts; all API reads remain real routes.
    app.router.routes=[route for route in app.router.routes if getattr(route,'path',None) not in {'/','/assets'}]
    app.mount('/assets',StaticFiles(directory=dist/'assets'),name='review-assets')
    @app.get('/',include_in_schema=False)
    async def index():return FileResponse(dist/'index.html')
    @app.middleware('http')
    async def readonly(request,call_next):
        if request.method not in {'GET','HEAD','OPTIONS'}:
            return JSONResponse({'detail':'Isolated saved-evidence UI is read-only; no external search is permitted.'},status_code=403)
        return await call_next(request)
    return app

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--database',required=True);parser.add_argument('--dist',required=True);parser.add_argument('--port',type=int,default=18007)
    args=parser.parse_args();assert args.port==18007
    uvicorn.run(app_for(args.database,args.dist),host='127.0.0.1',port=args.port,workers=1)
