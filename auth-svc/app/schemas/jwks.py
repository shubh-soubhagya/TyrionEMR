from pydantic import BaseModel


class JwkOut(BaseModel):
    kty: str
    use: str
    alg: str
    kid: str
    n: str
    e: str


class JwksOut(BaseModel):
    keys: list[JwkOut]
