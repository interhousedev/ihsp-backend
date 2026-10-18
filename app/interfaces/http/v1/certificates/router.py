"""Routes of certificates (`/v1/certificates/*`)."""

from app.interfaces.http.v1.certificates.handlers import (
    add_entry_file,
    create_entry,
    create_type,
    delete_entry,
    delete_type,
    download_file,
    export_entries,
    get_staff_ranking,
    get_staff_stats,
    import_emis,
    list_custom_field_values,
    list_my_entries,
    list_staff_entries,
    list_staff_groups,
    list_types,
    remove_entry_file,
    update_entry,
    update_type,
)
from app.interfaces.http.v1.certificates.schemas import (
    CertificateEntryResponse,
    CertificateFileResponse,
    CertificateTypeResponse,
    CustomFieldValuesResponse,
    ImportEmisResponse,
    StaffEntriesResponse,
    StaffGroupResponse,
    StaffRankingResponse,
    StaffStatsResponse,
)

from fastapi import APIRouter, status

router = APIRouter(prefix="/v1/certificates", tags=["certificates"])
NO_CONTENT = status.HTTP_204_NO_CONTENT

# - - - Types - - -
router.add_api_route(
    "/types",
    list_types.list_types,
    methods=["GET"],
    response_model=list[CertificateTypeResponse],
)
router.add_api_route(
    "/admin/types",
    create_type.create_type,
    methods=["POST"],
    response_model=CertificateTypeResponse,
)
router.add_api_route(
    "/admin/types/{type_id}",
    update_type.update_type,
    methods=["PATCH"],
    response_model=CertificateTypeResponse,
)
router.add_api_route(
    "/admin/types/{type_id}",
    delete_type.delete_type,
    methods=["DELETE"],
    status_code=NO_CONTENT,
)

# - - - A student's entries - - -
router.add_api_route(
    "/me",
    list_my_entries.list_my_entries,
    methods=["GET"],
    response_model=list[CertificateEntryResponse],
)
router.add_api_route(
    "/me",
    create_entry.create_entry,
    methods=["POST"],
    response_model=CertificateEntryResponse,
)
# Before `/me/{entry_id}`, or "import-emis" would be parsed as an entry id.
router.add_api_route(
    "/me/import-emis",
    import_emis.import_emis,
    methods=["POST"],
    response_model=ImportEmisResponse,
)
router.add_api_route(
    "/me/{entry_id}",
    update_entry.update_entry,
    methods=["PATCH"],
    response_model=CertificateEntryResponse,
)
router.add_api_route(
    "/me/{entry_id}",
    delete_entry.delete_entry,
    methods=["DELETE"],
    status_code=NO_CONTENT,
)
router.add_api_route(
    "/me/{entry_id}/files",
    add_entry_file.add_entry_file,
    methods=["POST"],
    response_model=CertificateFileResponse,
)
router.add_api_route(
    "/me/{entry_id}/files/{file_id}",
    remove_entry_file.remove_entry_file,
    methods=["DELETE"],
    status_code=NO_CONTENT,
)
router.add_api_route(
    "/files/{file_id}/download",
    download_file.download_file,
    methods=["GET"],
    status_code=status.HTTP_307_TEMPORARY_REDIRECT,
)

# - - - Staff - - -
router.add_api_route(
    "/staff/entries",
    list_staff_entries.list_staff_entries,
    methods=["GET"],
    response_model=StaffEntriesResponse,
)
router.add_api_route(
    "/staff/stats",
    get_staff_stats.get_staff_stats,
    methods=["GET"],
    response_model=StaffStatsResponse,
)
router.add_api_route(
    "/staff/ranking",
    get_staff_ranking.get_staff_ranking,
    methods=["GET"],
    response_model=StaffRankingResponse,
)
router.add_api_route(
    "/staff/groups",
    list_staff_groups.list_staff_groups,
    methods=["GET"],
    response_model=list[StaffGroupResponse],
)
router.add_api_route(
    "/staff/fields/{key}/values",
    list_custom_field_values.list_custom_field_values,
    methods=["GET"],
    response_model=CustomFieldValuesResponse,
)
router.add_api_route("/staff/export", export_entries.export_entries, methods=["POST"])
