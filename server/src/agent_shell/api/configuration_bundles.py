from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent_shell.configuration.bundles.archive import BundleArchiveError
from agent_shell.configuration.bundles.contracts import BundleRoot, ImportResolutions
from agent_shell.configuration.bundles.exporting import BundleExportError
from agent_shell.configuration.bundles.errors import BundleImportError
from agent_shell.configuration.bundles.service import ConfigurationBundleService


class _ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_token: str = Field(pattern=r"^[0-9a-f]{64}$")
    resolutions: ImportResolutions


def _bundle_error(exc: Exception, *, status_code: int = 422) -> HTTPException:
    detail: dict[str, object] = {
        "code": "configuration_bundle_invalid",
        "message": str(exc),
        "message_key": "errors.configurationBundleInvalid",
        "message_args": {},
    }
    if isinstance(exc, BundleImportError) and exc.issues:
        detail["issues"] = exc.issues
    return HTTPException(status_code=status_code, detail=detail)


def build_configuration_bundle_router(
    bundles: ConfigurationBundleService,
) -> APIRouter:
    router = APIRouter()

    @router.post("/api/configuration-bundles/export")
    async def export_configuration_bundle(root: BundleRoot) -> Response:
        try:
            exported = bundles.export(root)
        except (BundleExportError, ValueError) as exc:
            raise _bundle_error(exc) from exc
        return Response(
            content=exported.content,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{exported.filename}"'
            },
        )

    @router.post("/api/configuration-bundles/preview")
    async def preview_configuration_bundle(
        bundle: Annotated[UploadFile, File()],
    ) -> dict[str, object]:
        try:
            return bundles.preview(await bundle.read())
        except (BundleArchiveError, BundleImportError, ValueError) as exc:
            raise _bundle_error(exc) from exc

    @router.post("/api/configuration-bundles/import")
    async def import_configuration_bundle(
        bundle: Annotated[UploadFile, File()],
        request: Annotated[str, Form()],
    ) -> dict[str, object]:
        try:
            parsed_request = _ImportRequest.model_validate_json(request)
            return bundles.commit(
                await bundle.read(),
                bundle_sha256=parsed_request.bundle_sha256,
                plan_token=parsed_request.plan_token,
                resolutions=parsed_request.resolutions,
            )
        except ValidationError as exc:
            raise _bundle_error(
                ValueError("configuration bundle import request is invalid")
            ) from exc
        except BundleArchiveError as exc:
            raise _bundle_error(exc) from exc
        except BundleImportError as exc:
            raise _bundle_error(exc, status_code=409) from exc

    return router


__all__ = ["build_configuration_bundle_router"]
