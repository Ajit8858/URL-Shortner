from fastapi import APIRouter, HTTPException, status

from app import crud, schemas, security
from app.deps import DbDep
from app.utils import generate_api_key

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register", response_model=schemas.Token, status_code=201)
async def register(payload: schemas.UserCreate, db: DbDep):
    existing = await crud.get_user_by_email(db, payload.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = await crud.create_user(
        db,
        email=payload.email,
        hashed_password=security.hash_password(payload.password),
        api_key=generate_api_key(),
    )
    token = security.create_access_token(subject=str(user.id))
    return schemas.Token(access_token=token)


@router.post("/login", response_model=schemas.Token)
async def login(payload: schemas.UserCreate, db: DbDep):
    user = await crud.get_user_by_email(db, payload.email)
    if not user or not security.verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )
    token = security.create_access_token(subject=str(user.id))
    return schemas.Token(access_token=token)
