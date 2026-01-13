from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import get_db, MovieModel
from database.models import (
    CountryModel,
    GenreModel,
    ActorModel,
    LanguageModel
)
from schemas.movies import (
    MoviesListResponse,
    MovieResponse,
    MovieCreate,
    MovieUpdate
)

router = APIRouter(prefix="/movies")


@router.get("/", response_model=MoviesListResponse)
async def get_movies(
        page: int = Query(1, ge=1),
        per_page: int = Query(10, ge=1, le=20),
        db: AsyncSession = Depends(get_db),
):
    count_query = select(func.count(MovieModel.id))
    result = await db.execute(count_query)
    total_items = result.scalar_one()

    if total_items == 0 or (page - 1) * per_page >= total_items:
        raise HTTPException(
            status_code=404,
            detail="No movies found."
        )

    offset = (page - 1) * per_page
    query = (
        select(MovieModel)
        .order_by(MovieModel.id.desc())
        .limit(per_page)
        .offset(offset)
    )
    result = await db.execute(query)
    movies = result.scalars().all()

    total_pages = (total_items + per_page - 1) // per_page

    prev_page = None
    if page > 1:
        prev_page = f"/theater/movies/?page={page - 1}&per_page={per_page}"

    next_page = None
    if page < total_pages:
        next_page = f"/theater/movies/?page={page + 1}&per_page={per_page}"

    return MoviesListResponse(
        movies=movies,
        prev_page=prev_page,
        next_page=next_page,
        total_pages=total_pages,
        total_items=total_items
    )


async def get_or_create_entities(
        db: AsyncSession,
        model,
        names: list[str]
):
    entities = []
    for name in names:
        query = select(model).where(model.name == name)
        result = await db.execute(query)
        instance = result.scalar_one_or_none()

        if not instance:
            instance = model(name=name)
            db.add(instance)
            await db.flush()

        entities.append(instance)

    return entities


@router.post("/", response_model=MovieResponse, status_code=201)
async def create_movie(
        movie: MovieCreate,
        db: AsyncSession = Depends(get_db)
):
    try:
        duplicate_query = select(MovieModel).where(
            MovieModel.name == movie.name,
            MovieModel.date == movie.date
        )
        result = await db.execute(duplicate_query)
        existing_movie = result.scalar_one_or_none()

        if existing_movie:
            raise HTTPException(
                status_code=409,
                detail=f"A movie with the name '{movie.name}' "
                       f"and release date '{movie.date}' already exists."
            )

        country_query = select(CountryModel).where(
            CountryModel.code == movie.country
        )

        result = await db.execute(country_query)
        country = result.scalar_one_or_none()

        if not country:
            country = CountryModel(code=movie.country, name=None)
            db.add(country)
            await db.flush()

        genres = await get_or_create_entities(db, GenreModel, movie.genres)
        actors = await get_or_create_entities(db, ActorModel, movie.actors)
        languages = await get_or_create_entities(db, LanguageModel, movie.languages)

        new_movie = MovieModel(
            name=movie.name,
            date=movie.date,
            score=movie.score,
            overview=movie.overview,
            status=movie.status,
            budget=movie.budget,
            revenue=movie.revenue,
            country_id=country.id,
            genres=genres,
            actors=actors,
            languages=languages
        )

        db.add(new_movie)
        await db.commit()

        query = (
            select(MovieModel)
            .options(
                selectinload(MovieModel.country),
                selectinload(MovieModel.genres),
                selectinload(MovieModel.actors),
                selectinload(MovieModel.languages)
            )
            .where(MovieModel.id == new_movie.id)
        )
        result = await db.execute(query)
        return result.scalar_one()

    except RequestValidationError:
        raise HTTPException(
            status_code=400,
            detail="Invalid input data."
        )


@router.get("/{movie_id}/", response_model=MovieResponse)
async def get_movie(movie_id: int, db: AsyncSession = Depends(get_db)):
    query = (
        select(MovieModel)
        .options(
            selectinload(MovieModel.country),
            selectinload(MovieModel.genres),
            selectinload(MovieModel.actors),
            selectinload(MovieModel.languages)
        )
        .where(MovieModel.id == movie_id)
    )
    result = await db.execute(query)
    movie = result.scalar_one_or_none()

    if not movie:
        raise HTTPException(
            status_code=404,
            detail="Movie with the given ID was not found."
        )

    return movie


@router.delete("/{movie_id}/", status_code=204)
async def delete_movie(movie_id: int, db: AsyncSession = Depends(get_db)):
    query = select(MovieModel).where(MovieModel.id == movie_id)
    result = await db.execute(query)
    movie = result.scalar_one_or_none()

    if not movie:
        raise HTTPException(
            status_code=404,
            detail="Movie with the given ID was not found."
        )

    await db.delete(movie)
    await db.commit()

    return None


@router.patch("/{movie_id}/")
async def update_movie(
        movie_id: int,
        movie_update: MovieUpdate,
        db: AsyncSession = Depends(get_db)
):
    try:
        query = select(MovieModel).where(MovieModel.id == movie_id)
        result = await db.execute(query)
        movie = result.scalar_one_or_none()

        if not movie:
            raise HTTPException(
                status_code=404,
                detail="Movie with the given ID was not found."
            )

        update_data = movie_update.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            setattr(movie, field, value)

        await db.commit()

        return {"detail": "Movie updated successfully."}

    except RequestValidationError:
        raise HTTPException(
            status_code=400,
            detail="Invalid input data."
        )
