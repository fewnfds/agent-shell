from __future__ import annotations

from typing import NoReturn

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.background import BackgroundTask

from agent_shell.http_surface import management_api_router
from agent_shell.api.errors import management_error
from agent_shell.file_manager import FileManagerError, FileManagerService


class FilePathInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(max_length=4096)


class FileRenameInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(max_length=4096)
    name: str = Field(max_length=255)


class FileSelectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paths: list[str]


class TextFileSaveInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(max_length=4096)
    content: str
    revision: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")


def _raise_file_error(error: FileManagerError) -> NoReturn:
    raise management_error(
        error.status_code,
        code=error.code,
        message_key=error.message_key,
        message=str(error),
        message_args=error.message_args,
    ) from error


def build_file_manager_router(files: FileManagerService) -> APIRouter:
    router = management_api_router()

    @router.get("/file-manager")
    async def list_directory(
        path: str = Query(default="data", max_length=4096),
    ) -> dict:
        try:
            return files.list_directory(path)
        except FileManagerError as exc:
            _raise_file_error(exc)

    @router.post("/file-manager/directories")
    async def create_directory(payload: FilePathInput) -> dict:
        try:
            return files.create_directory(payload.path)
        except FileManagerError as exc:
            _raise_file_error(exc)

    @router.post("/file-manager/text-files")
    async def create_text_file(payload: FilePathInput) -> dict:
        try:
            return files.create_text_file(payload.path)
        except FileManagerError as exc:
            _raise_file_error(exc)

    @router.put("/file-manager/upload")
    async def upload_file(
        request: Request,
        path: str = Query(max_length=4096),
        overwrite: bool = Query(default=False),
    ) -> dict:
        try:
            return await files.upload(
                path,
                request.stream(),
                overwrite=overwrite,
            )
        except FileManagerError as exc:
            _raise_file_error(exc)

    @router.get("/file-manager/download")
    async def download_file(
        path: str = Query(max_length=4096),
    ) -> FileResponse:
        try:
            download = files.prepare_download(path)
        except FileManagerError as exc:
            _raise_file_error(exc)
        return FileResponse(
            download.path,
            filename=download.filename,
            media_type=download.media_type,
            background=(
                BackgroundTask(files.release_download, download)
                if download.delete_after
                else None
            ),
        )

    @router.post("/file-manager/archive/preview")
    async def preview_archive(payload: FileSelectionInput) -> dict:
        try:
            return files.preview_archive(payload.paths)
        except FileManagerError as exc:
            _raise_file_error(exc)

    @router.post("/file-manager/archive")
    async def download_archive(
        payload: FileSelectionInput,
    ) -> FileResponse:
        try:
            download = files.prepare_archive(payload.paths)
        except FileManagerError as exc:
            _raise_file_error(exc)
        return FileResponse(
            download.path,
            filename=download.filename,
            media_type=download.media_type,
            background=BackgroundTask(files.release_download, download),
        )

    @router.get("/file-manager/text")
    async def read_text_file(
        path: str = Query(max_length=4096),
    ) -> dict:
        try:
            return files.read_text(path)
        except FileManagerError as exc:
            _raise_file_error(exc)

    @router.put("/file-manager/text")
    async def save_text_file(payload: TextFileSaveInput) -> dict:
        try:
            return files.save_text(
                payload.path,
                payload.content,
                payload.revision,
            )
        except FileManagerError as exc:
            _raise_file_error(exc)

    @router.patch("/file-manager")
    async def rename_file(payload: FileRenameInput) -> dict:
        try:
            return files.rename(payload.path, payload.name)
        except FileManagerError as exc:
            _raise_file_error(exc)

    @router.delete("/file-manager")
    async def delete_file(
        path: str = Query(max_length=4096),
    ) -> dict:
        try:
            return files.delete(path)
        except FileManagerError as exc:
            _raise_file_error(exc)

    return router
