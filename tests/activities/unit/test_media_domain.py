"""Club media domain: states, reports, limits, access rules and signed URLs."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.modules.activities.domain.access import Permission, global_permissions
from app.modules.activities.domain.media import (
    Album,
    AlbumDepthError,
    AlbumVisibility,
    ClubMediaOverrides,
    HiddenSource,
    InvalidMediaUrlError,
    Media,
    MediaAlreadyReportedError,
    MediaConsentRequiredError,
    MediaKind,
    MediaNotReadyError,
    MediaQuotaExceededError,
    MediaStateError,
    MediaStatus,
    MediaTooLargeError,
    MediaTypeNotAllowedError,
    MediaUsage,
    MediaVariant,
    Viewer,
    can_delete_media,
    can_upload_to_album,
    can_view_album,
    check_album_depth,
    check_quota,
    check_size,
    kind_for_content_type,
    kind_for_name,
    resolve_limits,
    sign_media_url,
    verify_media_url,
)
from app.shared.actor import Role

import pytest

NOW = datetime(2026, 11, 28, 12, 0, tzinfo=UTC)
MIB = 1024 * 1024
LIMITS = resolve_limits(
    ClubMediaOverrides(),
    photo_max_bytes=15 * MIB,
    video_max_bytes=300 * MIB,
    quota_bytes=5 * 1024 * MIB,
)


def ready(kind: MediaKind = MediaKind.PHOTO, uploader: UUID | None = None) -> Media:
    """A processed photo or video."""
    m = Media(
        id=uuid4(),
        club_id=uuid4(),
        kind=kind,
        uploaded_by=uploader or uuid4(),
        consent_attested=True,
    )
    m.mark_processing()
    m.mark_ready(thumb_file_id=uuid4(), preview_file_id=uuid4(), byte_size=10)
    return m


def test_the_happy_path_and_its_guards() -> None:
    m = Media(id=uuid4(), club_id=uuid4(), kind=MediaKind.PHOTO, uploaded_by=uuid4())
    with pytest.raises(MediaConsentRequiredError):
        m.mark_processing()
    m.consent_attested = True
    m.mark_processing()
    with pytest.raises(MediaStateError):
        m.mark_processing()
    m.mark_ready(thumb_file_id=uuid4(), preview_file_id=uuid4(), byte_size=5)
    assert m.is_served
    with pytest.raises(MediaStateError):
        m.mark_failed()


def test_a_failed_upload_is_never_served() -> None:
    m = Media(id=uuid4(), club_id=uuid4(), kind=MediaKind.VIDEO, uploaded_by=None)
    m.mark_failed()
    assert m.status == MediaStatus.FAILED and not m.is_served


def test_attach_rules() -> None:
    m = ready()
    album, event = uuid4(), uuid4()
    m.attach_to_album(album, 3)
    assert (m.usage, m.album_id, m.position) == (MediaUsage.ALBUM, album, 3)
    with pytest.raises(MediaStateError):
        m.attach_as_cover(event)
    cover = ready()
    cover.attach_as_cover(event)
    assert cover.usage == MediaUsage.EVENT_COVER and cover.album_id is None
    cover.attach_as_cover(event)  # idempotent


def test_only_ready_photos_go_to_announcements_and_covers() -> None:
    video = ready(MediaKind.VIDEO)
    with pytest.raises(Exception, match="media-kind|activities"):
        video.attach_to_announcement(uuid4(), 0)
    raw = Media(id=uuid4(), club_id=uuid4(), kind=MediaKind.PHOTO, uploaded_by=None)
    with pytest.raises(MediaNotReadyError):
        raw.attach_as_cover(uuid4())


def test_hide_restore_and_who_may_restore() -> None:
    uploader, mod = uuid4(), uuid4()
    m = ready(uploader=uploader)
    m.hide(by=uploader, reason=None, source=HiddenSource.UPLOADER)
    assert not m.is_served
    m.restore(by_moderator=False, by=uploader)
    assert m.is_served and m.hidden_source is None
    m.hide(by=mod, reason="x", source=HiddenSource.MODERATOR)
    with pytest.raises(MediaStateError):
        m.restore(by_moderator=False, by=uploader)
    m.restore(by_moderator=True, by=mod)
    assert m.is_served


def test_soft_delete_undo_and_purge_window() -> None:
    m = ready()
    m.soft_delete(NOW)
    assert m.is_gone and not m.is_served
    assert not m.purge_due(NOW + timedelta(days=6), 7)
    assert m.purge_due(NOW + timedelta(days=7), 7)
    m.undelete()
    assert m.is_served and m.deleted_at is None


def test_a_staged_upload_expires() -> None:
    m = Media(id=uuid4(), club_id=uuid4(), kind=MediaKind.PHOTO, uploaded_by=None)
    m.created_at = NOW
    assert not m.staged_expired(NOW + timedelta(hours=23), 24)
    assert m.staged_expired(NOW + timedelta(hours=24), 24)


def test_an_i_am_in_this_photo_report_hides_the_item_at_once() -> None:
    m = ready()
    person = uuid4()
    r = m.report(
        person,
        is_subject=True,
        reason=" please ",
        existing_reporters=frozenset(),
        report_id=uuid4(),
        now=NOW,
    )
    assert m.status == MediaStatus.HIDDEN and m.hidden_source == HiddenSource.REPORT
    assert r.reason == "please" and r.is_subject
    with pytest.raises(MediaAlreadyReportedError):
        m.report(
            person,
            is_subject=True,
            reason="",
            existing_reporters=frozenset({person}),
            report_id=uuid4(),
            now=NOW,
        )


def test_another_report_leaves_the_item_visible_and_resolves_once() -> None:
    m = ready()
    r = m.report(
        uuid4(),
        is_subject=False,
        reason="spam",
        existing_reporters=frozenset(),
        report_id=uuid4(),
        now=NOW,
    )
    assert m.is_served
    r.resolve(upheld=False, by=uuid4(), now=NOW)
    with pytest.raises(MediaStateError):
        r.resolve(upheld=True, by=uuid4(), now=NOW)


def test_limits_resolve_per_club_over_defaults() -> None:
    lim = resolve_limits(
        ClubMediaOverrides(photo_max_bytes=1, quota_bytes=10),
        photo_max_bytes=15 * MIB,
        video_max_bytes=300 * MIB,
        quota_bytes=5000,
    )
    assert (lim.photo_max_bytes, lim.video_max_bytes, lim.quota_bytes) == (
        1,
        300 * MIB,
        10,
    )


def test_size_and_quota_checks() -> None:
    check_size(MediaKind.PHOTO, 15 * MIB, LIMITS)
    with pytest.raises(MediaTooLargeError) as big:
        check_size(MediaKind.PHOTO, 15 * MIB + 1, LIMITS)
    assert big.value.status == 413
    check_size(MediaKind.VIDEO, 300 * MIB, LIMITS)
    with pytest.raises(MediaTypeNotAllowedError):
        check_size(MediaKind.PHOTO, 0, LIMITS)
    check_quota(LIMITS.quota_bytes - 5, 5, LIMITS)
    with pytest.raises(MediaQuotaExceededError):
        check_quota(LIMITS.quota_bytes - 5, 6, LIMITS)


def test_kind_detection() -> None:
    assert kind_for_content_type("image/png; x=y") == MediaKind.PHOTO
    assert kind_for_content_type("video/mp4") == MediaKind.VIDEO
    assert kind_for_name("a.MOV") == MediaKind.VIDEO
    with pytest.raises(MediaTypeNotAllowedError) as err:
        kind_for_name("a.pdf")
    assert err.value.status == 415
    with pytest.raises(MediaTypeNotAllowedError):
        kind_for_content_type("image/svg+xml")


def test_album_depth_is_capped() -> None:
    assert check_album_depth(0) == 1
    assert check_album_depth(2) == 3
    with pytest.raises(AlbumDepthError):
        check_album_depth(3)


def test_visibility_school_members_and_deleted() -> None:
    club = uuid4()
    school = Album(id=uuid4(), club_id=club, title="a")
    assert school.visibility == AlbumVisibility.SCHOOL
    stranger = Viewer(user_id=uuid4())
    assert can_view_album(school, stranger)
    assert not can_view_album(school, Viewer(user_id=uuid4(), signed_in=False))
    closed = Album(
        id=uuid4(),
        club_id=club,
        title="b",
        visibility=AlbumVisibility.MEMBERS,
        event_id=uuid4(),
    )
    assert not can_view_album(closed, stranger)
    assert can_view_album(closed, Viewer(user_id=uuid4(), is_club_person=True))
    assert can_view_album(closed, Viewer(user_id=uuid4(), attended_event=True))
    assert can_view_album(closed, Viewer(user_id=uuid4(), is_platform_staff=True))
    school.delete(NOW)
    assert not can_view_album(school, Viewer(user_id=uuid4(), is_platform_staff=True))


def test_upload_permission_rules() -> None:
    album = Album(id=uuid4(), club_id=uuid4(), title="a")
    member = Viewer(user_id=uuid4(), is_club_person=True)
    assert can_upload_to_album(album, member, has_edit_events=True, blocked=False)
    assert not can_upload_to_album(album, member, has_edit_events=False, blocked=False)
    album.member_uploads = True
    assert can_upload_to_album(album, member, has_edit_events=False, blocked=False)
    assert not can_upload_to_album(
        album, Viewer(user_id=uuid4()), has_edit_events=False, blocked=False
    )
    assert not can_upload_to_album(album, member, has_edit_events=True, blocked=True)


def test_delete_rule_and_moderate_permission() -> None:
    m = ready()
    other = uuid4()
    assert can_delete_media(m, m.uploaded_by, can_moderate=False)
    assert not can_delete_media(m, other, can_moderate=False)
    assert can_delete_media(m, other, can_moderate=True)
    for role in (Role.SU, Role.ACTIVITIES_ADMIN, Role.ADMIN):
        assert Permission.MODERATE_MEDIA in global_permissions({role})
    assert Permission.MODERATE_MEDIA not in global_permissions({Role.STUDENT})


def test_signed_urls_verify_expire_and_reject_tampering() -> None:
    mid = uuid4()
    exp, sig = sign_media_url("k", mid, MediaVariant.THUMB, NOW)
    assert exp - NOW.timestamp() >= 24 * 3600
    verify_media_url("k", mid, MediaVariant.THUMB, exp, sig, NOW)
    assert sign_media_url("k", mid, MediaVariant.THUMB, NOW + timedelta(hours=1)) == (
        exp,
        sig,
    )  # same bucket: cacheable
    for args in (
        ("k2", mid, MediaVariant.THUMB, exp, sig),
        ("k", uuid4(), MediaVariant.THUMB, exp, sig),
        ("k", mid, MediaVariant.ORIGINAL, exp, sig),
        ("k", mid, MediaVariant.THUMB, exp + 1, sig),
        ("k", mid, MediaVariant.THUMB, exp, "0" * 64),
    ):
        with pytest.raises(InvalidMediaUrlError):
            verify_media_url(*args, NOW)
    with pytest.raises(InvalidMediaUrlError):
        verify_media_url(
            "k", mid, MediaVariant.THUMB, exp, sig, NOW + timedelta(days=3)
        )


def test_logo_validation() -> None:
    from app.modules.activities.domain.errors import Denied
    from app.modules.activities.domain.media import validate_logo_file

    me, club, fid = uuid4(), uuid4(), uuid4()
    ok = {
        "actor_id": me,
        "owner_id": me,
        "content_type": "image/png",
        "byte_size": 1,
        "club_id": club,
        "current_logo_id": None,
        "file_id": fid,
    }
    validate_logo_file(**ok)
    with pytest.raises(Denied):
        validate_logo_file(**{**ok, "owner_id": uuid4()})
    validate_logo_file(**{**ok, "owner_id": uuid4(), "current_logo_id": fid})
    with pytest.raises(MediaTypeNotAllowedError):
        validate_logo_file(**{**ok, "content_type": "application/pdf"})
    with pytest.raises(MediaTooLargeError):
        validate_logo_file(**{**ok, "byte_size": 6 * MIB})
