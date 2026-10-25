"""Request and response models of Web Push."""

from uuid import UUID

from app.modules.notify.domain.push_subscription import MAX_ENDPOINT_LENGTH

from pydantic import BaseModel, ConfigDict, Field


class PushConfigResponse(BaseModel):
    """GET /v1/push/config: whether push is on and the key to subscribe with."""

    enabled: bool
    vapid_public_key: str | None


class PushKeys(BaseModel):
    """The `keys` of a browser's PushSubscription JSON."""

    p256dh: str = Field(min_length=1, max_length=255)
    auth: str = Field(min_length=1, max_length=64)


class PushSubscriptionBody(BaseModel):
    """POST /v1/me/push-subscriptions: `PushSubscription.toJSON()` plus the agent."""

    model_config = ConfigDict(extra="ignore")  # browsers add expirationTime

    endpoint: str = Field(min_length=1, max_length=MAX_ENDPOINT_LENGTH)
    keys: PushKeys
    user_agent: str | None = Field(default=None, max_length=1000)


class PushSubscriptionResponse(BaseModel):
    """The saved subscription."""

    id: UUID


class PushUnsubscribeBody(BaseModel):
    """DELETE /v1/me/push-subscriptions."""

    endpoint: str = Field(min_length=1, max_length=MAX_ENDPOINT_LENGTH)
