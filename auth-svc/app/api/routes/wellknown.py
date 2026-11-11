from fastapi import APIRouter, Request, Response

from app.schemas.jwks import JwksOut

router = APIRouter()


@router.get("/.well-known/jwks.json", response_model=JwksOut, tags=["jwks"])
async def jwks(request: Request, response: Response) -> dict:
    response.headers["Cache-Control"] = "public, max-age=300"
    return request.app.state.keystore.jwks()
