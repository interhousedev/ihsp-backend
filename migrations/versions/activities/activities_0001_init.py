"""activities init: clubs, events, drafting, points, team, club-course links.

Revision ID: activities_0001
Revises:
Create Date: 2026-11-27 18:00:00.000000

Volunteers inventory (spec 4.15, revision 2): no table, file or setting of the
current schema holds IHT Volunteers members, forms, performance, points or
consents (searched every migration branch and the dev database for volunteer,
community and club tables; only the academic excuse category "volunteering" and
admission's essay categories mention the word, neither is member data). There is
therefore nothing to map, deduplicate or reconcile; the club is created by SU
through the application with the `forms`, `drafting`, `points`, `roster`
capabilities. Users and files belong to other modules (no cross-schema foreign
keys).
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "activities_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("activities",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the schema and its tables."""
    op.execute("CREATE SCHEMA IF NOT EXISTS activities")
    op.execute("""
CREATE TABLE activities.activities_announcements (
	id UUID NOT NULL, 
	club_id UUID NOT NULL, 
	author_id UUID NOT NULL, 
	text TEXT NOT NULL, 
	audience VARCHAR(60) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	scheduled_at TIMESTAMP WITH TIME ZONE, 
	sent_at TIMESTAMP WITH TIME ZONE, 
	recipient_count INTEGER NOT NULL, 
	cancelled BOOLEAN NOT NULL, 
	CONSTRAINT pk_activities_announcements PRIMARY KEY (id)
)
        """)
    op.execute("""
CREATE INDEX ix_activities_announcements_club ON activities.activities_announcements (club_id)
        """)
    op.execute("""
CREATE TABLE activities.activities_club_courses (
	id UUID NOT NULL, 
	club_id UUID NOT NULL, 
	course_id UUID NOT NULL, 
	requested_by UUID NOT NULL, 
	requested_side VARCHAR(8) NOT NULL, 
	status VARCHAR(10) NOT NULL, 
	requested_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	confirmed_by UUID, 
	confirmed_at TIMESTAMP WITH TIME ZONE, 
	CONSTRAINT pk_activities_club_courses PRIMARY KEY (id), 
	CONSTRAINT uq_activities_club_courses_club_id UNIQUE (club_id, course_id), 
	CONSTRAINT ck_activities_club_courses_status CHECK (status IN ('pending', 'active', 'ended'))
)
        """)
    op.execute("""
CREATE INDEX ix_activities_club_courses_course ON activities.activities_club_courses (course_id)
        """)
    op.execute("""
CREATE TABLE activities.activities_club_profiles (
	user_id UUID NOT NULL, 
	club_id UUID NOT NULL, 
	answers JSONB NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_activities_club_profiles PRIMARY KEY (user_id, club_id)
)
        """)
    op.execute("""
CREATE TABLE activities.activities_clubs (
	id UUID NOT NULL, 
	slug VARCHAR(40) NOT NULL, 
	kind VARCHAR(8) NOT NULL, 
	name JSONB NOT NULL, 
	created_by UUID NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	join_policy VARCHAR(8) NOT NULL, 
	visibility_public BOOLEAN NOT NULL, 
	contact_enabled BOOLEAN NOT NULL, 
	logo_file_id UUID, 
	published_once BOOLEAN NOT NULL, 
	capabilities JSONB DEFAULT '[]'::jsonb NOT NULL, 
	description TEXT DEFAULT '' NOT NULL, 
	owner_id UUID, 
	has_minor_members BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_activities_clubs PRIMARY KEY (id), 
	CONSTRAINT uq_activities_clubs_slug UNIQUE (slug), 
	CONSTRAINT ck_activities_clubs_kind CHECK (kind IN ('club', 'su')), 
	CONSTRAINT ck_activities_clubs_status CHECK (status IN ('draft', 'pending_review', 'active', 'suspended', 'archived')), 
	CONSTRAINT ck_activities_clubs_join_policy CHECK (join_policy IN ('open', 'request', 'invite'))
)
        """)
    op.execute("""
CREATE TABLE activities.activities_consent_events (
	id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	granted BOOLEAN NOT NULL, 
	at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_activities_consent_events PRIMARY KEY (id)
)
        """)
    op.execute("""
CREATE INDEX ix_activities_consent_events_user ON activities.activities_consent_events (user_id)
        """)
    op.execute("""
CREATE TABLE activities.activities_contact_messages (
	id UUID NOT NULL, 
	club_id UUID NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	email VARCHAR(320) NOT NULL, 
	body TEXT NOT NULL, 
	ip_hash VARCHAR(64) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	status VARCHAR(12) NOT NULL, 
	copied_to_safeguarding BOOLEAN NOT NULL, 
	replied_by UUID, 
	replied_at TIMESTAMP WITH TIME ZONE, 
	CONSTRAINT pk_activities_contact_messages PRIMARY KEY (id)
)
        """)
    op.execute("""
CREATE INDEX ix_activities_contact_messages_club ON activities.activities_contact_messages (club_id)
        """)
    op.execute("""
CREATE TABLE activities.activities_declarations (
	club_id UUID NOT NULL, 
	version INTEGER NOT NULL, 
	goals JSONB NOT NULL, 
	rules JSONB NOT NULL, 
	meeting_schedule JSONB NOT NULL, 
	requirements JSONB NOT NULL, 
	extra JSONB NOT NULL, 
	CONSTRAINT pk_activities_declarations PRIMARY KEY (club_id, version)
)
        """)
    op.execute("""
CREATE TABLE activities.activities_draft_picks (
	id UUID NOT NULL, 
	round_id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	role VARCHAR(60) NOT NULL, 
	status VARCHAR(10) NOT NULL, 
	CONSTRAINT pk_activities_draft_picks PRIMARY KEY (id), 
	CONSTRAINT ck_activities_draft_picks_status CHECK (status IN ('proposed', 'invited', 'accepted', 'declined', 'completed', 'no_show'))
)
        """)
    op.execute("""
CREATE INDEX ix_activities_draft_picks_round ON activities.activities_draft_picks (round_id)
        """)
    op.execute("""
CREATE TABLE activities.activities_draft_rounds (
	id UUID NOT NULL, 
	event_id UUID NOT NULL, 
	club_id UUID NOT NULL, 
	needed JSONB NOT NULL, 
	status VARCHAR(10) NOT NULL, 
	CONSTRAINT pk_activities_draft_rounds PRIMARY KEY (id)
)
        """)
    op.execute("""
CREATE INDEX ix_activities_draft_rounds_club ON activities.activities_draft_rounds (club_id)
        """)
    op.execute("""
CREATE TABLE activities.activities_draft_signups (
	id UUID NOT NULL, 
	round_id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	role VARCHAR(60) NOT NULL, 
	answers JSONB NOT NULL, 
	status VARCHAR(12) NOT NULL, 
	CONSTRAINT pk_activities_draft_signups PRIMARY KEY (id)
)
        """)
    op.execute("""
CREATE INDEX ix_activities_draft_signups_round ON activities.activities_draft_signups (round_id)
        """)
    op.execute("""
CREATE TABLE activities.activities_event_reports (
	event_id UUID NOT NULL, 
	attendance_count INTEGER NOT NULL, 
	summary TEXT NOT NULL, 
	media_file_ids JSONB NOT NULL, 
	outcomes JSONB NOT NULL, 
	published BOOLEAN NOT NULL, 
	CONSTRAINT pk_activities_event_reports PRIMARY KEY (event_id)
)
        """)
    op.execute("""
CREATE TABLE activities.activities_events (
	id UUID NOT NULL, 
	club_id UUID NOT NULL, 
	title JSONB NOT NULL, 
	starts_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	ends_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	capacity INTEGER, 
	rsvp_policy VARCHAR(10) NOT NULL, 
	status VARCHAR(10) NOT NULL, 
	description JSONB, 
	location VARCHAR(300), 
	course_id UUID, 
	opportunity_id UUID, 
	schedule_revision INTEGER NOT NULL, 
	rating_requested_at TIMESTAMP WITH TIME ZONE, 
	created_by UUID, 
	CONSTRAINT pk_activities_events PRIMARY KEY (id), 
	CONSTRAINT ck_activities_events_status CHECK (status IN ('draft', 'scheduled', 'cancelled', 'done')), 
	CONSTRAINT ck_activities_events_rsvp_policy CHECK (rsvp_policy IN ('open', 'members', 'approval'))
)
        """)
    op.execute("""
CREATE INDEX ix_activities_events_opportunity ON activities.activities_events (opportunity_id)
        """)
    op.execute("""
CREATE INDEX ix_activities_events_club ON activities.activities_events (club_id, starts_at)
        """)
    op.execute("""
CREATE TABLE activities.activities_memberships (
	club_id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	role VARCHAR(10) NOT NULL, 
	status VARCHAR(10) NOT NULL, 
	declaration_version INTEGER NOT NULL, 
	joined_at TIMESTAMP WITH TIME ZONE, 
	left_at TIMESTAMP WITH TIME ZONE, 
	CONSTRAINT pk_activities_memberships PRIMARY KEY (club_id, user_id), 
	CONSTRAINT ck_activities_memberships_role CHECK (role IN ('owner', 'co_owner', 'team', 'member')), 
	CONSTRAINT ck_activities_memberships_status CHECK (status IN ('requested', 'active', 'left', 'removed', 'banned'))
)
        """)
    op.execute("""
CREATE UNIQUE INDEX uq_activities_memberships_one_owner ON activities.activities_memberships (club_id) WHERE role = 'owner' AND status = 'active'
        """)
    op.execute("""
CREATE INDEX ix_activities_memberships_user ON activities.activities_memberships (user_id)
        """)
    op.execute("""
CREATE TABLE activities.activities_planner_items (
	id UUID NOT NULL, 
	club_id UUID NOT NULL, 
	kind VARCHAR(20) NOT NULL, 
	title VARCHAR(300) NOT NULL, 
	body TEXT NOT NULL, 
	assignee_id UUID, 
	due_at TIMESTAMP WITH TIME ZONE, 
	status VARCHAR(10) NOT NULL, 
	event_id UUID, 
	term VARCHAR(20) NOT NULL, 
	CONSTRAINT pk_activities_planner_items PRIMARY KEY (id), 
	CONSTRAINT ck_activities_planner_items_status CHECK (status IN ('backlog', 'planned', 'doing', 'done'))
)
        """)
    op.execute("""
CREATE INDEX ix_activities_planner_items_club ON activities.activities_planner_items (club_id)
        """)
    op.execute("""
CREATE TABLE activities.activities_points_ledger (
	id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	source_type VARCHAR(40) NOT NULL, 
	source_id UUID NOT NULL, 
	reason VARCHAR(40) NOT NULL, 
	points INTEGER NOT NULL, 
	at TIMESTAMP WITH TIME ZONE NOT NULL, 
	club_id UUID, 
	CONSTRAINT pk_activities_points_ledger PRIMARY KEY (id), 
	CONSTRAINT uq_activities_points_ledger_source_type UNIQUE (source_type, source_id, user_id, reason)
)
        """)
    op.execute("""
CREATE INDEX ix_activities_points_ledger_club ON activities.activities_points_ledger (club_id, user_id)
        """)
    op.execute("""
CREATE TABLE activities.activities_points_optout (
	user_id UUID NOT NULL, 
	CONSTRAINT pk_activities_points_optout PRIMARY KEY (user_id)
)
        """)
    op.execute("""
CREATE TABLE activities.activities_position_applications (
	id UUID NOT NULL, 
	position_id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	answers JSONB NOT NULL, 
	status VARCHAR(12) NOT NULL, 
	note TEXT, 
	CONSTRAINT pk_activities_position_applications PRIMARY KEY (id)
)
        """)
    op.execute("""
CREATE INDEX ix_activities_position_applications_position ON activities.activities_position_applications (position_id)
        """)
    op.execute("""
CREATE TABLE activities.activities_positions (
	id UUID NOT NULL, 
	club_id UUID NOT NULL, 
	title JSONB NOT NULL, 
	description JSONB NOT NULL, 
	slots INTEGER NOT NULL, 
	open_for_applications BOOLEAN NOT NULL, 
	form_schema JSONB NOT NULL, 
	position_order INTEGER NOT NULL, 
	CONSTRAINT pk_activities_positions PRIMARY KEY (id)
)
        """)
    op.execute("""
CREATE INDEX ix_activities_positions_club ON activities.activities_positions (club_id)
        """)
    op.execute("""
CREATE TABLE activities.activities_ratings (
	id UUID NOT NULL, 
	target_type VARCHAR(8) NOT NULL, 
	target_id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	score INTEGER NOT NULL, 
	aspects JSONB NOT NULL, 
	comment TEXT, 
	anonymous_to_club BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_activities_ratings PRIMARY KEY (id), 
	CONSTRAINT ck_activities_ratings_target_type CHECK (target_type IN ('event', 'club'))
)
        """)
    op.execute("""
CREATE INDEX ix_activities_ratings_target ON activities.activities_ratings (target_type, target_id)
        """)
    op.execute("""
CREATE TABLE activities.activities_rsvps (
	id UUID NOT NULL, 
	event_id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	status VARCHAR(12) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	checked_in_at TIMESTAMP WITH TIME ZONE, 
	check_in_method VARCHAR(10), 
	event_role VARCHAR(40), 
	CONSTRAINT pk_activities_rsvps PRIMARY KEY (id), 
	CONSTRAINT uq_activities_rsvps_event_id UNIQUE (event_id, user_id)
)
        """)
    op.execute("""
CREATE TABLE activities.activities_team_seats (
	id UUID NOT NULL, 
	position_id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	since TIMESTAMP WITH TIME ZONE NOT NULL, 
	until TIMESTAMP WITH TIME ZONE, 
	public BOOLEAN NOT NULL, 
	consent_public BOOLEAN NOT NULL, 
	bio JSONB, 
	experience JSONB NOT NULL, 
	photo_url VARCHAR(2000), 
	consent_changed_at TIMESTAMP WITH TIME ZONE, 
	CONSTRAINT pk_activities_team_seats PRIMARY KEY (id)
)
        """)
    op.execute("""
CREATE INDEX ix_activities_team_seats_position ON activities.activities_team_seats (position_id)
        """)
    op.execute("""
CREATE TABLE activities.activities_transfers (
	id UUID NOT NULL, 
	club_id UUID NOT NULL, 
	from_user UUID NOT NULL, 
	to_user UUID NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	status VARCHAR(10) NOT NULL, 
	CONSTRAINT pk_activities_transfers PRIMARY KEY (id), 
	CONSTRAINT ck_activities_transfers_status CHECK (status IN ('offered', 'accepted', 'declined', 'cancelled', 'expired'))
)
        """)
    op.execute("""
CREATE INDEX ix_activities_transfers_club ON activities.activities_transfers (club_id)
        """)


def downgrade() -> None:
    """Drop the schema."""
    op.execute("DROP SCHEMA IF EXISTS activities CASCADE")
